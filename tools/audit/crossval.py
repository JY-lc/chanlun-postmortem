# -*- coding: utf-8 -*-
"""
交叉验证: 逐日截断重跑(方案1的定义) vs 推导口径
验证: 截断视图下信号首次出现的日期, 是否 = 分型确认日(推导B), 以及 < 定型日(推导C)
"""
import sys, os, time, pickle
sys.path.insert(0, 'work')
import config
from chanlun.core import ChanLunAnalyzer, RawKline
from chanlun.signal import SignalDetector, Signal
from chanlun.backtest import BacktestEngine

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
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


def conf_date(f, merged):
    return merged[f.index + 1].end_date if f.index + 1 < len(merged) else None


def build_fix(fractals, merged):
    from chanlun.signal import Signal as S  # noqa
    if len(fractals) < 2:
        return {}, None
    fixed = {}
    sel = [fractals[0]]
    def _low(a, b):
        return a.low if (a.type == 'bottom' and b.type == 'top') else (b.low if (a.type == 'top' and b.type == 'bottom') else None)
    def _high(a, b):
        return b.high if (a.type == 'bottom' and b.type == 'top') else (a.high if (a.type == 'top' and b.type == 'bottom') else None)
    for i in range(1, len(fractals)):
        cu, la = fractals[i], sel[-1]
        if cu.type == la.type:
            if cu.type == 'top':
                if cu.high > la.high: sel[-1] = cu
            else:
                if cu.low < la.low: sel[-1] = cu
            continue
        if abs(cu.index - la.index) < 3:
            continue
        ok = False
        if la.type == 'bottom' and cu.type == 'top':
            if cu.high > la.high:
                if len(sel) >= 2 and cu.high <= _low(sel[-2], sel[-1]): continue
                ok = True
        elif la.type == 'top' and cu.type == 'bottom':
            if cu.low < la.low:
                if len(sel) >= 2 and cu.low >= _high(sel[-2], sel[-1]): continue
                ok = True
        if ok:
            fixed[(la.index, la.type, la.date)] = conf_date(cu, merged)
            sel.append(cu)
    return fixed, (sel[-1].index, sel[-1].type, sel[-1].date)


CHECK = ['000001', '000858', '601318']
N_SIG = 6
for symbol in CHECK:
    df = stock_data[symbol][1]
    klines = df_to_klines(df)
    dmap = {k.date: i for i, k in enumerate(klines)}
    an = ChanLunAnalyzer(); an.analyze(klines)
    full = SignalDetector(env_map).detect(klines, an)
    conf_map = {}
    for st in an.strokes:
        for f in (st.start, st.end):
            cd = conf_date(f, an.merged_klines)
            k = (f.index, f.type, f.date)
            if k not in conf_map or (cd and (conf_map[k] is None or cd < conf_map[k])):
                conf_map[k] = cd
    fixed, lastk = build_fix(an.fractals, an.merged_klines)
    print(f'--- {symbol} {stock_data[symbol][0]} 最近{N_SIG}个信号 (共{len(full)}) ---')
    for sg in full[-N_SIG:]:
        key = None
        for st in an.strokes:
            if st.end.date == sg.date: key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date: key = (st.start.index, st.start.type, st.start.date); break
        dB = conf_map.get(key)
        dC = fixed.get(key)
        d0 = dmap[sg.date]
        first = None
        for j in range(d0 + 1, min(d0 + 41, len(klines))):
            a2 = ChanLunAnalyzer(); a2.analyze(klines[:j])
            s2 = SignalDetector(env_map).detect(klines[:j], a2)
            if any(s.signal_type == sg.signal_type and s.date == sg.date for s in s2):
                first = klines[j - 1].date
                break
        tag = ''
        if first and dB and first == dB: tag = '<= 与推导B一致'
        elif first and dB and first < dB: tag = '<= 比推导B更早!'
        print(f'  {sg.signal_type:6} date={sg.date} | 推导B={dB} 推导C={dC} | 截断首见={first} {tag}')
        time.sleep(0)
print('\n完成')
