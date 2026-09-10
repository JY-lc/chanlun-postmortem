# -*- coding: utf-8 -*-
"""
重建方向可行性探针: 用确认制引擎测试"当日可算"的信号原型
说明: 原型信号只用截至当日收盘的数据(无确认滞后), 复用引擎的仓位/止损/风控。
      本探针不做参数优化(防过拟合), 只判断方向是否存在边缘。
"""
import sys, os, io, contextlib, pickle, importlib
sys.path.insert(0, 'work')
import numpy as np
import pandas as pd
import config
from chanlun.core import RawKline
from chanlun.signal import Signal
from chanlun.backtest import BacktestEngine

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)


def rsi(close, n=14):
    d = close.diff()
    up = d.clip(lower=0).ewm(alpha=1/n, adjust=False).mean()
    dn = (-d.clip(upper=0)).ewm(alpha=1/n, adjust=False).mean()
    return 100 - 100 / (1 + up / dn)


def build_signals(df, kind):
    """返回 [(date, 'buyM'|'sellM'), ...]"""
    c, o, h, l, v = df['收盘'], df['开盘'], df['最高'], df['最低'], df['成交量']
    ma20, ma60 = c.rolling(20).mean(), c.rolling(60).mean()
    v20 = v.rolling(20).mean()
    new_high20 = h.rolling(20).max().shift(1)
    r14 = rsi(c, 14)
    out = []
    for i in range(60, len(df)):
        d = str(df['日期'].iloc[i])[:10]
        if kind == 'P1_趋势突破':
            if (c.iloc[i] > new_high20.iloc[i] and ma20.iloc[i] > ma60.iloc[i]
                    and v.iloc[i] > 1.2 * v20.iloc[i]):
                out.append((d, 'buyM'))
            elif c.iloc[i] < ma20.iloc[i]:
                out.append((d, 'sellM'))
        elif kind == 'P2_超跌企稳':
            if r14.iloc[i] < 32 and c.iloc[i] > o.iloc[i] and v.iloc[i] < 0.9 * v20.iloc[i]:
                out.append((d, 'buyM'))
            elif c.iloc[i] > ma20.iloc[i]:
                out.append((d, 'sellM'))
        elif kind == 'P3_多头回踩':
            if (ma20.iloc[i] > ma60.iloc[i] and l.iloc[i] <= ma20.iloc[i] * 1.005
                    and c.iloc[i] > ma20.iloc[i] and v.iloc[i] < v20.iloc[i]):
                out.append((d, 'buyM'))
            elif c.iloc[i] < ma20.iloc[i] * 0.98:
                out.append((d, 'sellM'))
    return out


def run(kind):
    sigmap = {}
    for sym, (name, df) in stock_data.items():
        corr = [Signal(signal_type=t, date=d, price=0.0, description=kind)
                for d, t in build_signals(df, kind)]
        sigmap[sym] = corr
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = e.run(stock_data, signals_override=sigmap)[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    hold = sum(t.hold_days for t in sells) / max(len(sells), 1)
    print(f'[{kind}] 年化{r.annual_return:.2%} 回撤{r.max_drawdown:.2%} 夏普{r.sharpe_ratio:.2f} '
          f'胜率{r.win_rate:.2%} 盈亏比{r.profit_loss_ratio:.2f} 买入{len(buys)}笔 '
          f'期末{r.final_capital:,.0f} 持仓{hold:.1f}天')
    return r


print('对照: 原缠论(确认制) 年化2.05% 回撤5.55% 夏普-0.15')
print('     沪深300持有 年化-0.85%')
for k in ['P1_趋势突破', 'P2_超跌企稳', 'P3_多头回踩']:
    run(k)
