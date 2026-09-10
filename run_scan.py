"""
缠论全市场扫描入口脚本
=======================
使用方法: python run_scan.py [--quick] [--full]
  --quick: 快速模式，只扫描58只核心标的（~2分钟）
  --full: 全市场模式（默认，~30分钟）
"""

import os
import sys
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from chanlun.scanner import MarketScanner
from config import BACKTEST_STOCKS


def parse_args():
    parser = argparse.ArgumentParser(description='缠论全市场扫描器')
    parser.add_argument('--quick', action='store_true', 
                        help='快速模式: 只扫描58只核心标的')
    parser.add_argument('--full', action='store_true',
                        help='全市场模式: 扫描全市场5000+标的（默认）')
    return parser.parse_args()


def run_quick_mode():
    """快速模式: 扫描config中定义的58只核心标的"""
    print("=" * 60)
    print("缠论扫描器 - 快速模式")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"标的: {len(BACKTEST_STOCKS)}只核心标的（33ETF + 25蓝筹）")
    print("=" * 60)
    print()

    scanner = MarketScanner()
    
    start_time = datetime.now()
    results = scanner.scan_batch(BACKTEST_STOCKS)
    elapsed = (datetime.now() - start_time).total_seconds()
    
    # 输出结果
    print(f"\n扫描完成, 耗时 {elapsed:.1f}秒")
    print(scanner.format_results(results))
    
    # 输出统计
    signal_count = sum(len(data['signals']) for data in results.values())
    print(f"\n统计: 扫描{len(BACKTEST_STOCKS)}只, 发现{len(results)}只有信号, 共{signal_count}个信号")


def run_full_mode():
    """全市场模式: 两阶段扫描全市场5000+标的"""
    print("=" * 60)
    print("缠论扫描器 - 全市场模式")
    print(f"时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("预计耗时: 15~30分钟")
    print("=" * 60)
    print()

    scanner = MarketScanner()
    results = scanner.scan_full_market()
    
    # 输出结果
    print()
    print(scanner.format_results(results))


def main():
    args = parse_args()
    
    if args.quick:
        run_quick_mode()
    else:
        # 默认全市场模式
        run_full_mode()


if __name__ == "__main__":
    main()
