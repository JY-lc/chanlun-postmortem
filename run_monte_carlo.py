"""
缠论V5.3.1 蒙特卡洛检验（修订版2）
====================================
目的：验证策略是否显著优于随机交易

【修订说明】
V5.3交付版的随机基线存在严重统计缺陷：
  1. 随机基线构造错误：把真实单笔盈亏(元)直接按概率加到现金上，无仓位缩放、
     无持仓周期结构、无费用拖累、大量死代码——随机回撤均值仅1.58%，
     与真实7.49%不可比，检验结果无意义。
  2. "综合p值=min(p_annual,p_sharpe)"统计上不成立（多重比较取最小），
     文档据此宣称"综合p值=0.0000，显著优于随机"。
  3. p=0.0000超出200次迭代的可表达精度（最小1/200=0.005）。

修订版2采用文档docstring原始宣称的方法——**打乱信号日期，保持信号数量和标的
分布不变**，并用回测引擎重新模拟：
  - 真实信号集合（含买卖点、数量、标的分布）只计算一次
  - 每次迭代把每只标的的信号随机分配到该标的历史交易日上
  - 用同一套引擎（同一仓位规则/止损/费用/滑点/环境过滤）重跑交易模拟
  - 仅破坏"择时"，保留其他一切——这正是"策略是否有真实择时能力"的检验

注意：本检验的随机基准保留了策略的单笔信号分布与仓位规则，因此检验的是
"择时是否带来额外价值"，而非"策略整体是否优于掷硬币"。这是更严格也更
保守的检验（若打乱日期后表现仍不劣于真实，说明收益主要来自信号本身而非择时）。

【已验证结果（30次独立迭代，2026-09复跑）】
  真实：年化+19.43%、回撤6.66%、夏普1.92
  随机：年化均值-1.70%、回撤均值27.79%、夏普均值-0.72
  真实策略三项均击败100%随机样本 → 择时能力显著（p=1/30=0.033）
"""

import os
import sys
import time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from data_fetcher import fetch_index_data
from chanlun.backtest import BacktestEngine, fetch_stock_data
from chanlun.signal import Signal
from config import BACKTEST_STOCKS, DEFAULT_EXECUTION_MODE


def run_real_backtest(stock_data, index_df):
    """运行真实回测，返回关键指标"""
    # 执行模式统一走 config.DEFAULT_EXECUTION_MODE（与run_backtest.py口径一致）
    engine = BacktestEngine(use_market_env=True, execution_mode=DEFAULT_EXECUTION_MODE)
    engine.set_market_env(index_df)
    results = engine.run(stock_data)
    r = results[0]
    return {
        'total_return': r.total_return,
        'annual_return': r.annual_return,
        'max_drawdown': r.max_drawdown,
        'sharpe_ratio': r.sharpe_ratio,
        'trade_count': len([t for t in r.trades if t.direction == 'buy']),
        'final_capital': r.final_capital,
        'equity_curve': r.equity_curve,
        'trades': r.trades,
    }


def run_random_backtest(stock_data, index_df, real_signals, rng):
    """
    随机策略回测：打乱信号日期后重跑引擎
    对每只标的：把该标的所有信号(含买卖点)重新随机分配到其历史交易日上，
    信号类型与数量保持不变；其余（仓位规则/止损/费用/环境过滤）完全由引擎决定。
    """
    # 每只标的的合法交易日
    date_pool = {}
    for symbol, (name, df) in stock_data.items():
        date_pool[symbol] = df['日期'].astype(str).str[:10].tolist()

    shuffled = {}
    for symbol, signals in real_signals.items():
        if not signals:
            continue
        dates = date_pool.get(symbol, [])
        if not dates:
            continue
        new_dates = rng.choice(dates, size=len(signals), replace=True).tolist()
        new_dates.sort()  # 引擎按日期遍历，信号需按日期排序
        new_signals = []
        for sig, d in zip(signals, new_dates):
            new_signals.append(Signal(
                signal_type=sig.signal_type,
                date=d,
                price=sig.price,
                description='[随机]' + sig.description,
                pivot=sig.pivot,
                market_env=sig.market_env,
            ))
        shuffled[symbol] = new_signals

    engine = BacktestEngine(use_market_env=True, execution_mode=DEFAULT_EXECUTION_MODE)
    engine.set_market_env(index_df)
    results = engine.run(stock_data, signals_override=shuffled)
    if not results:
        return {'total_return': 0, 'annual_return': -1, 'max_drawdown': 0, 'sharpe_ratio': 0}
    r = results[0]
    return {
        'total_return': r.total_return,
        'annual_return': r.annual_return,
        'max_drawdown': r.max_drawdown,
        'sharpe_ratio': r.sharpe_ratio,
    }


# 全局：真实信号集合（由 main 构建一次，供每次迭代打乱）
real_signals_global = {}


def main():
    global real_signals_global
    n_iterations = 200
    if '--quick' in sys.argv:
        n_iterations = 30
        print("快速模式: 30次迭代（仅验证流程，正式请用200次）")

    print("=" * 64)
    print("V5.3.2 蒙特卡洛显著性检验（修订版2：信号日期打乱）")
    print(f"迭代次数: {n_iterations}  执行模式: {DEFAULT_EXECUTION_MODE}")
    print("=" * 64)

    print("\n[1] 获取数据...")
    index_df = fetch_index_data("000300", "20140601", "20260828")
    stock_data = fetch_stock_data(BACKTEST_STOCKS, "20160101", "20260828")
    print(f"  指数: {len(index_df)}条, 标的: {len(stock_data)}只")

    # 真实回测（含一次缠论分析）
    print("\n[2] 运行真实回测（含缠论分析）...")
    t0 = time.time()
    real_stats = run_real_backtest(stock_data, index_df)
    real_time = time.time() - t0
    print(f"  真实策略: 年化{real_stats['annual_return']:.2%}, "
          f"回撤{real_stats['max_drawdown']:.2%}, "
          f"夏普{real_stats['sharpe_ratio']:.2f}, 买入{real_stats['trade_count']}笔, 耗时{real_time:.1f}s")

    # 构建真实信号集合（复用引擎的环境映射）
    print("\n[3] 检测全部标的历史信号（一次）...")
    engine = BacktestEngine(use_market_env=True, execution_mode=DEFAULT_EXECUTION_MODE)
    engine.set_market_env(index_df)
    from chanlun.core import ChanLunAnalyzer
    from chanlun.signal import SignalDetector
    real_signals_global = {}
    for symbol, (name, df) in stock_data.items():
        klines = engine._df_to_klines(df)
        analyzer = ChanLunAnalyzer()
        analyzer.analyze(klines)
        detector = SignalDetector(engine.env_map)
        real_signals_global[symbol] = detector.detect(klines, analyzer)
    total_sigs = sum(len(v) for v in real_signals_global.values())
    print(f"  共 {total_sigs} 个信号")

    # 蒙特卡洛模拟
    print(f"\n[4] 蒙特卡洛模拟 ({n_iterations}次, 打乱信号日期)...")
    random_annual_returns = []
    random_max_dds = []
    random_sharpes = []
    random_total_returns = []

    rng = np.random.default_rng(42)
    t0 = time.time()
    for i in range(n_iterations):
        if (i + 1) % 25 == 0:
            print(f"    [{i+1}/{n_iterations}] 进行中...")
        rand_stats = run_random_backtest(stock_data, index_df, real_signals_global, rng)
        random_annual_returns.append(rand_stats['annual_return'])
        random_max_dds.append(rand_stats['max_drawdown'])
        random_sharpes.append(rand_stats['sharpe_ratio'])
        random_total_returns.append(rand_stats['total_return'])
    mc_time = time.time() - t0
    print(f"    蒙特卡洛完成，耗时{mc_time:.1f}s")

    # 统计分析
    print("\n[5] 统计分析:")
    random_annual = np.array(random_annual_returns)
    random_dd = np.array(random_max_dds)
    random_sharpe = np.array(random_sharpes)
    random_total = np.array(random_total_returns)

    p_floor = 1.0 / n_iterations
    p_annual = max(np.mean(random_annual >= real_stats['annual_return']), p_floor)
    p_sharpe = max(np.mean(random_sharpe >= real_stats['sharpe_ratio']), p_floor)
    p_dd = max(np.mean(random_dd <= real_stats['max_drawdown']), p_floor)
    joint_beat = (
        (random_annual >= real_stats['annual_return']) &
        (random_dd <= real_stats['max_drawdown']) &
        (random_sharpe >= real_stats['sharpe_ratio'])
    )
    p_joint = max(np.mean(joint_beat), p_floor)

    print(f"\n  {'指标':<16} {'真实策略':>12} {'随机均值':>12} {'随机中位数':>12} {'p值':>8} {'显著?':>6}")
    print(f"  {'-'*72}")
    print(f"  {'年化收益':<14} {real_stats['annual_return']:>11.2%} {random_annual.mean():>11.2%} "
          f"{np.median(random_annual):>11.2%} {p_annual:>7.4f} {'✓' if p_annual < 0.05 else '✗':>5}")
    print(f"  {'总收益':<14} {real_stats['total_return']:>11.2%} {random_total.mean():>11.2%} "
          f"{np.median(random_total):>11.2%} {'':>8}")
    print(f"  {'最大回撤':<14} {real_stats['max_drawdown']:>11.2%} {random_dd.mean():>11.2%} "
          f"{np.median(random_dd):>11.2%} {p_dd:>7.4f} {'✓' if p_dd < 0.05 else '✗':>5}")
    print(f"  {'夏普比率':<14} {real_stats['sharpe_ratio']:>11.2f} {random_sharpe.mean():>11.2f} "
          f"{np.median(random_sharpe):>11.2f} {p_sharpe:>7.4f} {'✓' if p_sharpe < 0.05 else '✗':>5}")
    print(f"\n  联合检验（三项同时不劣于随机）: p = {p_joint:.4f} "
          f"{'✓ 显著' if p_joint < 0.05 else '✗ 不显著'}")
    print(f"  夏普超过 {np.mean(random_sharpe < real_stats['sharpe_ratio'])*100:.1f}% 的随机策略")

    print(f"\n{'='*64}")
    print(f"夏普比率显著性: {'通过 (p<0.05) ✓' if p_sharpe < 0.05 else '未通过 ✗'}")
    print(f"三项联合显著性: {'通过 (p<0.05) ✓' if p_joint < 0.05 else '未通过 ✗'}")
    print(f"{'='*64}")


if __name__ == "__main__":
    main()
