# -*- coding: utf-8 -*-
"""
① 小盘β + 风控 工程化与验收
================================
基准: 中证1000指数(000852) 买入持有
风控组件(逐层叠加, 全部只用截至当日数据, 无前视):
  1) 趋势过滤: 收盘>MA60 且 MA20>MA60 → 持有, 否则空仓
  2) 波动率目标: 仓位 = min(1, 目标波动/20日已实现波动)
  3) 回撤控制: 从净值高点回撤>阈值 → 仓位减半(直到回撤修复)
执行: t日收盘计算目标仓位 → t+1日收益按目标仓位计, 调仓成本=|Δ仓位|×单边成本
"""
import sys, os, pickle
import numpy as np
import pandas as pd

sys.path.insert(0, 'work')
from data_fetcher import fetch_index_data

CACHE = 'data_cache'
IDX_FILE = f'{CACHE}/csi1000_index.pkl'


def load_index():
    if os.path.exists(IDX_FILE):
        df = pickle.load(open(IDX_FILE, 'rb'))
    else:
        df = fetch_index_data('000852', '20140101', '20260828')
        pickle.dump(df, open(IDX_FILE, 'wb'))
    df = df.copy()
    df['日期'] = pd.to_datetime(df['日期'])
    for c in ['开盘', '最高', '最低', '收盘']:
        df[c] = pd.to_numeric(df[c], errors='coerce')
    return df.sort_values('日期').reset_index(drop=True)


def build_positions(df, use_trend=True, use_vol=True, target_vol=0.15,
                    use_dd=False, dd_trigger=0.15, dd_scale=0.5):
    c = df['收盘']
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    ret = c.pct_change()
    vol20 = ret.rolling(20).std() * np.sqrt(252)
    pos = pd.Series(1.0, index=df.index)
    if use_trend:
        pos *= ((c > ma60) & (ma20 > ma60)).astype(float)
    if use_vol:
        pos *= np.minimum(1.0, target_vol / vol20).clip(0, 1).fillna(1.0)
    if use_dd:
        # 回撤控制: 基于"策略自身净值"的事前近似 -> 用指数回撤(保守, 不引入前视)
        peak = c.cummax()
        dd = (peak - c) / peak
        pos *= np.where(dd > dd_trigger, dd_scale, 1.0)
    return pos.fillna(0.0)


def backtest(df, pos, cost=0.0005, rf=0.02):
    ret = df['收盘'].pct_change().fillna(0.0).values
    p = pos.values
    p_lag = np.concatenate([[0.0], p[:-1]])           # t仓位在t+1生效
    turnover = np.abs(np.diff(np.concatenate([[0.0], p_lag])))
    strat = p_lag[:-1] * ret[1:] - turnover[:-1] * cost  # 对齐
    strat = np.concatenate([[0.0], strat])
    dates = df['日期'].values
    eq = np.cumprod(1 + strat)
    years = (df['日期'].iloc[-1] - df['日期'].iloc[0]).days / 365.25
    ann = eq[-1] ** (1 / years) - 1
    vol = pd.Series(strat).std() * np.sqrt(252)
    sharpe = (ann - rf) / vol if vol > 0 else 0
    peak = np.maximum.accumulate(eq)
    dd = ((peak - eq) / peak).max()
    calmar = ann / dd if dd > 0 else np.nan
    return {'ann': ann, 'vol': vol, 'sharpe': sharpe, 'dd': dd, 'calmar': calmar,
            'turnover': np.abs(np.diff(p_lag)).sum() / years,
            'eq': eq, 'dates': dates, 'pos': p}


def show(label, m):
    print(f'{label:<32} 年化{m["ann"]:+7.2%} 波动{m["vol"]:6.2%} 夏普{m["sharpe"]:+5.2f} '
          f'回撤{m["dd"]:6.2%} Calmar{m["calmar"]:5.2f} 年换手{m["turnover"]:5.1f}')


def yearly(m):
    s = pd.Series(m['eq'], index=pd.to_datetime(m['dates']))
    y = s.resample('YE').last()
    prev = 1.0
    out = []
    for d, v in y.items():
        out.append((d.year, v / prev - 1))
        prev = v
    return out


if __name__ == '__main__':
    df = load_index()
    print(f'中证1000指数: {len(df)}根 {df["日期"].iloc[0].date()} ~ {df["日期"].iloc[-1].date()}\n')
    print('===== 全样本(2014-2026) 净0.05%单边成本 =====')
    ms = {}
    ms['基准:买入持有'] = backtest(df, build_positions(df, False, False), cost=0.0)
    ms['趋势过滤'] = backtest(df, build_positions(df, True, False))
    ms['波动率目标15%'] = backtest(df, build_positions(df, False, True))
    ms['趋势+波动率目标'] = backtest(df, build_positions(df, True, True))
    ms['趋势+波动率+回撤控制'] = backtest(df, build_positions(df, True, True, True, 0.15, 0.5))
    for k, v in ms.items():
        show(k, v)

    print('\n===== 成本敏感(趋势+波动率目标) =====')
    for c in [0.0, 0.0005, 0.001, 0.002]:
        show(f'单边{c:.2%}', backtest(df, build_positions(df, True, True), cost=c))

    print('\n===== 样本外分段: 2014-2020 开发 / 2021-2026 验证 =====')
    for name, (s, e) in [('开发2014-2020', ('2014-01-01', '2020-12-31')),
                         ('验证2021-2026', ('2021-01-01', '2026-12-31'))]:
        sub = df[(df['日期'] >= s) & (df['日期'] <= e)].reset_index(drop=True)
        print(f'-- {name} --')
        show('  买入持有', backtest(sub, build_positions(sub, False, False), cost=0.0))
        show('  趋势+波动率目标', backtest(sub, build_positions(sub, True, True)))

    print('\n===== 逐年(趋势+波动率目标) =====')
    for y, r in yearly(ms['趋势+波动率目标']):
        b = dict(yearly(ms['基准:买入持有']))[y]
        print(f'  {y}: 策略{r:+.2%}  持有{b:+.2%}  差{r-b:+.2%}')
