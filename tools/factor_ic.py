# -*- coding: utf-8 -*-
"""
P2 因子IC扫描 (横截面, 月度调仓, 2017-2026, 沪深300)
- 纯统计检验, 不涉及交易
- 财务因子严格按 report_date_ms(实际披露日) 对齐, 避免前视
- 门槛参考: |IC均值|>0.03 且 IR>0.3 才进入P3组合回测
"""
import pickle, time
import numpy as np
import pandas as pd

fin = pickle.load(open('data_cache/hs300_financials.pkl', 'rb'))
px = pickle.load(open('data_cache/hs300_prices.pkl', 'rb'))
mem = pickle.load(open('data_cache/hs300_members.pkl', 'rb'))
codes = [m['thscode'] for m in mem]
print(f'标的 {len(codes)}, 财务 {len(fin)}, 价格 {len(px)}')


def to_df(rows):
    if not rows:
        return None
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date_ms'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
    for c in ['open_price', 'high_price', 'low_price', 'close_price', 'volume', 'turnover']:
        if c in df:
            df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.sort_values('date').drop_duplicates('date').reset_index(drop=True)


print('构建价格面板...')
pxdf = {}
for tc in codes:
    d = to_df(px.get(tc))
    if d is not None and len(d) > 300:
        pxdf[tc] = d.set_index('date')

# 月末交易日序列
all_dates = sorted(set().union(*[set(d.index) for d in pxdf.values()]))
dts = pd.Series(pd.to_datetime(all_dates))
month_end = dts.groupby([dts.dt.year, dts.dt.month]).max().values
month_end = pd.to_datetime(month_end)
print(f'月份数 {len(month_end)}: {month_end[0].date()} ~ {month_end[-1].date()}')

# 月份收益(用月末收盘)
close_panel = pd.DataFrame({tc: d['close_price'] for tc, d in pxdf.items()})
close_me = close_panel.reindex(month_end).ffill()
ret_next = close_me.shift(-1) / close_me - 1   # 下月收益

print('计算价格类因子...')
fac = {}


def factor_at(tc, dt, name):
    d = pxdf[tc]
    hist = d.loc[:dt]
    if len(hist) < 260:
        return np.nan
    c = hist['close_price'].values
    if name == 'MOM12_1':
        return c[-22] / c[-252] - 1 if len(c) >= 252 else np.nan
    if name == 'REV1':
        return c[-1] / c[-22] - 1 if len(c) >= 22 else np.nan
    if name == 'VOL60':
        r = np.diff(c[-61:]) / c[-61:-1]
        return r.std() * np.sqrt(252) if len(r) > 10 else np.nan
    if name == 'LIQ':
        v = hist['volume'].values
        return np.mean(v[-20:]) / (np.mean(v[-250:]) + 1e-9) if len(v) >= 250 else np.nan
    return np.nan


price_facs = ['MOM12_1', 'REV1', 'VOL60', 'LIQ']
panels = {f: pd.DataFrame(index=month_end, columns=codes, dtype=float) for f in price_facs}
t0 = time.time()
for tc in list(pxdf.keys()):
    for dt in month_end:
        for f in price_facs:
            panels[f].loc[dt, tc] = factor_at(tc, dt, f)
print(f'  价格因子完成 {time.time()-t0:.0f}s')

# ===== 财务因子(按披露日对齐) =====
print('计算财务类因子...')


def fin_factors(tc):
    """返回 DataFrame: index=可用起始日, cols=因子值(按 fiscal_year)"""
    e = fin.get(tc) or {}
    inc = e.get('income') or []
    bal = e.get('balance') or []
    if not inc or not bal:
        return None
    inc_by = {i['fiscal_year']: i for i in inc if i.get('period_end_ms')}
    bal_by = {i['fiscal_year']: i for i in bal if i.get('period_end_ms')}
    recs = []
    for y, i in inc_by.items():
        b = bal_by.get(y)
        if not b:
            continue
        avail = min(i.get('report_date_ms') or 0, b.get('report_date_ms') or 0)
        if not avail:
            continue
        oi = i.get('operating_income'); oc = i.get('operating_costs')
        npf = i.get('parent_holder_net_profit') or i.get('net_profit')
        eps = i.get('basic_eps')
        eq = b.get('holder_equity_total'); at = b.get('assets_total'); td = b.get('total_debt')
        prev = inc_by.get(y - 1) or {}
        oi_prev = prev.get('operating_income')
        rec = {'avail_ms': avail, 'year': y,
               'ROE': (npf / eq) if (npf and eq and eq > 0) else np.nan,
               'GROWTH': ((oi / oi_prev - 1) if (oi and oi_prev and oi_prev > 0) else np.nan),
               'MARGIN': ((oi - oc) / oi) if (oi and oc and oi > 0) else np.nan,
               'LEV': (td / at) if (td is not None and at and at > 0) else np.nan,
               'EPS': eps}
        recs.append(rec)
    if not recs:
        return None
    return pd.DataFrame(recs).sort_values('avail_ms')


fin_facs = ['ROE', 'GROWTH', 'MARGIN', 'LEV']
fin_panels = {f: pd.DataFrame(index=month_end, columns=codes, dtype=float) for f in fin_facs}
ep_panel = pd.DataFrame(index=month_end, columns=codes, dtype=float)
for tc in codes:
    fd = fin_factors(tc)
    if fd is None:
        continue
    d = pxdf.get(tc)
    for dt in month_end:
        avail = fd[fd['avail_ms'] <= int(dt.timestamp() * 1000)]
        if avail.empty:
            continue
        row = avail.iloc[-1]
        for f in fin_facs:
            fin_panels[f].loc[dt, tc] = row[f]
        if d is not None and dt in d.index and row['EPS'] is not None and row['EPS'] > 0:
            ep_panel.loc[dt, tc] = row['EPS'] / d.loc[dt, 'close_price']

all_panels = {**panels, **fin_panels, 'EP': ep_panel}

# ===== IC 统计 =====
print('\n' + '=' * 78)
print(f'{"因子":<10}{"IC均值":>9}{"IC标准差":>10}{"IR":>8}{"IC>0占比":>10}{"t值":>8}{"样本月":>7}  判定')
print('-' * 78)
summary = []
for f, p in all_panels.items():
    ics = []
    for dt in month_end[:-1]:
        x = p.loc[dt].dropna()
        y = ret_next.loc[dt].dropna()
        common = x.index.intersection(y.index)
        if len(common) < 30:
            continue
        ic = x[common].rank().corr(y[common].rank())  # 秩相关(spearman等价), 不依赖scipy
        if not np.isnan(ic):
            ics.append(ic)
    if not ics:
        print(f'{f:<10} 无有效样本')
        continue
    ics = np.array(ics)
    mean, sd = ics.mean(), ics.std(ddof=1)
    ir = mean / sd if sd > 0 else 0
    tval = mean / (sd / np.sqrt(len(ics))) if sd > 0 else 0
    win = (ics > 0).mean()
    verdict = '★通过' if (abs(mean) > 0.03 and abs(ir) > 0.3) else '不达标'
    print(f'{f:<10}{mean:>+9.4f}{sd:>10.4f}{ir:>+8.2f}{win:>10.1%}{tval:>+8.2f}{len(ics):>7}  {verdict}')
    summary.append({'factor': f, 'ic': mean, 'ir': ir, 'win': win, 't': tval, 'n': len(ics)})

pd.DataFrame(summary).to_csv('data_cache/factor_ic_summary.csv', index=False)
print('\n门槛: |IC|>0.03 且 |IR|>0.3 → 进入P3组合回测')
print('已保存 data_cache/factor_ic_summary.csv')
