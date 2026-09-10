# -*- coding: utf-8 -*-
"""EP组合分年度稳定性 + 与基准对比"""
import sys
import numpy as np
import pandas as pd
import combo_precheck as cp

pool = sys.argv[1] if len(sys.argv) > 1 else 'csi1000'
facs, ret_next, month_end = cp.build_panels(pool)
TOPN = 50

rows = []
prev_sel = set()
for dt in month_end[:-1]:
    x = facs['EP'].loc[dt].dropna()
    y = ret_next.loc[dt].dropna()
    common = x.index.intersection(y.index)
    if len(common) < TOPN + 10:
        continue
    sel = list(x[common].sort_values(ascending=False).index[:TOPN])
    to = 1 - len(set(sel) & prev_sel) / TOPN if prev_sel else 1.0
    gross = y[sel].mean()
    net = gross - to * 2 * 0.001
    bench = y[common].mean()
    rows.append({'date': dt, 'ep_net': net, 'bench': bench})
    prev_sel = set(sel)

df = pd.DataFrame(rows)
df['year'] = pd.to_datetime(df['date']).dt.year
print(f'池={pool} EP组合(选高{TOPN}只, 净0.1%滑点) 分年度:')
print(f'{"年份":<6}{"EP组合":>10}{"基准":>10}{"超额":>10}')
for y, g in df.groupby('year'):
    ep = np.prod(1 + g['ep_net']) - 1
    bm = np.prod(1 + g['bench']) - 1
    print(f'{y:<6}{ep:>+10.2%}{bm:>+10.2%}{ep-bm:>+10.2%}')
all_ep = np.prod(1 + df['ep_net']) - 1
all_bm = np.prod(1 + df['bench']) - 1
print(f'{"全期":<6}{all_ep:>+10.2%}{all_bm:>+10.2%}{all_ep-all_bm:>+10.2%}')
win_years = sum(1 for y, g in df.groupby('year')
                if np.prod(1 + g['ep_net']) > np.prod(1 + g['bench']))
print(f'\n跑赢基准的年份: {win_years}/{df["year"].nunique()}')
