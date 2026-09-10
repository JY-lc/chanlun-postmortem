# -*- coding: utf-8 -*-
"""
多资产配置快速预检(用回测池现有ETF, 无需新数据)
资产代表: A股宽基/纳指/黄金/恒生/红利/行业
测试: ①各资产单独持有 ②等权组合(年度再平衡) ③动量轮动(月度选前2)
全部用月末收盘计算信号, 下月首日开盘执行(无前视), 含0.1%单边成本
"""
import pickle, sys, os
import numpy as np
import pandas as pd
sys.path.insert(0, 'work')

with open('data_cache/stock_data.pkl', 'rb') as f:
    sd = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)

ASSETS = {
    '510300': '沪深300(大盘)',
    '510500': '中证500(中盘)',
    '159915': '创业板',
    '513100': '纳指(美股)',
    '518880': '黄金',
    '159920': '恒生(港股)',
    '510880': '红利(A股)',
}
COST = 0.001


def load(tc):
    name, df = sd[tc]
    d = df.copy()
    d['日期'] = pd.to_datetime(d['日期'])
    for c in ['开盘', '收盘']:
        d[c] = pd.to_numeric(d[c], errors='coerce')
    return d.sort_values('日期').set_index('日期')


data = {tc: load(tc) for tc in ASSETS}
# 月频面板
all_dates = sorted(set().union(*[set(d.index) for d in data.values()]))
dts = pd.Series(pd.to_datetime(all_dates))
me = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)

close = pd.DataFrame({tc: d['收盘'].reindex(me).ffill() for tc, d in data.items()})
open1 = {}
for tc, d in data.items():
    o = pd.Series(d['开盘'].values, index=d.index)
    nxt = []
    for t in me:
        after = d.index[d.index > t]
        nxt.append(d.loc[after[0], '开盘'] if len(after) else np.nan)
    open1[tc] = pd.Series(nxt, index=me)
open1 = pd.DataFrame(open1)
ret_exec = close.shift(-1) / open1 - 1          # 执行修正

START = '2016-01-01'
mask = me >= pd.Timestamp(START)
me_use = me[mask]


def perf(r, label):
    r = np.array([x for x in r if x == x])
    if len(r) < 12:
        print(f'{label}: 样本不足')
        return None
    cum = np.cumprod(1 + r)
    years = len(r) / 12
    ann = cum[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ann - 0.02) / vol if vol > 0 else 0
    dd = ((np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)).max()
    print(f'{label:<30} 年化{ann:+7.2%} 波动{vol:6.2%} 夏普{sh:+5.2f} 回撤{dd:6.2%}')
    return {'ann': ann, 'vol': vol, 'sharpe': sh, 'dd': dd, 'rets': r}


print(f'样本: {me_use[0].date()} ~ {me_use[-1].date()}\n')
print('===== ① 各资产单独持有(执行修正, 无成本) =====')
singles = {}
for tc, nm in ASSETS.items():
    r = ret_exec.loc[me_use[:-1], tc].values
    singles[tc] = perf(r, f'{tc} {nm}')

print('\n===== ② 等权组合(每月再平衡, 净0.1%) =====')
r_list = []
for i, t in enumerate(me_use[:-1]):
    y = ret_exec.loc[t].dropna()
    r_list.append(y.mean() - COST * (2 * (len(y) - 1) / len(y)))
perf(r_list, '等权6资产月度再平衡')

print('\n===== ③ 动量轮动(月度选过去6月动量前2, 净0.1%) =====')
mom = close / close.shift(6) - 1
r_list = []
prev = set()
for i, t in enumerate(me_use[:-1]):
    if t not in mom.index:
        continue
    j = list(mom.index).index(t)
    if j < 6:
        continue
    m = mom.loc[t].dropna()
    if len(m) < 3:
        continue
    sel = list(m.sort_values(ascending=False).index[:2])
    y = ret_exec.loc[t]
    s = y[sel].dropna()
    if s.empty:
        continue
    to = 1 - len(set(s.index) & prev) / len(s) if prev else 1.0
    r_list.append(s.mean() - to * 2 * COST)
    prev = set(s.index)
perf(r_list, '动量前2轮动')

print('\n===== ④ 等权 + 趋势过滤(各资产在自身MA10月上才持有) =====')
r_list = []
ma = close.rolling(10).mean()
for t in me_use[:-1]:
    if t not in ma.index:
        continue
    y = ret_exec.loc[t]
    on = [tc for tc in ASSETS if tc in ma.columns and ma.loc[t, tc] == ma.loc[t, tc]
          and close.loc[t, tc] == close.loc[t, tc] and close.loc[t, tc] > ma.loc[t, tc]]
    if not on:
        r_list.append(0.0)
        continue
    r_list.append(y[on].dropna().mean())
perf(r_list, '趋势过滤等权')

print('\n===== 逐年(等权6资产) =====')
val = pd.Series(1.0, index=me_use[1:1 + len([1])])
eq = np.cumprod(1 + np.array([x for x in [ret_exec.loc[t, list(ASSETS)].dropna().mean() for t in me_use[:-1]]]))
sd_eq = pd.Series(eq, index=me_use[1:len(eq) + 1])
yr = sd_eq.resample('YE').last()
prev = 1.0
for d, v in yr.items():
    print(f'  {d.year}: {v/prev-1:+.2%}')
    prev = v
