# -*- coding: utf-8 -*-
"""
审查实验: 确认滞后型未来函数的量化与真实口径回测
================================================
方法(精确、低成本, 零额外analyze):
  1. 全历史analyze -> merged_klines / fractals / strokes
  2. 复刻 _build_strokes 的选择过程, 推导每个笔端点分型的"定型日"
     (分型确认日 = 右侧合并K线end_date; 笔端点定型 = 出现并接纳反向分型之时)
  3. 未定型的笔端点(数据末端) -> 依赖它的信号在实盘不可得 -> 丢弃
  4. 用定型日替代 signal.date, 经 signals_override 重跑回测 -> 真实口径
"""
import sys, os, time, pickle, csv
sys.path.insert(0, 'work')
import pandas as pd
from collections import defaultdict, Counter

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
        d = str(row['日期'])[:10]
        ks.append(RawKline(date=d, open=float(row['开盘']), high=float(row['最高']),
                           low=float(row['最低']), close=float(row['收盘']),
                           volume=float(row.get('成交量', 0)), index=len(ks)))
    return ks


def _s_low(f1, f2):
    if f1.type == 'bottom' and f2.type == 'top':
        return f1.low
    if f1.type == 'top' and f2.type == 'bottom':
        return f2.low
    return None


def _s_high(f1, f2):
    if f1.type == 'bottom' and f2.type == 'top':
        return f2.high
    if f1.type == 'top' and f2.type == 'bottom':
        return f1.high
    return None


def fractal_conf_date(f, merged):
    """分型确认日 = 右侧合并K线的end_date (需f.index+1存在)"""
    if f.index + 1 < len(merged):
        return merged[f.index + 1].end_date
    return None


def build_fix_maps(fractals, merged):
    """复刻 _build_strokes 选择过程, 返回:
       fixed: {(index,type,date): 定型日}  -- 已成为笔端点、且已被反向分型确认的分型
       last_key: 最后一个未定型分型的key
    """
    if len(fractals) < 2:
        return {}, None
    fixed = {}
    selected = [fractals[0]]
    for i in range(1, len(fractals)):
        curr, last = fractals[i], selected[-1]
        if curr.type == last.type:
            if curr.type == 'top':
                if curr.high > last.high:
                    selected[-1] = curr
            else:
                if curr.low < last.low:
                    selected[-1] = curr
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
            # last 定型, 定型日 = curr 的分型确认日
            k = (last.index, last.type, last.date)
            fixed[k] = fractal_conf_date(curr, merged)
            selected.append(curr)
    last_key = (selected[-1].index, selected[-1].type, selected[-1].date)
    return fixed, last_key


def date_index_map(klines):
    return {k.date: i for i, k in enumerate(klines)}


def open_after(klines, dmap, date_str, n=1):
    """date_str 之后第n个交易日的开盘价"""
    if date_str not in dmap:
        return None
    j = dmap[date_str] + n
    if j < len(klines):
        return klines[j].open
    return None


t0 = time.time()
signal_stats = []
fixed_signals = {}
drop_count = 0
total_sig = 0
lag_days = []
price_devs = []

for si, (symbol, (name, df)) in enumerate(stock_data.items()):
    klines = df_to_klines(df)
    dmap = date_index_map(klines)
    an = ChanLunAnalyzer()
    an.analyze(klines)
    fixed, last_key = build_fix_maps(an.fractals, an.merged_klines)
    sigs = SignalDetector(env_map).detect(klines, an)
    corr = []
    for sg in sigs:
        total_sig += 1
        key = None
        # 找 date 匹配的笔端点分型(以 strokes 端点为准)
        for st in an.strokes:
            if st.end.date == sg.date:
                key = (st.end.index, st.end.type, st.end.date)
                break
            if st.start.date == sg.date:
                key = (st.start.index, st.start.type, st.start.date)
                break
        if key is None or key == last_key or key not in fixed:
            drop_count += 1
            continue
        conf = fixed[key]
        if conf is None:
            drop_count += 1
            continue
        # 滞后(交易日)
        orig_buy_day = dmap.get(sg.date)
        conf_buy_day = dmap.get(conf)
        lag = (conf_buy_day - orig_buy_day) if (orig_buy_day is not None and conf_buy_day is not None) else None
        if lag is not None:
            lag_days.append(lag)
        # 价格偏离: (定型日+1开盘 vs 原日期+1开盘) 仅买点
        if sg.signal_type.startswith('buy'):
            p_orig = open_after(klines, dmap, sg.date, 1)
            p_conf = open_after(klines, dmap, conf, 1)
            if p_orig and p_conf and p_orig > 0:
                price_devs.append((p_conf - p_orig) / p_orig * 100)
        corr.append(Signal(signal_type=sg.signal_type, date=conf, price=sg.price,
                           description=sg.description, pivot=sg.pivot,
                           market_env=env_map.get(conf, 'sideways')))
    fixed_signals[symbol] = corr
    signal_stats.append((symbol, len(sigs), len(corr), len(sigs) - len(corr)))

print(f'[信号统计] 全池信号{total_sig}个, 定型可用{total_sig-drop_count}, 丢弃(未定型){drop_count} '
      f'({drop_count/max(total_sig,1)*100:.1f}%)')
if lag_days:
    ls = sorted(lag_days)
    print(f'[确认滞后(交易日)] 中位{ls[len(ls)//2]} 均值{sum(ls)/len(ls):.2f} '
          f'分布:{dict(sorted(Counter(ls).items())[:12])} 最大{max(ls)}')
    print(f'   滞后0天(当日可得): {sum(1 for x in ls if x==0)}/{len(ls)} = {sum(1 for x in ls if x==0)/len(ls)*100:.1f}%')
    print(f'   滞后<=1天: {sum(1 for x in ls if x<=1)/len(ls)*100:.1f}%  <=3天: {sum(1 for x in ls if x<=3)/len(ls)*100:.1f}%')
if price_devs:
    ps = sorted(price_devs)
    print(f'[价格偏离(买点,定型日+1开盘 vs 原日+1开盘)] 中位{ps[len(ps)//2]:+.2f}% 均值{sum(ps)/len(ps):+.2f}% '
          f'P90 {ps[int(len(ps)*0.9)]:+.2f}% 最大{max(ps):+.2f}%  >0占比{sum(1 for x in ps if x>0)/len(ps)*100:.0f}%')

# ===== 回测对比 =====
def run(label, override=None):
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    res = e.run(stock_data, signals_override=override)
    r = res[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    hold = sum(t.hold_days for t in sells) / max(len(sells), 1)
    print(f'[{label}] 年化{r.annual_return:.2%} 回撤{r.max_drawdown:.2%} 夏普{r.sharpe_ratio:.2f} '
          f'胜率{r.win_rate:.2%} 盈亏比{r.profit_loss_ratio:.2f} 买入{len(buys)}笔 期末{r.final_capital:,.0f} '
          f'平均持仓{hold:.1f}天')
    return r

print('\n===== 回测对比(同口径, T+1_open) =====')
print('说明: "修复前"=按signal.date撮合(含未来函数); "修复后"=按笔定型日撮合(实盘可得)')
r_before = run('修复前(原口径)', None)
r_after = run('修复后(定型日口径)', fixed_signals)

# 保存修复后交易明细
with open('data_cache/trades_fixed.csv', 'w', newline='', encoding='utf-8') as f:
    w = csv.writer(f)
    w.writerow(['symbol', 'direction', 'date', 'price', 'shares', 'signal_type', 'pnl', 'hold_days', 'market_env'])
    for t in r_after.trades:
        w.writerow([t.symbol, t.direction, t.date, t.price, t.shares, t.signal_type, t.pnl, t.hold_days, t.market_env])
print('\n耗时 %.0fs' % (time.time() - t0))
