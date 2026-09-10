"""
Walk-Forward样本外验证脚本
===========================
方案A：固定分割
方案B：滚动窗口
"""

import os
import sys
import json
import traceback
from datetime import datetime
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import (
    BACKTEST_STOCKS, BACKTEST_START_DATE, BACKTEST_END_DATE,
    INITIAL_CAPITAL, MARKET_INDEX_SYMBOL, DEFAULT_EXECUTION_MODE,
)
from chanlun.backtest import BacktestEngine, fetch_stock_data
from data_fetcher import fetch_index_data


def run_single_backtest(start_date: str, end_date: str, label: str = "") -> dict:
    """
    运行单个日期区间的回测
    start_date/end_date: 格式 'YYYYMMDD'
    返回: 指标字典
    """
    print(f"\n  [{label}] 回测区间: {start_date} ~ {end_date}")
    
    # 多取前置数据用于均线计算
    from datetime import timedelta
    start_dt = datetime.strptime(start_date, "%Y%m%d")
    pre_start = (start_dt - timedelta(days=200)).strftime("%Y%m%d")
    
    # 获取指数数据
    print(f"    获取指数数据...")
    index_df = fetch_index_data(MARKET_INDEX_SYMBOL, pre_start, end_date)
    if index_df is None:
        print(f"    警告: 指数数据获取失败")
        index_df = None
    
    # 获取股票数据
    print(f"    获取股票数据 ({len(BACKTEST_STOCKS)}只)...")
    stock_data = fetch_stock_data(BACKTEST_STOCKS, pre_start, end_date)
    if not stock_data:
        print(f"    错误: 股票数据获取失败")
        return None
    
    # 过滤数据到指定区间（但保留前置数据用于指标计算）
    # BacktestEngine的run方法会遍历所有日期，需要过滤 equity_curve 到回测区间
    
    # 运行回测（执行模式与主回测一致：DEFAULT_EXECUTION_MODE，见config.py注释）
    print(f"    运行回测 (执行模式: {DEFAULT_EXECUTION_MODE})...")
    engine = BacktestEngine(use_market_env=True, execution_mode=DEFAULT_EXECUTION_MODE)
    if index_df is not None:
        engine.set_market_env(index_df)
    
    results = engine.run(stock_data)
    
    if not results:
        print(f"    错误: 回测无结果")
        return None
    
    r = results[0]
    
    # 统一日期格式处理（equity_curve中的日期可能是YYYY-MM-DD或YYYYMMDD）
    def normalize_date(d):
        return d.replace('-', '')

    # 【V5.3.1修复】同时过滤上/下界，防止把区间外的权益误计入
    equity_in_range = [e for e in r.equity_curve
                       if normalize_date(e['date']) >= start_date
                       and normalize_date(e['date']) <= end_date]
    
    if not equity_in_range:
        print(f"    错误: 目标区间内无权益数据")
        return None
    
    # 重新计算区间内指标
    initial_eq = equity_in_range[0]['equity']
    final_eq = equity_in_range[-1]['equity']
    
    # 区间天数
    d0_str = normalize_date(equity_in_range[0]['date'])
    d1_str = normalize_date(equity_in_range[-1]['date'])
    d0 = datetime.strptime(d0_str, "%Y%m%d")
    d1 = datetime.strptime(d1_str, "%Y%m%d")
    days = (d1 - d0).days
    if days <= 0:
        days = 1
    years = days / 365.25
    
    total_return = (final_eq / initial_eq) - 1 if initial_eq > 0 else 0
    annual_return = (1 + total_return) ** (1 / years) - 1 if years > 0 else 0
    
    # 最大回撤
    eq_vals = [e['equity'] for e in equity_in_range]
    peak = eq_vals[0]
    max_dd = 0
    for v in eq_vals:
        if v > peak:
            peak = v
        dd = (peak - v) / peak if peak > 0 else 0
        if dd > max_dd:
            max_dd = dd
    
    # 夏普比率（年化）
    eq_series = pd.Series(eq_vals)
    daily_returns = eq_series.pct_change().dropna()
    if len(daily_returns) > 1 and daily_returns.std() > 0:
        sharpe = (daily_returns.mean() / daily_returns.std()) * np.sqrt(252)
    else:
        sharpe = 0
    
    # 统计区间内的交易
    # 【V5.3.1修复】剔除期末强制清仓(清仓)，与主回测胜率口径一致；
    # 否则窗口末尾被强制平掉的持仓会被计入胜率/盈亏，污染样本外统计
    trades_in_range = [t for t in r.trades 
                       if t.direction == 'sell' and t.signal_type != '清仓'
                       and normalize_date(t.date) >= start_date and normalize_date(t.date) <= end_date]
    sell_trades = trades_in_range
    win_trades = [t for t in sell_trades if t.pnl > 0]
    win_rate = len(win_trades) / len(sell_trades) if sell_trades else 0
    
    total_pnl = sum(t.pnl for t in sell_trades)
    avg_pnl = total_pnl / len(sell_trades) if sell_trades else 0
    
    result = {
        'label': label,
        'start_date': start_date,
        'end_date': end_date,
        'days': days,
        'years': round(years, 2),
        'initial_equity': round(initial_eq, 2),
        'final_equity': round(final_eq, 2),
        'total_return': round(total_return * 100, 2),
        'annual_return': round(annual_return * 100, 2),
        'max_drawdown': round(max_dd * 100, 2),
        'sharpe_ratio': round(sharpe, 2),
        'trade_count': len(sell_trades),
        'win_count': len(win_trades),
        'win_rate': round(win_rate * 100, 2),
        'total_pnl': round(total_pnl, 2),
        'avg_pnl': round(avg_pnl, 2),
    }
    
    print(f"    结果: 年化{result['annual_return']:.2f}%, "
          f"回撤{result['max_drawdown']:.2f}%, "
          f"夏普{result['sharpe_ratio']:.2f}, "
          f"交易{result['trade_count']}笔, "
          f"胜率{result['win_rate']:.1f}%")
    
    return result


def run_plan_a():
    """方案A：固定分割"""
    print("\n" + "=" * 70)
    print("方案A：固定分割 Walk-Forward验证")
    print("=" * 70)
    
    # 训练集：2016-01-01 ~ 2022-12-31
    train_result = run_single_backtest("20160101", "20221231", "训练集")
    
    # 验证集：2023-01-01 ~ 2026-08-31
    valid_result = run_single_backtest("20230101", "20260831", "验证集")
    
    return {'train': train_result, 'valid': valid_result}


def run_plan_b():
    """方案B：滚动窗口"""
    print("\n" + "=" * 70)
    print("方案B：滚动窗口 Walk-Forward验证")
    print("=" * 70)
    
    windows = [
        ("20160101", "20181231", "20190101", "20191231", "W1:2016-18训练/2019验证"),
        ("20170101", "20191231", "20200101", "20201231", "W2:2017-19训练/2020验证"),
        ("20180101", "20201231", "20210101", "20211231", "W3:2018-20训练/2021验证"),
        ("20190101", "20211231", "20220101", "20221231", "W4:2019-21训练/2022验证"),
        ("20200101", "20221231", "20230101", "20231231", "W5:2020-22训练/2023验证"),
        ("20210101", "20231231", "20240101", "20241231", "W6:2021-23训练/2024验证"),
        ("20220101", "20241231", "20250101", "20260831", "W7:2022-24训练/2025-26验证"),
    ]
    
    results = []
    for train_start, train_end, val_start, val_end, label in windows:
        # 训练集回测（仅用于确定参数，但参数固定不变）
        train_r = run_single_backtest(train_start, train_end, f"{label}(训练)")
        # 验证集回测
        val_r = run_single_backtest(val_start, val_end, f"{label}(验证)")
        
        results.append({
            'label': label,
            'train': train_r,
            'valid': val_r,
        })
    
    return results


def print_plan_a_report(plan_a):
    """打印方案A报告"""
    print("\n" + "=" * 70)
    print("方案A报告：固定分割训练集 vs 验证集")
    print("=" * 70)
    
    train = plan_a.get('train')
    valid = plan_a.get('valid')
    
    if not train or not valid:
        print("数据不完整，无法生成报告")
        return
    
    print(f"\n  {'指标':<16s} {'训练集(2016-2022)':>20s} {'验证集(2023-2026)':>20s} {'衰减比':>10s}")
    print(f"  {'-' * 70}")
    
    # 年化收益
    ar_ratio = valid['annual_return'] / train['annual_return'] if train['annual_return'] > 0 else 0
    print(f"  {'年化收益率(%)':<16s} {train['annual_return']:>20.2f} {valid['annual_return']:>20.2f} {ar_ratio:>10.2%}")
    
    # 最大回撤
    dd_ratio = valid['max_drawdown'] / train['max_drawdown'] if train['max_drawdown'] > 0 else 0
    print(f"  {'最大回撤(%)':<16s} {train['max_drawdown']:>20.2f} {valid['max_drawdown']:>20.2f} {dd_ratio:>10.2%}")
    
    # 夏普
    sp_ratio = valid['sharpe_ratio'] / train['sharpe_ratio'] if train['sharpe_ratio'] > 0 else 0
    print(f"  {'夏普比率':<16s} {train['sharpe_ratio']:>20.2f} {valid['sharpe_ratio']:>20.2f} {sp_ratio:>10.2%}")
    
    # 胜率
    wr_ratio = valid['win_rate'] / train['win_rate'] if train['win_rate'] > 0 else 0
    print(f"  {'胜率(%)':<16s} {train['win_rate']:>20.2f} {valid['win_rate']:>20.2f} {wr_ratio:>10.2%}")
    
    # 交易次数
    print(f"  {'交易次数':<16s} {train['trade_count']:>20d} {valid['trade_count']:>20d}")
    
    # 总收益
    print(f"  {'总收益率(%)':<16s} {train['total_return']:>20.2f} {valid['total_return']:>20.2f}")
    
    print(f"\n  验收标准:")
    print(f"    年化收益比 ≥ 60%:  {ar_ratio:.2%} {'✅ 通过' if ar_ratio >= 0.6 else '❌ 未通过'}")
    print(f"    回撤比 ≤ 150%:     {dd_ratio:.2%} {'✅ 通过' if dd_ratio <= 1.5 else '❌ 未通过'}")


def print_plan_b_report(plan_b):
    """打印方案B报告"""
    print("\n" + "=" * 70)
    print("方案B报告：滚动窗口验证")
    print("=" * 70)
    
    print(f"\n  {'窗口':<30s} {'训练年化%':>10s} {'验证年化%':>10s} {'衰减比':>8s} {'训练回撤%':>10s} {'验证回撤%':>10s}")
    print(f"  {'-' * 85}")
    
    valid_annual_returns = []
    valid_drawdowns = []
    train_annual_returns = []
    train_drawdowns = []
    decay_ratios = []
    invalid_windows = []

    for w in plan_b:
        t = w['train']
        v = w['valid']
        if t and v and v['trade_count'] > 0:
            # 【V5.3.1修复】验证期0笔交易的窗口（如W4:2022熊市无信号）不属于"有效样本外"，
            # 不应计入衰减比统计，否则会人为拉低中位数
            ratio = v['annual_return'] / t['annual_return'] if t['annual_return'] > 0 else 0
            decay_ratios.append(ratio)
            valid_annual_returns.append(v['annual_return'])
            train_annual_returns.append(t['annual_return'])
            valid_drawdowns.append(v['max_drawdown'])
            train_drawdowns.append(t['max_drawdown'])
            print(f"  {w['label']:<30s} {t['annual_return']:>10.2f} {v['annual_return']:>10.2f} {ratio:>8.2%} {t['max_drawdown']:>10.2f} {v['max_drawdown']:>10.2f}")
        else:
            invalid_windows.append(w['label'])
            print(f"  {w['label']:<30s} {'无效(0笔交易或数据缺失)':>30s}")
    
    if valid_annual_returns:
        print(f"\n  汇总统计（仅有效窗口，0笔交易的窗口已剔除）:")
        print(f"    有效窗口数: {len(valid_annual_returns)}/{len(plan_b)}")
        print(f"    验证集年化收益:  均值={np.mean(valid_annual_returns):.2f}%, "
              f"中位数={np.median(valid_annual_returns):.2f}%, "
              f"范围=[{min(valid_annual_returns):.2f}%, {max(valid_annual_returns):.2f}%]")
        print(f"    训练集年化收益:  均值={np.mean(train_annual_returns):.2f}%, "
              f"中位数={np.median(train_annual_returns):.2f}%")
        print(f"    衰减比:          均值={np.mean(decay_ratios):.2%}, "
              f"中位数={np.median(decay_ratios):.2%}")
        print(f"    验证集最大回撤:  均值={np.mean(valid_drawdowns):.2f}%, "
              f"最大={max(valid_drawdowns):.2f}%")
        
        pass_count = sum(1 for r in decay_ratios if r >= 0.6)
        print(f"\n    通过窗口数 (衰减比≥60%): {pass_count}/{len(decay_ratios)}")
    if invalid_windows:
        print(f"\n  已剔除的无效窗口（0笔交易或数据缺失）: {', '.join(invalid_windows)}")


def generate_report(plan_a, plan_b):
    """生成最终报告"""
    report_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 
                               "V5.3_WalkForward验证报告.md")
    
    lines = []
    lines.append("# V5.3 Walk-Forward样本外验证报告")
    lines.append("")
    lines.append(f"生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")
    
    # 方案A
    lines.append("## 一、方案A：固定分割")
    lines.append("")
    lines.append("- **训练集**: 2016-01-01 ~ 2022-12-31 (7年)")
    lines.append("- **验证集**: 2023-01-01 ~ 2026-08-31 (3.5年)")
    lines.append("")
    
    train = plan_a.get('train')
    valid = plan_a.get('valid')
    
    if train and valid:
        lines.append("### 指标对比")
        lines.append("")
        lines.append("| 指标 | 训练集 | 验证集 | 衰减比 | 验收 |")
        lines.append("|------|--------|--------|--------|------|")
        
        ar_ratio = valid['annual_return'] / train['annual_return'] if train['annual_return'] > 0 else 0
        dd_ratio = valid['max_drawdown'] / train['max_drawdown'] if train['max_drawdown'] > 0 else 0
        sp_ratio = valid['sharpe_ratio'] / train['sharpe_ratio'] if train['sharpe_ratio'] > 0 else 0
        
        lines.append(f"| 年化收益率 | {train['annual_return']:.2f}% | {valid['annual_return']:.2f}% | {ar_ratio:.2%} | {'✅' if ar_ratio >= 0.6 else '❌'} |")
        lines.append(f"| 最大回撤 | {train['max_drawdown']:.2f}% | {valid['max_drawdown']:.2f}% | {dd_ratio:.2%} | {'✅' if dd_ratio <= 1.5 else '❌'} |")
        lines.append(f"| 夏普比率 | {train['sharpe_ratio']:.2f} | {valid['sharpe_ratio']:.2f} | {sp_ratio:.2%} | - |")
        lines.append(f"| 胜率 | {train['win_rate']:.1f}% | {valid['win_rate']:.1f}% | - | - |")
        lines.append(f"| 交易次数 | {train['trade_count']} | {valid['trade_count']} | - | - |")
        lines.append(f"| 总收益率 | {train['total_return']:.2f}% | {valid['total_return']:.2f}% | - | - |")
    
    # 方案B
    lines.append("")
    lines.append("## 二、方案B：滚动窗口")
    lines.append("")
    lines.append("| 窗口 | 训练年化% | 验证年化% | 衰减比 | 训练回撤% | 验证回撤% |")
    lines.append("|------|-----------|-----------|--------|-----------|-----------|")
    
    decay_ratios = []
    valid_annual = []
    train_annual = []
    valid_dd = []
    
    for w in plan_b:
        t = w['train']
        v = w['valid']
        if t and v and v['trade_count'] > 0:
            ratio = v['annual_return'] / t['annual_return'] if t['annual_return'] > 0 else 0
            decay_ratios.append(ratio)
            valid_annual.append(v['annual_return'])
            train_annual.append(t['annual_return'])
            valid_dd.append(v['max_drawdown'])
            lines.append(f"| {w['label']} | {t['annual_return']:.2f} | {v['annual_return']:.2f} | {ratio:.2%} | {t['max_drawdown']:.2f} | {v['max_drawdown']:.2f} |")
        else:
            lines.append(f"| {w['label']} | 无效(0笔交易) | 无效 | - | - | - |")
    
    if decay_ratios:
        lines.append("")
        lines.append("### 汇总统计（仅有效窗口，0笔交易的窗口已剔除）")
        lines.append("")
        lines.append(f"- 有效窗口数: {len(decay_ratios)}/{len(plan_b)}")
        lines.append(f"- 验证集年化收益均值: {np.mean(valid_annual):.2f}%")
        lines.append(f"- 验证集年化收益中位数: {np.median(valid_annual):.2f}%")
        lines.append(f"- 衰减比均值: {np.mean(decay_ratios):.2%}")
        lines.append(f"- 衰减比中位数: {np.median(decay_ratios):.2%}")
        lines.append(f"- 验证集最大回撤均值: {np.mean(valid_dd):.2f}%")
        pass_count = sum(1 for r in decay_ratios if r >= 0.6)
        lines.append(f"- 通过窗口数(衰减≥60%): {pass_count}/{len(decay_ratios)}")
    else:
        lines.append("")
        lines.append("### 汇总统计")
        lines.append("")
        lines.append("- 无有效窗口（所有窗口验证期0笔交易或数据缺失）")
    
    # 结论
    lines.append("")
    lines.append("## 三、结论")
    lines.append("")
    
    if train and valid:
        ar_ratio = valid['annual_return'] / train['annual_return'] if train['annual_return'] > 0 else 0
        dd_ratio = valid['max_drawdown'] / train['max_drawdown'] if train['max_drawdown'] > 0 else 0
        plan_a_pass = ar_ratio >= 0.6 and dd_ratio <= 1.5
        
        plan_b_pass = False
        if decay_ratios:
            plan_b_pass = np.median(decay_ratios) >= 0.6
        
        if plan_a_pass and plan_b_pass:
            lines.append("### ✅ 策略**未过拟合**")
            lines.append("")
            lines.append("Walk-forward样本外验证通过，策略在未见数据上表现稳健：")
            lines.append(f"- 方案A：验证集年化收益为训练集的{ar_ratio:.0%}，回撤为训练集的{dd_ratio:.0%}")
            if decay_ratios:
                lines.append(f"- 方案B：滚动窗口衰减比中位数{np.median(decay_ratios):.0%}")
            lines.append("")
            lines.append("**结论：V5.3策略具有真实的预测能力，不存在严重的过拟合问题。**")
        elif plan_a_pass:
            lines.append("### ⚠️ 策略存在轻微过拟合风险")
            lines.append("")
            lines.append(f"- 方案A通过（衰减比{ar_ratio:.0%}），但方案B显示部分窗口衰减较大")
            lines.append("")
            lines.append("**建议：关注后续模拟盘表现，必要时降低参数复杂度。**")
        else:
            lines.append("### ❌ 策略存在过拟合")
            lines.append("")
            lines.append(f"- 方案A验证集年化仅为训练集的{ar_ratio:.0%}")
            lines.append("")
            lines.append("**建议：需要简化策略参数或增加训练数据。**")
    
    lines.append("")
    lines.append("---")
    lines.append("*报告自动生成 by Walk-Forward验证脚本*")
    
    report_content = "\n".join(lines)
    
    with open(report_path, 'w', encoding='utf-8') as f:
        f.write(report_content)
    
    print(f"\n报告已保存: {report_path}")
    return report_path


def main():
    print("=" * 70)
    print("V5.3 Walk-Forward样本外验证")
    print(f"运行时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    
    # 方案A
    plan_a = run_plan_a()
    
    # 方案B
    plan_b = run_plan_b()
    
    # 打印报告
    print_plan_a_report(plan_a)
    print_plan_b_report(plan_b)
    
    # 保存报告
    generate_report(plan_a, plan_b)
    
    # 保存原始数据
    data_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "walkforward_results.json")
    with open(data_path, 'w', encoding='utf-8') as f:
        json.dump({'plan_a': plan_a, 'plan_b': plan_b}, f, ensure_ascii=False, indent=2)
    print(f"原始数据已保存: {data_path}")
    
    print("\n验证完成！")


if __name__ == "__main__":
    main()
