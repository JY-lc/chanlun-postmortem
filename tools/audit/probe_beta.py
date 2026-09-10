# -*- coding: utf-8 -*-
"""β基准探针: 池内标的等权买入持有的年化(判断策略是否有β之上的价值)"""
import sys, pickle
sys.path.insert(0, 'work')
import numpy as np
import pandas as pd
import config

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)

pool = config.BACKTEST_STOCKS
etfs = [k for k in pool if k.startswith(('51', '15', '56', '58', '159'))]
stks = [k for k in pool if k not in etfs]


def hold_return(symbols, label):
    """等权买入持有(标的上市首日起, 用上市后首末收盘; 汇总为组合年化)"""
    rets = []
    for s in symbols:
        df = stock_data.get(s, (None, None))[1]
        if df is None or len(df) < 100:
            continue
        r = df['收盘'].iloc[-1] / df['收盘'].iloc[0] - 1
        days = (pd.to_datetime(df['日期'].iloc[-1]) - pd.to_datetime(df['日期'].iloc[0])).days
        if days > 0:
            ann = (1 + r) ** (365.25 / days) - 1
            rets.append(ann)
    rets = np.array(rets)
    print(f'{label}: 标的数{len(rets)} | 平均年化{rets.mean():+.2%} 中位{np.median(rets):+.2%} '
          f'正收益占比{(rets>0).mean():.0%}')


hold_return(list(pool.keys()), '全池58只等权持有')
hold_return(etfs, '仅ETF(33只)')
hold_return(stks, '仅股票(25只)')

# 指数基准
i = idx.copy()
i['日期'] = pd.to_datetime(i['日期'])
tot = i['收盘'].iloc[-1] / i['收盘'].iloc[0] - 1
days = (i['日期'].iloc[-1] - i['日期'].iloc[0]).days
print(f'沪深300: 总{tot:+.1%} 年化{(1+tot)**(365.25/days)-1:+.2%}')
print('\n(参考: 原缠论确认制 年化+2.05%/夏普-0.15; 无风险利率~2%)')
