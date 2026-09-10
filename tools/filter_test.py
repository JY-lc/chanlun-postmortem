# -*- coding: utf-8 -*-
"""
最后尝试: 在「缠论确认制信号」上加 MACD / 布林 辅助确认, 看是否改善
================================================================
- 基线: 确认制策略(消除未来函数后的真实口径)
- 过滤只作用于买点; 指标在信号日当天计算(只用截至当日数据, 无未来)
- 注: 原策略的"背驰"已用 MACD 面积, 本实验测的是"额外的一层确认"
"""
import sys, os, io, contextlib, pickle, importlib
sys.path.insert(0, 'work')
import numpy as np
import pandas as pd
import config
from chanlun.core import ChanLunAnalyzer, RawKline, calculate_macd
from chanlun.signal import SignalDetector, Signal
from chanlun.backtest import BacktestEngine, resolve_confirmation_dates

with open('data_cache/stock_data.pkl', 'rb') as f:
    sd = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)

engine = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
engine.set_market_env(idx)
env_map = engine.env_map


def df_to_klines(df):
    ks = []
    for i, row in df.iterrows():
        ks.append(RawKline(date=str(row['日期'])[:10], open=float(row['开盘']), high=float(row['最高']),
                           low=float(row['最低']), close=float(row['收盘']),
                           volume=float(row.get('成交量', 0)), index=len(ks)))
    return ks


# 1) 构建确认制信号 + 指标
print('构建确认制信号与指标...')
conf_signals = {}
ind = {}
for sym, (name, df) in sd.items():
    kl = df_to_klines(df)
    d = pd.DataFrame({'date': [k.date for k in kl], 'close': [k.close for k in kl]})
    dif, dea, hist = calculate_macd(d['close'].tolist(), 12, 26, 9)
    d['dif'] = dif; d['dea'] = dea; d['hist'] = hist
    d['mid'] = d['close'].rolling(20).mean()
    std = d['close'].rolling(20).std()
    d['up'] = d['mid'] + 2 * std
    d['lo'] = d['mid'] - 2 * std
    d['gold'] = (d['dif'] > d['dea']) & (d['dif'].shift(1) <= d['dea'].shift(1))
    d['gold5'] = d['gold'].rolling(5).max().fillna(0) > 0
    d['lo_up'] = (d['close'] > d['lo']) & (d['close'].shift(1) <= d['lo'].shift(1))
    ind[sym] = d.set_index('date')

    an = ChanLunAnalyzer(); an.analyze(kl)
    raw = SignalDetector(env_map).detect(kl, an)
    fixed, _ = resolve_confirmation_dates(kl, an, raw, env_map)
    conf_signals[sym] = fixed
tot = sum(len(v) for v in conf_signals.values())
print(f'确认制信号 {tot} 个')


def filter_signals(rule):
    """rule(sym, date, d) -> bool (买点是否保留)"""
    out = {}
    for sym, sigs in conf_signals.items():
        d = ind[sym]
        keep = []
        for sg in sigs:
            if not sg.signal_type.startswith('buy'):
                keep.append(sg); continue
            if sg.date not in d.index:
                keep.append(sg); continue
            row = d.loc[sg.date]
            if rule(sym, sg.date, row):
                keep.append(sg)
        out[sym] = keep
    return out


def run(label, override):
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = e.run(sd, signals_override=override)[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    print(f'{label:<34} 年化{r.annual_return:+7.2%} 回撤{r.max_drawdown:6.2%} 夏普{r.sharpe_ratio:+5.2f} '
          f'胜率{r.win_rate:5.1%} 盈亏比{r.profit_loss_ratio:5.2f} 买入{len(buys):>3}笔')
    return r


print('\n===== 过滤消融(买点过滤, 卖点不变) =====')
run('V0 基线(确认制, 无过滤)', None)
run('V1 +MACD柱>0', filter_signals(lambda s, dt, r: r['hist'] > 0))
run('V2 +DIF>0(零轴上方)', filter_signals(lambda s, dt, r: r['dif'] > 0))
run('V3 +5日内MACD金叉', filter_signals(lambda s, dt, r: bool(r['gold5'])))
run('V4 +收盘>布林中轨', filter_signals(lambda s, dt, r: r['close'] > r['mid']))
run('V5 +收盘>布林下轨(排除极端超卖)', filter_signals(lambda s, dt, r: r['close'] > r['lo']))
run('V6 +布林下轨回升', filter_signals(lambda s, dt, r: bool(r['lo_up'])))
run('V7 +MACD柱>0 且 >中轨', filter_signals(lambda s, dt, r: (r['hist'] > 0) and (r['close'] > r['mid'])))
run('V8 +MACD柱>0 且 >下轨', filter_signals(lambda s, dt, r: (r['hist'] > 0) and (r['close'] > r['lo'])))
run('V9 +DIF>0 且 >中轨', filter_signals(lambda s, dt, r: (r['dif'] > 0) and (r['close'] > r['mid'])))
