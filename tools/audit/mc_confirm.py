# -*- coding: utf-8 -*-
"""确认制口径下的蒙特卡洛检验(打乱信号日期)
用法: python mc_confirm.py prepare | python mc_confirm.py run <start> <count>
"""
import sys, os, pickle, json, time
sys.path.insert(0, 'work')
import numpy as np
import config
from chanlun.core import ChanLunAnalyzer
from chanlun.signal import SignalDetector, Signal
from chanlun.backtest import BacktestEngine, resolve_confirmation_dates

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)
PREP = 'data_cache/mc_confirm_prep.pkl'
RES = 'data_cache/mc_confirm_results.json'


def df_to_klines(df):
    from chanlun.core import RawKline
    ks = []
    for i, row in df.iterrows():
        ks.append(RawKline(date=str(row['日期'])[:10], open=float(row['开盘']), high=float(row['最高']),
                           low=float(row['最低']), close=float(row['收盘']),
                           volume=float(row.get('成交量', 0)), index=len(ks)))
    return ks


def prepare():
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    env_map = e.env_map
    sigs = {}
    t0 = time.time()
    for symbol, (name, df) in stock_data.items():
        kl = df_to_klines(df)
        an = ChanLunAnalyzer(); an.analyze(kl)
        raw = SignalDetector(env_map).detect(kl, an)
        fixed, st = resolve_confirmation_dates(kl, an, raw, env_map)
        sigs[symbol] = fixed
    total = sum(len(v) for v in sigs.values())
    print(f'确认制信号构建完成: {total}个, {time.time()-t0:.0f}s', flush=True)
    with open(PREP, 'wb') as f:
        pickle.dump(sigs, f)


def run_chunk(start, count):
    with open(PREP, 'rb') as f:
        base = pickle.load(f)
    res = []
    if os.path.exists(RES):
        res = json.load(open(RES))
    rng = np.random.default_rng(42 + start)
    t0 = time.time()
    for i in range(start, start + count):
        shuffled = {}
        for sym, sgs in base.items():
            if not sgs:
                continue
            dates = list(stock_data[sym][1]['日期'].astype(str).str[:10])
            nd = rng.choice(dates, size=len(sgs), replace=True).tolist()
            nd.sort()
            shuffled[sym] = [Signal(signal_type=s.signal_type, date=d, price=s.price,
                                    description=s.description, pivot=s.pivot, market_env=s.market_env)
                             for s, d in zip(sgs, nd)]
        e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
        e.set_market_env(idx)
        r = e.run(stock_data, signals_override=shuffled)[0]
        res.append({'iter': i, 'annual': r.annual_return, 'dd': r.max_drawdown, 'sharpe': r.sharpe_ratio})
        if (i - start + 1) % 5 == 0:
            print(f'  iter {i} ok ({time.time()-t0:.0f}s)', flush=True)
    json.dump(res, open(RES, 'w'))
    print('saved total', len(res), flush=True)


if __name__ == '__main__':
    if sys.argv[1] == 'prepare':
        prepare()
    else:
        run_chunk(int(sys.argv[2]), int(sys.argv[3]))
