# -*- coding: utf-8 -*-
"""
C方案实测(v2, 修正B口径构建)
A = 严格确认(引擎默认确认制)
B = 分型确认日口径(不验证, 允许幻影)   <- 修正: 需用分型确认日重新构建
C = B + 后验(在T+1日检测, 失败则T+2开盘无条件卖出)
"""
import sys, os, io, contextlib, pickle
sys.path.insert(0, 'work')
import config
from chanlun.core import ChanLunAnalyzer, RawKline
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


def frac_conf(f, merged):
    return merged[f.index + 1].end_date if f.index + 1 < len(merged) else None


def build_B(an, raw, env_map):
    """B口径: 用分型确认日替换日期, 不做截断验证(允许幻影)"""
    merged, strokes = an.merged_klines, an.strokes
    conf = {}
    for st in strokes:
        for f in (st.start, st.end):
            cd = frac_conf(f, merged)
            k = (f.index, f.type, f.date)
            if k not in conf or (cd and (conf[k] is None or cd < conf[k])):
                conf[k] = cd
    out = []
    for sg in raw:
        key = None
        for st in strokes:
            if st.end.date == sg.date:
                key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date:
                key = (st.start.index, st.start.type, st.start.date); break
        d = conf.get(key) if key else None
        if not d:
            continue
        out.append(Signal(signal_type=sg.signal_type, date=d, price=sg.price,
                          description=sg.description, pivot=sg.pivot,
                          market_env=env_map.get(d, 'sideways')))
    return out


B_all, C_full = {}, {}
n_fail = 0
for sym, (name, df) in sd.items():
    kl = df_to_klines(df)
    didx = {k.date: i for i, k in enumerate(kl)}
    an = ChanLunAnalyzer(); an.analyze(kl)
    raw = SignalDetector(env_map).detect(kl, an)
    Bsigs = build_B(an, raw, env_map)
    B_all[sym] = list(Bsigs)
    keep = []
    for sg in Bsigs:
        if not sg.signal_type.startswith('buy'):
            keep.append(sg); continue
        i = didx.get(sg.date)
        if i is None or i + 1 >= len(kl):
            keep.append(sg); continue
        a2 = ChanLunAnalyzer(); a2.analyze(kl[:i + 2])   # 截至 T+1
        ok = any(s.signal_type == sg.signal_type and s.date == sg.date
                 for s in SignalDetector(env_map).detect(kl[:i + 2], a2))
        keep.append(sg)                                   # 买入(T+1开盘)
        if not ok:                                        # 后验失败 -> 次日撤
            n_fail += 1
            keep.append(Signal(signal_type='sell_post', date=kl[i + 1].date,
                               price=kl[i + 1].close, description='post-fail', pivot=None,
                               market_env=env_map.get(kl[i + 1].date, 'sideways')))
    C_full[sym] = keep
print('后验失败买点数:', n_fail)


def run(label, override):
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = e.run(sd, signals_override=override)[0]
    buys = [t for t in r.trades if t.direction == 'buy']
    print(f'{label:<30} 年化{r.annual_return:+7.2%} 回撤{r.max_drawdown:6.2%} 夏普{r.sharpe_ratio:+5.2f} '
          f'胜率{r.win_rate:5.1%} 盈亏比{r.profit_loss_ratio:5.2f} 买入{len(buys):>3}笔')


print('\n===== 三方案对比 (T+1_open, 含0.1%滑点) =====')
run('A 严格确认(引擎确认制)', None)
run('B 分型确认日(不验证)', B_all)
run('C 先开后验(chan.py)', C_full)
