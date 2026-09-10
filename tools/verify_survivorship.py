# -*- coding: utf-8 -*-
"""验证: 中证1000指数(无偏) vs 当前成分股等权(含幸存者偏差) 同一时期对比"""
import pickle
import pandas as pd
import numpy as np
import factor_ic2 as fi

idx = pickle.load(open('data_cache/csi1000_index.pkl', 'rb'))
idx['日期'] = pd.to_datetime(idx['日期'])
idx = idx.set_index('日期').sort_index()

mem, px, fin = fi.load_pool('csi1000')
arr = fi.build_arrays(px)

S, E = '2016-01-04', '2026-08-28'


def ann(series):
    s = series.dropna()
    if len(s) < 100:
        return np.nan
    years = (s.index[-1] - s.index[0]).days / 365.25
    return (s.iloc[-1] / s.iloc[0]) ** (1 / years) - 1


# 1) 指数(无偏): 中证1000
i = idx['收盘'][(idx.index >= S) & (idx.index <= E)]
print(f'中证1000指数    : 年化 {ann(i):+.2%}  ({i.index[0].date()}~{i.index[-1].date()}, 无幸存者偏差)')

# 2) 当前成分股等权(含幸存者偏差)
rets = []
for tc, (dates, c, v) in arr.items():
    s = pd.Series(c, index=pd.to_datetime(dates))
    s = s[(s.index >= S) & (s.index <= E)]
    a = ann(s)
    if a == a:
        rets.append(a)
print(f'当前1000成分等权: 平均年化 {np.mean(rets):+.2%} (中位{np.median(rets):+.2%}, n={len(rets)})')
print(f'  → 差异约 {np.mean(rets) - ann(i):+.1f}pp/年: 主要来自"用2026年成分股回溯历史"的幸存者偏差')

# 3) 上市满5年的子样本(部分消除"次新股"偏差, 但仍含幸存者偏差)
old = []
for tc, (dates, c, v) in arr.items():
    d = pd.to_datetime(dates)
    if d[0] <= pd.Timestamp('2016-01-04'):
        s = pd.Series(c, index=d)
        s = s[(s.index >= S) & (s.index <= E)]
        a = ann(s)
        if a == a:
            old.append(a)
print(f'2016年已上市成分等权: 平均年化 {np.mean(old):+.2%} (n={len(old)})')

print('\n结论: 指数(市值加权, 实时成分)才是无偏基准; "用当前成分回溯"会系统性高估。')
