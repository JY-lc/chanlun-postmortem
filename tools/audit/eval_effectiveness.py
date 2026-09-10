# -*- coding: utf-8 -*-
"""确认制口径下的策略有效性评估: 总指标/分年度/分标的/基准对比/风险"""
import sys, os, pickle
sys.path.insert(0, 'work')
import numpy as np
import pandas as pd
import config
from chanlun.backtest import BacktestEngine

with open('data_cache/stock_data.pkl', 'rb') as f:
    stock_data = pickle.load(f)
with open('data_cache/index.pkl', 'rb') as f:
    idx = pickle.load(f)

# ===== 确认制口径（默认） =====
e = BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
e.set_market_env(idx)
r = e.run(stock_data)[0]

eq = pd.DataFrame(r.equity_curve)
eq['date'] = pd.to_datetime(eq['date'])
eq = eq.set_index('date')
print('===== 1) 总指标(确认制口径) =====')
print(f'年化 {r.annual_return:.2%} | 最大回撤 {r.max_drawdown:.2%} | 夏普 {r.sharpe_ratio:.2f} | '
      f'胜率 {r.win_rate:.2%} | 盈亏比 {r.profit_loss_ratio:.2f} | 期末 {r.final_capital:,.0f}')

# 风险指标
rets = eq['equity'].pct_change().dropna()
ann_vol = rets.std() * np.sqrt(252)
calmar = r.annual_return / r.max_drawdown if r.max_drawdown > 0 else np.nan
print(f'年化波动 {ann_vol:.2%} | Calmar {calmar:.2f} | 日胜率 {(rets>0).mean():.1%}')
# 月度胜率
m = eq['equity'].resample('ME').last().pct_change().dropna()
print(f'月度胜率 {(m>0).mean():.1%} (共{len(m)}个月)')

# ===== 2) 分年度 =====
print('\n===== 2) 分年度收益 =====')
yr = eq['equity'].resample('YE').last()
first_year_start = eq['equity'].iloc[0]
rows = []
prev = first_year_start
for d, v in yr.items():
    y_ret = v / prev - 1
    rows.append((d.year, y_ret))
    prev = v
for y, rr in rows:
    print(f'  {y}: {rr:+.2%}')

# 基准: 沪深300同期
idx2 = idx.copy()
idx2['日期'] = pd.to_datetime(idx2['日期'])
idx2 = idx2.set_index('日期')['收盘']
idx_y = idx2.resample('YE').last()
idx_ret_tot = idx2.iloc[-1] / idx2.iloc[0] - 1
years = (idx2.index[-1] - idx2.index[0]).days / 365.25
idx_ann = (1 + idx_ret_tot) ** (1 / years) - 1
print(f'\n===== 3) 基准对比 =====')
print(f'  沪深300买入持有: 总收益{idx_ret_tot:+.1%} 年化{idx_ann:+.2%}')
print(f'  策略(确认制): 总收益{r.total_return:+.1%} 年化{r.annual_return:+.2%}')
print(f'  无风险利率(参考): ~2.0%')
print(f'  → 超额收益(vs沪深300): {r.annual_return - idx_ann:+.2%}')

# ===== 4) 分标的 =====
trades = r.trades
sells = [t for t in trades if t.direction == 'sell' and t.signal_type != '清仓']
from collections import defaultdict
pnl_by = defaultdict(float); cnt = defaultdict(int); win = defaultdict(int)
for t in sells:
    pnl_by[t.symbol] += t.pnl; cnt[t.symbol] += 1
    if t.pnl > 0: win[t.symbol] += 1
pos = sum(1 for v in pnl_by.values() if v > 0)
neg = sum(1 for v in pnl_by.values() if v <= 0)
print(f'\n===== 4) 分标的(共{len(pnl_by)}只有交易) =====')
print(f'  正贡献 {pos}只 / 负贡献 {neg}只')
top = sorted(pnl_by.items(), key=lambda x: -x[1])[:5]
bot = sorted(pnl_by.items(), key=lambda x: x[1])[:5]
print('  盈利前5:', [(k, round(v)) for k, v in top])
print('  亏损前5:', [(k, round(v)) for k, v in bot])

# ===== 5) 交易结构 =====
print(f'\n===== 5) 交易结构 =====')
print(f'  买入{len([t for t in trades if t.direction=="buy"])}笔 / 卖出(不含清仓){len(sells)}笔')
reasons = defaultdict(int)
for t in sells: reasons[t.signal_type] += 1
print('  卖出原因:', dict(reasons))

# 落盘
rows_df = pd.DataFrame(rows, columns=['year', 'ret'])
rows_df.to_csv('data_cache/confirm_by_year.csv', index=False)
pd.DataFrame([(k, round(v, 2), cnt[k], win[k]) for k, v in pnl_by.items()],
             columns=['symbol', 'pnl', 'trades', 'wins']).to_csv('data_cache/confirm_by_symbol.csv', index=False)
print('\n已落盘 data_cache/confirm_by_year.csv, confirm_by_symbol.csv')
