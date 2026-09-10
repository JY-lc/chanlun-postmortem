# -*- coding: utf-8 -*-
"""风险平价(等风险贡献)配置测试 - 先验方法, 不做参数优化"""
import pickle, sys
import numpy as np
import pandas as pd
sys.path.insert(0, 'work')

with open('data_cache/stock_data.pkl', 'rb') as f:
    sd = pickle.load(f)

ASSETS = {'510300': '沪深300', '510500': '中证500', '159915': '创业板',
          '513100': '纳指', '518880': '黄金', '159920': '恒生', '510880': '红利'}
COST = 0.001
MAXW = 0.40


def load(tc):
    name, df = sd[tc]
    d = df.copy()
    d['日期'] = pd.to_datetime(d['日期'])
    for c in ['开盘', '收盘']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.sort_values('日期').set_index('日期')


data = {tc: load(tc) for tc in ASSETS}
all_dates = sorted(set().union(*[set(d.index) for d in data.values()]))
dts = pd.Series(pd.to_datetime(all_dates))
me = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
close = pd.DataFrame({tc: d['收盘'].reindex(me).ffill() for tc, d in data.items()})

# 执行修正收益: 下月末收盘/次月首日开盘-1
open1 = {}
for tc, d in data.items():
    nxt = []
    for t in me:
        after = d.index[d.index > t]
        nxt.append(d.loc[after[0], '开盘'] if len(after) else np.nan)
    open1[tc] = pd.Series(nxt, index=me)
open1 = pd.DataFrame(open1)
ret_exec = close.shift(-1) / open1 - 1

# 日频用于波动估计
daily_ret = pd.DataFrame({tc: d['收盘'].pct_change() for tc, d in data.items()})
vol_daily = daily_ret.rolling(60).std()
vol_me = vol_daily.reindex(me, method='ffill') * np.sqrt(252)
ma10 = close.rolling(10).mean()

me_use = me[me >= pd.Timestamp('2017-01-01')]  # 留出波动估计预热
print(f'样本: {me_use[0].date()} ~ {me_use[-1].date()}\n')


def perf(r, label, rets_detail=None):
    r = np.array([x for x in r if x == x])
    cum = np.cumprod(1 + r); years = len(r) / 12
    ann = cum[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ann - 0.02) / vol if vol > 0 else 0
    dd = ((np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)).max()
    print(f'{label:<32} 年化{ann:+7.2%} 波动{vol:6.2%} 夏普{sh:+5.2f} 回撤{dd:6.2%}')
    return {'ann': ann, 'sharpe': sh, 'dd': dd}


# 1) 等权
r1 = [ret_exec.loc[t, list(ASSETS)].dropna().mean() for t in me_use[:-1]]
perf(r1, '① 等权(月度再平衡)')

# 2) 风险平价(1/vol)
r2 = []
w_prev = None
for t in me_use[:-1]:
    v = vol_me.loc[t].dropna()
    v = v[[c for c in v.index if c in ASSETS and v[c] == v[c] and v[c] > 0]]
    if len(v) < 3:
        r2.append(0.0); continue
    w = (1 / v) / (1 / v).sum()
    w = w.clip(upper=MAXW); w = w / w.sum()
    y = ret_exec.loc[t]
    s = y[w.index].dropna()
    w2 = w[s.index]; w2 = w2 / w2.sum()
    if w_prev is not None:
        allk = w2.index.union(w_prev.index)
        to = float(np.abs(w2.reindex(allk).fillna(0) - w_prev.reindex(allk).fillna(0)).sum())
    else:
        to = 1.0
    r2.append((s * w2).sum() - to * COST)
    w_prev = w2
perf(r2, '② 风险平价(1/vol, 上限40%)')

# 3) 风险平价 + 趋势过滤(资产在MA10月上方才纳入)
r3 = []
w_prev = None
for t in me_use[:-1]:
    on = [c for c in ASSETS if close.loc[t, c] == close.loc[t, c] and ma10.loc[t, c] == ma10.loc[t, c]
          and close.loc[t, c] > ma10.loc[t, c]]
    if len(on) < 2:
        r3.append(0.0); w_prev = None; continue
    v = vol_me.loc[t, on].dropna()
    v = v[v > 0]
    if len(v) < 2:
        r3.append(0.0); w_prev = None; continue
    w = (1 / v) / (1 / v).sum()
    w = w.clip(upper=MAXW); w = w / w.sum()
    y = ret_exec.loc[t]
    s = y[w.index].dropna()
    w2 = w[s.index]; w2 = w2 / w2.sum()
    if w_prev is not None:
        allk = w2.index.union(w_prev.index)
        to = float(np.abs(w2.reindex(allk).fillna(0) - w_prev.reindex(allk).fillna(0)).sum())
    else:
        to = 1.0
    r3.append((s * w2).sum() - to * COST)
    w_prev = w2
perf(r3, '③ 风险平价+趋势过滤')

# 逐年(③)
print('\n逐年(③ 风险平价+趋势过滤):')
eq = np.cumprod(1 + np.array(r3))
s = pd.Series(eq, index=me_use[1:len(eq) + 1])
yr = s.resample('YE').last()
prev = 1.0
for d, v in yr.items():
    print(f'  {d.year}: {v/prev-1:+.2%}')
    prev = v

# 成本敏感
print('\n成本敏感(③):')
for c in [0.0, 0.001, 0.003]:
    rr = []
    w_prev = None
    for t in me_use[:-1]:
        on = [x for x in ASSETS if close.loc[t, x] == close.loc[t, x] and ma10.loc[t, x] == ma10.loc[t, x] and close.loc[t, x] > ma10.loc[t, x]]
        if len(on) < 2:
            rr.append(0.0); w_prev = None; continue
        v = vol_me.loc[t, on].dropna(); v = v[v > 0]
        if len(v) < 2:
            rr.append(0.0); w_prev = None; continue
        w = (1 / v) / (1 / v).sum(); w = w.clip(upper=MAXW); w = w / w.sum()
        y = ret_exec.loc[t]; ss = y[w.index].dropna()
        w2 = w[ss.index]; w2 = w2 / w2.sum()
        to = 1.0 if w_prev is None else float(np.abs(w2.reindex(w2.index.union(w_prev.index)).fillna(0) - w_prev.reindex(w2.index.union(w_prev.index)).fillna(0)).sum())
        rr.append((ss * w2).sum() - to * c)
        w_prev = w2
    perf(rr, f'  单边{c:.2%}')
