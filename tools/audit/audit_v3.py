# -*- coding: utf-8 -*-
"""
审查v3: 方案1(逐日确认制)精确近似 -> D口径
- 买点: 逐日截断检测得到真实"首见确认日"; 窗口内检不出 -> 剔除(幻影信号)
- 卖点: 用推导B(分型确认日) -- 与截断结果高度一致(已验证), 为控制耗时不再逐日重跑
"""
import sys, os, time, pickle, csv
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


WINDOW = 20
t0 = time.time()
sigD = {}
n_buy = n_buy_drop = n_buy_ok = 0
lagD = []
for symbol, (name, df) in stock_data.items():
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
    corr = []
    for sg in full:
        key = None
        for st in an.strokes:
            if st.end.date == sg.date: key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date: key = (st.start.index, st.start.type, st.start.date); break
        dB = conf_map.get(key)
        if sg.signal_type.startswith('buy'):
            n_buy += 1
            d0 = dmap[sg.date]
            first = None
            # 短窗口快速验证(最多5天), 未出现再延到WINDOW
            for j in range(d0 + 1, min(d0 + WINDOW + 1, len(klines))):
                a2 = ChanLunAnalyzer(); a2.analyze(klines[:j])
                s2 = SignalDetector(env_map).detect(klines[:j], a2)
                if any(s.signal_type == sg.signal_type and s.date == sg.date for s in s2):
                    first = klines[j - 1].date
                    break
            if first is None:
                n_buy_drop += 1
                continue
            n_buy_ok += 1
            conf = first
            if dB:
                lagD.append(dmap[first] - d0 if first in dmap else None)
        else:
            conf = dB
            if conf is None:
                continue
        corr.append(Signal(signal_type=sg.signal_type, date=conf, price=sg.price,
                           description=sg.description, pivot=sg.pivot,
                           market_env=env_map.get(conf, 'sideways')))
    sigD[symbol] = corr

print(f'[D口径构建] 买点{n_buy}: 截断可确认{n_buy_ok}, 幻影剔除{n_buy_drop} ({n_buy_drop/max(n_buy,1)*100:.1f}%)')
lags = [x for x in lagD if x is not None]
if lags:
    lags.sort()
    print(f'   买点确认滞后(交易日): 中位{lags[len(lags)//2]} 均值{sum(lags)/len(lags):.2f} 最大{max(lags)} '
          f'| 滞后1天占比 {sum(1 for x in lags if x==1)/len(lags)*100:.0f}%')
print(f'   构建耗时 {time.time()-t0:.0f}s')

def run(label, override):
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    r = e.run(stock_data, signals_override=override)[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    hold = sum(t.hold_days for t in sells) / max(len(sells), 1)
    print(f'[{label}] 年化{r.annual_return:.2%} 回撤{r.max_drawdown:.2%} 夏普{r.sharpe_ratio:.2f} '
          f'胜率{r.win_rate:.2%} 盈亏比{r.profit_loss_ratio:.2f} 买入{len(buys)}笔 期末{r.final_capital:,.0f} 持仓{hold:.1f}天')
    return r

print('\n===== 口径D(方案1精确近似) vs 原口径 =====')
rD = run('D方案1逐日确认制', sigD)
print('参考: A原口径 年化16.79%/夏普1.89 ｜ B分型确认 6.83%/0.64 ｜ C笔定型 2.11%/-0.10')
with open('data_cache/trades_D.csv','w',newline='',encoding='utf-8') as f:
    w = csv.writer(f); w.writerow(['symbol','direction','date','price','shares','signal_type','pnl','hold_days'])
    for t in rD.trades: w.writerow([t.symbol,t.direction,t.date,t.price,t.shares,t.signal_type,t.pnl,t.hold_days])
