# -*- coding: utf-8 -*-
"""V5.3.3 确认制实装回归: 开关关(原口径) vs 开(确认制)"""
import sys, os, io, contextlib, importlib, pickle, time
sys.path.insert(0, 'work')
import pandas as pd

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)
print('数据:', len(stock_data), '只')


def run(label, confirm):
    import config, importlib
    importlib.reload(config)
    config.USE_CONFIRMATION_DELAY = confirm
    import chanlun.backtest as bt
    importlib.reload(bt)
    from chanlun.backtest import BacktestEngine
    e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    t0 = time.time()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = e.run(stock_data)[0]
    out = buf.getvalue()
    conf_line = [l for l in out.split('\n') if '确认制' in l]
    buys = [t for t in r.trades if t.direction == 'buy']
    sells = [t for t in r.trades if t.direction == 'sell' and t.signal_type != '清仓']
    hold = sum(t.hold_days for t in sells) / max(len(sells), 1)
    print(f'[{label}] 年化{r.annual_return:.2%} 回撤{r.max_drawdown:.2%} 夏普{r.sharpe_ratio:.2f} '
          f'胜率{r.win_rate:.2%} 盈亏比{r.profit_loss_ratio:.2f} 买入{len(buys)}笔 '
          f'期末{r.final_capital:,.0f} 持仓{hold:.1f}天 ({time.time()-t0:.0f}s)')
    for l in conf_line:
        print('   ', l.strip())
    return r


print('\n=== 开关关闭(原口径, 对照) ===')
rA = run('A原口径', False)
print('\n=== 开关开启(确认制, 新默认) ===')
rD = run('D确认制', True)
