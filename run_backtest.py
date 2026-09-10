"""
缠论策略回测入口脚本（V2优化版）
=================================
支持：
1. V1版回测（无市场环境判断，原策略基准）
2. V2版回测（有市场环境判断+策略适配）
3. 对比实验：V1 vs V2
4. 分环境统计
"""

import os
import sys
from datetime import datetime
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    BACKTEST_STOCKS, BACKTEST_STOCKS_V1, BACKTEST_START_DATE, BACKTEST_END_DATE,
    INITIAL_CAPITAL, MARKET_INDEX_SYMBOL, MARKET_INDEX_NAME,
    BACKTEST_ETFS, BACKTEST_STOCKS_V2, INDEX_PRE_START_DAYS,
    DEFAULT_EXECUTION_MODE,
)
from chanlun.backtest import BacktestEngine, fetch_stock_data
from data_fetcher import fetch_index_data


def print_divider(char='=', width=70):
    print(char * width)


def print_result_summary(r, label=""):
    """打印单个回测结果摘要"""
    print(f"\n  {label}")
    print(f"  初始资金:       {r.initial_capital:>12,.2f} 元")
    print(f"  最终资金:       {r.final_capital:>12,.2f} 元")
    print(f"  总收益率:       {r.total_return:>11.2%}")
    print(f"  年化收益率:     {r.annual_return:>11.2%}")
    print(f"  最大回撤:       {r.max_drawdown:>11.2%}")
    print(f"  夏普比率:       {r.sharpe_ratio:>11.2f}")
    print(f"  胜率:           {r.win_rate:>11.2%}")
    print(f"  盈亏比:         {r.profit_loss_ratio:>11.2f}")
    print(f"  交易次数(买):   {r.trade_count:>11d}")


def print_env_stats(env_stats):
    """打印分环境统计"""
    print(f"\n  {'环境':<8s} {'交易数':>6s} {'盈利数':>6s} {'胜率':>8s} {'总盈亏':>12s} {'均盈亏':>10s}")
    print(f"  {'-'*60}")
    
    env_labels = {'bull': '上涨市', 'bear': '下跌市', 'sideways': '震荡市'}
    for env_type in ['bull', 'sideways', 'bear']:
        stats = env_stats.get(env_type, {})
        if not stats:
            continue
        label = env_labels.get(env_type, env_type)
        print(f"  {label:<8s} {stats['trade_count']:>6d} {stats['win_count']:>6d} "
              f"{stats['win_rate']:>7.1%} {stats['total_pnl']:>12,.2f} {stats['avg_pnl']:>10,.2f}")
    
    # 按买点类型统计
    print(f"\n  各买点在不同环境下的表现:")
    print(f"  {'买点':<8s} {'上涨市(次/胜/率)':>20s} {'震荡市(次/胜/率)':>20s} {'下跌市(次/胜/率)':>20s}")
    print(f"  {'-'*70}")
    
    for bt, bt_name in [('buy1', '一买'), ('buy2', '二买'), ('buy3', '三买')]:
        parts = []
        for env in ['bull', 'sideways', 'bear']:
            stats = env_stats.get(env, {})
            count = stats.get(f'{bt}_count', 0)
            win = stats.get(f'{bt}_win', 0)
            wr = stats.get(f'{bt}_wr', 0)
            parts.append(f"{count:>3d}/{win:>2d}/{wr:>5.0%}")
        print(f"  {bt_name:<8s} {parts[0]:>20s} {parts[1]:>20s} {parts[2]:>20s}")


def print_trade_details(trades, max_show=30):
    """打印交易明细"""
    sell_trades = [t for t in trades if t.direction == 'sell']
    print(f"\n  卖出交易明细（共{len(sell_trades)}笔，显示前{max_show}笔）:")
    print(f"  {'日期':<12s} {'代码':<8s} {'买点':<8s} {'环境':<6s} {'卖价':>8s} {'盈亏':>10s} {'持仓天':>6s} {'原因':<10s}")
    print(f"  {'-'*75}")
    
    for t in sell_trades[:max_show]:
        env_label = {'bull': '上涨', 'bear': '下跌', 'sideways': '震荡'}.get(t.market_env, '?')
        print(f"  {t.date:<12s} {t.symbol:<8s} {t.signal_type:<8s} {env_label:<6s} "
              f"{t.price:>8.2f} {t.pnl:>10,.2f} {t.hold_days:>6d} {t.signal_type:<10s}")


def run_v1(stock_data):
    """运行V1版回测（无市场环境判断）"""
    print_divider()
    print("实验A: V1版回测（无市场环境判断，原策略基准）")
    print(f"执行模式: {DEFAULT_EXECUTION_MODE}")
    print_divider()
    
    engine = BacktestEngine(use_market_env=False, execution_mode=DEFAULT_EXECUTION_MODE)
    results = engine.run(stock_data)
    return results, engine


def run_v2(stock_data, index_df):
    """运行V2版回测（有市场环境判断+策略适配）"""
    print_divider()
    print("实验B: V2版回测（有市场环境判断 + 策略适配）")
    print(f"执行模式: {DEFAULT_EXECUTION_MODE}")
    print_divider()
    
    engine = BacktestEngine(use_market_env=True, execution_mode=DEFAULT_EXECUTION_MODE)
    engine.set_market_env(index_df)
    results = engine.run(stock_data)
    return results, engine


def main():
    print_divider()
    print("缠论量化策略回测系统 V2 - 市场环境适配优化")
    print(f"回测区间: {BACKTEST_START_DATE} ~ {BACKTEST_END_DATE}")
    print(f"初始资金: {INITIAL_CAPITAL}元")
    print(f"大盘指数: {MARKET_INDEX_NAME}({MARKET_INDEX_SYMBOL})")
    print(f"V1标的: {len(BACKTEST_STOCKS_V1)}只 ({', '.join(f'{v}' for k, v in BACKTEST_STOCKS_V1.items())})")
    print(f"V2标的: {len(BACKTEST_STOCKS)}只 ({len(BACKTEST_ETFS)}只ETF + {len(BACKTEST_STOCKS_V2)}只低价股)")
    print_divider()
    print()

    # ========== 获取数据 ==========
    print("[1/5] 获取大盘指数数据（用于市场环境判定）...")
    # 【V5.3.1修复】指数起始日由回测起始日动态前推，覆盖MA120预热。
    # 原代码硬编码 index_start = "20220601"，导致2016~2022-06 市场环境全部缺省为
    # 震荡市，环境适配机制只对最后4年生效——与文档声称的行为不符，重跑无法复现文档结果。
    from datetime import timedelta as _td
    _bs = datetime.strptime(BACKTEST_START_DATE, "%Y%m%d")
    index_start = (_bs - _td(days=INDEX_PRE_START_DAYS)).strftime("%Y%m%d")
    index_df = fetch_index_data(MARKET_INDEX_SYMBOL, index_start, BACKTEST_END_DATE)
    if index_df is None:
        print("  警告: 无法获取大盘指数数据，V2版将使用默认震荡市")
        index_df = None
    else:
        print(f"  获取成功: {len(index_df)}条 ({index_df['日期'].iloc[0]} ~ {index_df['日期'].iloc[-1]})")
        # 截取到回测区间（但保留前置数据给均线计算）

    print(f"\n[2/5] 获取V1版标的数据（{len(BACKTEST_STOCKS_V1)}只）...")
    v1_data = fetch_stock_data(BACKTEST_STOCKS_V1, BACKTEST_START_DATE, BACKTEST_END_DATE)
    print(f"  成功获取 {len(v1_data)}/{len(BACKTEST_STOCKS_V1)} 只")

    print(f"\n[3/5] 获取V2版标的数据（{len(BACKTEST_STOCKS)}只）...")
    v2_data = fetch_stock_data(BACKTEST_STOCKS, BACKTEST_START_DATE, BACKTEST_END_DATE)
    print(f"  成功获取 {len(v2_data)}/{len(BACKTEST_STOCKS)} 只")

    if not v1_data and not v2_data:
        print("错误: 未获取到任何数据！")
        return

    # ========== 运行V1回测 ==========
    print(f"\n[4/5] 运行V1版回测...")
    v1_results = []
    v1_engine = None
    if v1_data:
        v1_results, v1_engine = run_v1(v1_data)
    else:
        print("  V1数据为空，跳过")

    # ========== 运行V2回测 ==========
    print(f"\n[5/5] 运行V2版回测...")
    v2_results = []
    v2_engine = None
    if v2_data:
        v2_results, v2_engine = run_v2(v2_data, index_df)
    else:
        print("  V2数据为空，跳过")

    # ========== 输出对比报告 ==========
    print_divider()
    print("回测结果对比报告")
    print_divider()

    if v1_results:
        print_result_summary(v1_results[0], "实验A - V1版（原策略）")
        print_trade_details(v1_results[0].trades)

    if v2_results:
        print_result_summary(v2_results[0], "\n实验B - V2版（市场环境适配）")
        print_trade_details(v2_results[0].trades)

    # ========== 核心指标对比 ==========
    if v1_results and v2_results:
        print_divider()
        print("V1 vs V2 核心指标对比")
        print_divider()
        r1 = v1_results[0]
        r2 = v2_results[0]
        
        metrics = [
            ('总收益率', f'{r1.total_return:.2%}', f'{r2.total_return:.2%}', 
             f'{(r2.total_return - r1.total_return):.2%}'),
            ('年化收益率', f'{r1.annual_return:.2%}', f'{r2.annual_return:.2%}',
             f'{(r2.annual_return - r1.annual_return):.2%}'),
            ('最大回撤', f'{r1.max_drawdown:.2%}', f'{r2.max_drawdown:.2%}',
             f'{(r2.max_drawdown - r1.max_drawdown):.2%}'),
            ('夏普比率', f'{r1.sharpe_ratio:.2f}', f'{r2.sharpe_ratio:.2f}',
             f'{(r2.sharpe_ratio - r1.sharpe_ratio):.2f}'),
            ('胜率', f'{r1.win_rate:.2%}', f'{r2.win_rate:.2%}',
             f'{(r2.win_rate - r1.win_rate):.2%}'),
            ('盈亏比', f'{r1.profit_loss_ratio:.2f}', f'{r2.profit_loss_ratio:.2f}', ''),
            ('交易次数', f'{r1.trade_count}', f'{r2.trade_count}', ''),
        ]
        
        print(f"  {'指标':<12s} {'V1版':>12s} {'V2版':>12s} {'差异':>12s}")
        print(f"  {'-'*55}")
        for name, v1_val, v2_val, diff in metrics:
            print(f"  {name:<12s} {v1_val:>12s} {v2_val:>12s} {diff:>12s}")

    # ========== 分环境统计（V2） ==========
    if v2_results and v2_results[0].env_stats:
        print_divider()
        print("V2版 - 分市场环境统计")
        print_divider()
        print_env_stats(v2_results[0].env_stats)

    # ========== 保存结果 ==========
    output_dir = os.path.dirname(os.path.abspath(__file__))
    
    if v2_results and v2_results[0].equity_curve:
        import pandas as pd
        equity_file = os.path.join(output_dir, "equity_curve_v2.csv")
        df = pd.DataFrame(v2_results[0].equity_curve)
        df.to_csv(equity_file, index=False)
        print(f"\nV2权益曲线已保存: {equity_file}")
    
    if v1_results and v1_results[0].equity_curve:
        import pandas as pd
        equity_file = os.path.join(output_dir, "equity_curve_v1.csv")
        df = pd.DataFrame(v1_results[0].equity_curve)
        df.to_csv(equity_file, index=False)
        print(f"V1权益曲线已保存: {equity_file}")

    print(f"\n回测完成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()
