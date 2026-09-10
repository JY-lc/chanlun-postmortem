# -*- coding: utf-8 -*-
"""
实验: 移植 czsc 的"未完成笔长度限制"到本项目确认制框架
====================================================
czsc 源码: if c.bars_ubi.len() > 7 { return "其他" }  # 未完成笔过长则不判断
本实验: 在确认制信号上, 计算"信号日时当前笔已走交易日数", 超过阈值则跳过该信号
变体: N = 5 / 7 / 10 / 15 / 20 / 不过滤(基线)
"""
import sys, os, io, contextlib, pickle
sys.path.insert(0, 'work')
import numpy as np
import pandas as pd
import config
from chanlun.core import ChanLunAnalyzer, RawKline
from chanlun.signal import SignalDetector
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


print('构建确认制信号 + 笔长度信息...')
signals_by_sym = {}
bilen_by_sym = {}          # {sym: {signal_key: 当前笔长度}}
for sym, (name, df) in sd.items():
    kl = df_to_klines(df)
    didx = {k.date: i for i, k in enumerate(kl)}
    an = ChanLunAnalyzer(); an.analyze(kl)
    raw = SignalDetector(env_map).detect(kl, an)
    fixed, _ = resolve_confirmation_dates(kl, an, raw, env_map)
    strokes = an.strokes
    lens = {}
    for sg in fixed:
        d = sg.date
        if d not in didx:
            lens[id(sg)] = None; continue
        # 信号日时"当前笔"= 起点日期 <= 信号日的最后一笔
        cur = None
        for st in reversed(strokes):
            if st.start.date <= d:
                s_i = didx.get(st.start.date)
                if s_i is not None:
                    cur = didx[d] - s_i
                break
        lens[id(sg)] = cur
    signals_by_sym[sym] = fixed
    bilen_by_sym[sym] = lens
print('信号总数:', sum(len(v) for v in signals_by_sym.values()))


def filt(N):
    """N=None 不过滤; 否则保留 当前笔长度<=N 的信号(无法计算长度的也跳过, 对应czsc的'其他')"""
    out = {}
    for sym, sigs in signals_by_sym.items():
        keep = []
        for sg in sigs:
            if not sg.signal_type.startswith('buy'):
                keep.append(sg); continue
            L = bilen_by_sym[sym].get(id(sg))
            if N is None or (L is not None and L <= N):
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
    print(f'{label:<30} 年化{r.annual_return:+7.2%} 回撤{r.max_drawdown:6.2%} 夏普{r.sharpe_ratio:+5.2f} '
          f'胜率{r.win_rate:5.1%} 盈亏比{r.profit_loss_ratio:5.2f} 买入{len(buys):>3}笔')


print('\n===== 未完成笔长度过滤 (czsc路线) =====')
for N in [None, 20, 15, 10, 7, 5]:
    run(f'笔长≤{N} (None=基线)', filt(N))
