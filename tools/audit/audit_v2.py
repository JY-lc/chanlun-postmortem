# -*- coding: utf-8 -*-
"""
审查v2: 三种口径对比 + 逐日截断交叉验证
口径A: 原口径(signal.date=笔终点日)            -- 含未来函数
口径B: 实战口径(分型确认日=右侧合并K线end_date) -- 分型出现即可行动, 无未来函数
口径C: 严格口径(笔定型日=反向分型被接纳)        -- 笔成立才行动, 无未来函数(上轮已算: 2.11%)
"""
import sys, os, time, pickle, csv
sys.path.insert(0, 'work')
import pandas as pd
import config
from chanlun.core import ChanLunAnalyzer, RawKline
from chanlun.signal import SignalDetector, Signal
from chanlun.backtest import BacktestEngine
def df_to_klines(df):
    ks = []
    for i, row in df.iterrows():
        d = str(row['日期'])[:10]
        ks.append(RawKline(date=d, open=float(row['开盘']), high=float(row['最高']),
                           low=float(row['最低']), close=float(row['收盘']),
                           volume=float(row.get('成交量', 0)), index=len(ks)))
    return ks


def fractal_conf_date(f, merged):
    if f.index + 1 < len(merged):
        return merged[f.index + 1].end_date
    return None


def date_index_map(klines):
    return {k.date: i for i, k in enumerate(klines)}


def _s_low(f1, f2):
    if f1.type == 'bottom' and f2.type == 'top': return f1.low
    if f1.type == 'top' and f2.type == 'bottom': return f2.low
    return None


def _s_high(f1, f2):
    if f1.type == 'bottom' and f2.type == 'top': return f2.high
    if f1.type == 'top' and f2.type == 'bottom': return f1.high
    return None


def build_fix_maps(fractals, merged):
    if len(fractals) < 2:
        return {}, None
    fixed = {}
    selected = [fractals[0]]
    for i in range(1, len(fractals)):
        curr, last = fractals[i], selected[-1]
        if curr.type == last.type:
            if curr.type == 'top':
                if curr.high > last.high: selected[-1] = curr
            else:
                if curr.low < last.low: selected[-1] = curr
            continue
        if abs(curr.index - last.index) < 3:
            continue
        ok = False
        if last.type == 'bottom' and curr.type == 'top':
            if curr.high > last.high:
                if len(selected) >= 2:
                    if curr.high <= _s_low(selected[-2], selected[-1]):
                        continue
                ok = True
        elif last.type == 'top' and curr.type == 'bottom':
            if curr.low < last.low:
                if len(selected) >= 2:
                    if curr.low >= _s_high(selected[-2], selected[-1]):
                        continue
                ok = True
        if ok:
            k = (last.index, last.type, last.date)
            fixed[k] = fractal_conf_date(curr, merged)
            selected.append(curr)
    return fixed, (selected[-1].index, selected[-1].type, selected[-1].date)

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)

engine = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
engine.set_market_env(idx)
env_map = engine.env_map

# 逐只: 计算 分型确认日 映射(所有笔端点分型, 含最后未定型分型)
def build_all_confirm(an):
    """{ (index,type,date): 分型确认日 }  对全部笔端点分型(含最后未定型)"""
    m = {}
    for st in an.strokes:
        for f in (st.start, st.end):
            cd = fractal_conf_date(f, an.merged_klines)
            k = (f.index, f.type, f.date)
            if k not in m or (cd and (m[k] is None or cd < m[k])):
                m[k] = cd
    return m

sigB = {}   # 实战口径(分型确认日)
stats = {'total': 0, 'drop_B': 0}
for symbol, (name, df) in stock_data.items():
    klines = df_to_klines(df)
    dmap = date_index_map(klines)
    an = ChanLunAnalyzer(); an.analyze(klines)
    conf_map = build_all_confirm(an)
    sigs = SignalDetector(env_map).detect(klines, an)
    corr = []
    for sg in sigs:
        stats['total'] += 1
        key = None
        for st in an.strokes:
            if st.end.date == sg.date: key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date: key = (st.start.index, st.start.type, st.start.date); break
        cd = conf_map.get(key) if key else None
        if cd is None:
            stats['drop_B'] += 1
            continue
        corr.append(Signal(signal_type=sg.signal_type, date=cd, price=sg.price,
                           description=sg.description, pivot=sg.pivot,
                           market_env=env_map.get(cd, 'sideways')))
    sigB[symbol] = corr
print(f"[信号统计] 总{stats['total']}, 实战口径丢弃(分型未确认){stats['drop_B']}")

def run(label, override=None):
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    r = e.run(stock_data, signals_override=override)[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    hold = sum(t.hold_days for t in sells) / max(len(sells), 1)
    print(f'[{label}] 年化{r.annual_return:.2%} 回撤{r.max_drawdown:.2%} 夏普{r.sharpe_ratio:.2f} '
          f'胜率{r.win_rate:.2%} 盈亏比{r.profit_loss_ratio:.2f} 买入{len(buys)}笔 期末{r.final_capital:,.0f} 持仓{hold:.1f}天')
    return r

print('\n===== 三口径对比 =====')
rA = run('A原口径(含未来函数)', None)
rB = run('B实战口径(分型确认日)', sigB)

# 保存B的明细
with open('data_cache/trades_B.csv','w',newline='',encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['symbol','direction','date','price','shares','signal_type','pnl','hold_days'])
    for t in rB.trades: w.writerow([t.symbol,t.direction,t.date,t.price,t.shares,t.signal_type,t.pnl,t.hold_days])

# ===== 交叉验证: 逐日截断重跑, 与推导口径对照 =====
print('\n===== 交叉验证(逐日截断重跑 vs 推导) =====')
CHECK_SYMS = ['600519', '000001', '600036']
for symbol in CHECK_SYMS:
    df = stock_data[symbol][1]
    klines = df_to_klines(df)
    an_full = ChanLunAnalyzer(); an_full.analyze(klines)
    full_sigs = SignalDetector(env_map).detect(klines, an_full)
    conf_map = build_all_confirm(an_full)
    fixed_map, last_key = build_fix_maps(an_full.fractals, an_full.merged_klines)
    # 只验证最近 8 个信号
    sample = full_sigs[-8:]
    print(f'--- {symbol} {stock_data[symbol][0]} 最近{len(sample)}个信号 ---')
    for sg in sample:
        key = None
        for st in an_full.strokes:
            if st.end.date == sg.date: key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date: key = (st.start.index, st.start.type, st.start.date); break
        derived_B = conf_map.get(key)
        derived_C = fixed_map.get(key)
        # 逐日截断: 从 signal.date 起, 逐日重跑 analyze+detect, 找该信号首次出现日
        d0 = date_index_map(klines).get(sg.date)
        first_seen = None
        for j in range(d0 + 1, min(d0 + 31, len(klines))):
            an = ChanLunAnalyzer(); an.analyze(klines[:j])
            s2 = SignalDetector(env_map).detect(klines[:j], an)
            if any(s.signal_type == sg.signal_type and s.date == sg.date for s in s2):
                first_seen = klines[j-1].date
                break
        print(f'  {sg.signal_type} signal.date={sg.date} | 推导B(分型确认)={derived_B} 推导C(定型)={derived_C} | 逐日截断首见={first_seen}')
