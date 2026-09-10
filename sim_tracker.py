"""
缠论策略V5.3 - 模拟盘跟踪系统
================================
功能：
1. 每日扫描信号并记录到模拟盘日志
2. 跟踪信号后续表现（T+1/T+3/T+5/T+10/T+20 实际成交价）
3. 统计滑点（信号价 vs 次日开盘价 vs 实际成交）
4. 1个月模拟盘对比报告

启动方式：
    # 每日运行（扫描+记录）
    python sim_tracker.py --daily

    # 生成跟踪报告
    python sim_tracker.py --report

    # 模拟盘从指定日期开始
    python sim_tracker.py --start 2026-09-01
"""

import os
import sys
import json
import csv
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from collections import defaultdict

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 模拟盘数据目录
SIM_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sim_data")
SIM_SIGNALS_FILE = os.path.join(SIM_DATA_DIR, "signals.json")
SIM_TRACKING_FILE = os.path.join(SIM_DATA_DIR, "tracking.csv")
SIM_REPORT_FILE = os.path.join(SIM_DATA_DIR, "report.md")


def ensure_sim_dir():
    """确保模拟盘数据目录存在"""
    os.makedirs(SIM_DATA_DIR, exist_ok=True)


def load_signals() -> List[dict]:
    """加载已记录的信号"""
    if not os.path.exists(SIM_SIGNALS_FILE):
        return []
    with open(SIM_SIGNALS_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_signals(signals: List[dict]):
    """保存信号记录"""
    ensure_sim_dir()
    with open(SIM_SIGNALS_FILE, 'w', encoding='utf-8') as f:
        json.dump(signals, f, ensure_ascii=False, indent=2)


def load_tracking() -> pd.DataFrame:
    """加载跟踪数据"""
    if not os.path.exists(SIM_TRACKING_FILE):
        return pd.DataFrame(columns=[
            'signal_id', 'symbol', 'name', 'signal_type', 'signal_date',
            'signal_price', 'close_price',
            'open_t1', 'close_t1', 'high_t1', 'low_t1',
            'open_t3', 'close_t3', 'high_t3', 'low_t3',
            'open_t5', 'close_t5',
            'open_t10', 'close_t10',
            'open_t20', 'close_t20',
            'status', 'actual_entry', 'actual_exit', 'actual_pnl',
            'slippage_pct',
        ])
    return pd.read_csv(SIM_TRACKING_FILE)


def save_tracking(df: pd.DataFrame):
    """保存跟踪数据"""
    ensure_sim_dir()
    df.to_csv(SIM_TRACKING_FILE, index=False)


def scan_and_record(start_date: str = None):
    """
    扫描当日信号并记录到模拟盘
    【V5.3.1修复】
    1. 标的池改为 config.BACKTEST_STOCKS（原硬编码20只子集，与回测58只不一致，
       无法"确认模拟盘信号与回测系统一致"）
    2. 增加市场环境过滤：回测中买卖点按环境参数表过滤（如震荡市禁三买、下跌市禁二三买），
       原扫描器不传环境，会把回测中不会成交的信号也报出来
    """
    from chanlun.scanner import MarketScanner
    from data_fetcher import fetch_stock_hist, fetch_index_data
    from chanlun.market_env import MarketEnvClassifier
    from config import (
        BACKTEST_STOCKS, MARKET_INDEX_SYMBOL, MARKET_INDEX_NAME,
        BACKTEST_END_DATE,
    )

    scanner = MarketScanner()
    today = datetime.now().strftime('%Y-%m-%d')

    print(f"\n[{today}] 模拟盘信号扫描")
    print("=" * 60)

    # 获取大盘指数并判定市场环境（与回测同一套分类器）
    env_map = {}
    try:
        from datetime import timedelta as _td
        idx_start = (datetime.now() - _td(days=400)).strftime('%Y%m%d')
        index_df = fetch_index_data(MARKET_INDEX_SYMBOL, idx_start, datetime.now().strftime('%Y%m%d'))
        if index_df is not None and len(index_df) > 120:
            classifier = MarketEnvClassifier()
            env_map = classifier.classify(index_df)
            from collections import Counter
            cnt = Counter(env_map.values())
            print(f"  市场环境({MARKET_INDEX_NAME}): "
                  f"上涨{cnt.get('bull', 0)}天 震荡{cnt.get('sideways', 0)}天 下跌{cnt.get('bear', 0)}天")
        else:
            print(f"  警告: 指数数据不足，无法判定环境，扫描不启用环境过滤")
    except Exception as e:
        print(f"  警告: 环境判定失败({e})，扫描不启用环境过滤")

    # 核心标的池：与回测58只全池一致
    sim_pool = BACKTEST_STOCKS

    # 扫描每只标的
    new_signals = []
    for symbol, name in sim_pool.items():
        print(f"  扫描 {symbol} {name}...", end=" ")
        signals = scanner.scan_stock(symbol, name, env_map=env_map)
        if signals:
            for sig in signals:
                record = {
                    'signal_id': f"{symbol}_{sig.date}_{sig.signal_type}",
                    'symbol': symbol,
                    'name': name,
                    'signal_type': sig.signal_type,
                    'signal_date': sig.date,
                    'signal_price': sig.price,
                    'market_env': getattr(sig, 'market_env', ''),
                    'record_time': today,
                }
                new_signals.append(record)
                print(f"发现{sig.signal_type}信号 @ {sig.price:.2f}({record['market_env']})")
            time.sleep(0.3)
        else:
            print("无信号")
        time.sleep(0.5)

    # 保存信号
    existing = load_signals()
    existing_ids = {s['signal_id'] for s in existing}
    for s in new_signals:
        if s['signal_id'] not in existing_ids:
            existing.append(s)

    save_signals(existing)
    print(f"\n  本次新增: {len(new_signals)}个信号, 累计: {len(existing)}个")
    return new_signals


def update_tracking():
    """
    更新跟踪数据：检查已记录信号在后续交易日的表现
    """
    from data_fetcher import fetch_stock_hist

    signals = load_signals()
    tracking = load_tracking()
    tracked_ids = set(tracking['signal_id'].tolist()) if len(tracking) > 0 else set()

    today = datetime.now()
    new_rows = []

    for sig in signals:
        signal_id = sig['signal_id']
        symbol = sig['symbol']
        signal_date = sig['signal_date']
        signal_price = sig['signal_price']

        # 获取信号后20个交易日的数据
        try:
            sd = datetime.strptime(signal_date[:10], '%Y-%m-%d')
            ed = today
            start_str = sd.strftime('%Y%m%d')
            end_str = ed.strftime('%Y%m%d')

            df = fetch_stock_hist(symbol, start_str, end_str)
            if df is None or len(df) < 2:
                continue

            # 找到信号日的索引
            dates = df['日期'].tolist()
            signal_date_str = signal_date[:10]
            if signal_date_str not in dates:
                continue
            sig_idx = dates.index(signal_date_str)
            if sig_idx >= len(df) - 1:
                continue  # 信号日就是最后一日，无法跟踪

            row = {
                'signal_id': signal_id,
                'symbol': symbol,
                'name': sig['name'],
                'signal_type': sig['signal_type'],
                'signal_date': signal_date,
                'signal_price': signal_price,
                'close_price': df.iloc[sig_idx]['收盘'],
            }

            # T+1
            if sig_idx + 1 < len(df):
                row['open_t1'] = df.iloc[sig_idx + 1]['开盘']
                row['close_t1'] = df.iloc[sig_idx + 1]['收盘']
                row['high_t1'] = df.iloc[sig_idx + 1]['最高']
                row['low_t1'] = df.iloc[sig_idx + 1]['最低']

            # T+3
            if sig_idx + 3 < len(df):
                row['open_t3'] = df.iloc[sig_idx + 3]['开盘']
                row['close_t3'] = df.iloc[sig_idx + 3]['收盘']
                row['high_t3'] = df.iloc[sig_idx + 3]['最高']
                row['low_t3'] = df.iloc[sig_idx + 3]['最低']

            # T+5
            if sig_idx + 5 < len(df):
                row['open_t5'] = df.iloc[sig_idx + 5]['开盘']
                row['close_t5'] = df.iloc[sig_idx + 5]['收盘']

            # T+10
            if sig_idx + 10 < len(df):
                row['open_t10'] = df.iloc[sig_idx + 10]['开盘']
                row['close_t10'] = df.iloc[sig_idx + 10]['收盘']

            # T+20
            if sig_idx + 20 < len(df):
                row['open_t20'] = df.iloc[sig_idx + 20]['开盘']
                row['close_t20'] = df.iloc[sig_idx + 20]['收盘']
                row['status'] = 'completed'
            else:
                row['status'] = 'tracking'

            # 滑点计算：信号价 vs 次日开盘价
            if 'open_t1' in row and row['open_t1'] and signal_price > 0:
                row['slippage_pct'] = round(
                    (row['open_t1'] - signal_price) / signal_price * 100, 4
                )

            # 模拟盈亏：次日开盘买入 -> T+5卖出
            if 'open_t1' in row and 'close_t5' in row:
                row['actual_entry'] = row['open_t1']
                row['actual_exit'] = row['close_t5']
                if row['actual_entry'] and row['actual_entry'] > 0:
                    row['actual_pnl'] = round(
                        (row['actual_exit'] - row['actual_entry']) / row['actual_entry'] * 100, 2
                    )

            new_rows.append(row)

            time.sleep(0.3)
        except Exception as e:
            print(f"  跟踪 {signal_id} 失败: {e}")
            continue

    # 合并到跟踪表
    if new_rows:
        new_df = pd.DataFrame(new_rows)
        if len(tracking) > 0:
            # 更新已有行
            for _, row in new_df.iterrows():
                mask = tracking['signal_id'] == row['signal_id']
                if mask.any():
                    for col in new_df.columns:
                        if pd.notna(row.get(col)):
                            tracking.loc[mask, col] = row[col]
                else:
                    tracking = pd.concat([tracking, pd.DataFrame([row])], ignore_index=True)
        else:
            tracking = new_df

    save_tracking(tracking)
    print(f"  跟踪更新完成: {len(tracking)}条记录")
    return tracking


def generate_report() -> str:
    """生成模拟盘跟踪报告"""
    tracking = load_tracking()
    signals = load_signals()

    if len(tracking) == 0:
        return "暂无跟踪数据"

    report_lines = []
    report_lines.append("# 缠论V5.3 模拟盘跟踪报告")
    report_lines.append(f"\n生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report_lines.append(f"信号总数：{len(signals)}")
    report_lines.append(f"已跟踪：{len(tracking)}条")

    # 滑点统计
    completed = tracking[tracking['status'] == 'completed'] if 'status' in tracking.columns else tracking
    if 'slippage_pct' in completed.columns:
        slippage_data = completed['slippage_pct'].dropna()
        if len(slippage_data) > 0:
            report_lines.append(f"\n## 滑点统计")
            report_lines.append(f"| 指标 | 值 |")
            report_lines.append(f"|------|-----|")
            report_lines.append(f"| 平均滑点 | {slippage_data.mean():.4f}% |")
            report_lines.append(f"| 最大滑点 | {slippage_data.max():.4f}% |")
            report_lines.append(f"| 最小滑点 | {slippage_data.min():.4f}% |")
            report_lines.append(f"| 滑点中位数 | {slippage_data.median():.4f}% |")

    # 模拟盈亏统计
    if 'actual_pnl' in completed.columns:
        pnl_data = completed['actual_pnl'].dropna()
        if len(pnl_data) > 0:
            win_count = (pnl_data > 0).sum()
            report_lines.append(f"\n## 模拟交易统计（T+1买入 → T+5卖出）")
            report_lines.append(f"| 指标 | 值 |")
            report_lines.append(f"|------|-----|")
            report_lines.append(f"| 交易笔数 | {len(pnl_data)} |")
            report_lines.append(f"| 胜率 | {win_count/len(pnl_data)*100:.1f}% |")
            report_lines.append(f"| 平均盈亏 | {pnl_data.mean():.2f}% |")
            report_lines.append(f"| 最大单笔盈利 | {pnl_data.max():.2f}% |")
            report_lines.append(f"| 最大单笔亏损 | {pnl_data.min():.2f}% |")
            report_lines.append(f"| 累计盈亏 | {pnl_data.sum():.2f}% |")

    # 按信号类型统计
    if 'signal_type' in tracking.columns and 'actual_pnl' in tracking.columns:
        report_lines.append(f"\n## 分信号类型统计")
        report_lines.append(f"| 信号类型 | 笔数 | 胜率 | 平均盈亏 |")
        report_lines.append(f"|----------|------|------|----------|")
        for st in tracking['signal_type'].unique():
            st_data = tracking[tracking['signal_type'] == st]['actual_pnl'].dropna()
            if len(st_data) > 0:
                wr = (st_data > 0).sum() / len(st_data) * 100
                report_lines.append(
                    f"| {st} | {len(st_data)} | {wr:.1f}% | {st_data.mean():.2f}% |"
                )

    report_lines.append(f"\n---\n*报告由V5.3模拟盘跟踪系统自动生成*")

    report_text = "\n".join(report_lines)

    # 保存报告
    ensure_sim_dir()
    with open(SIM_REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(report_text)
    print(f"  报告已保存: {SIM_REPORT_FILE}")

    return report_text


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="V5.3模拟盘跟踪系统")
    parser.add_argument("--daily", action="store_true", help="每日扫描并记录信号")
    parser.add_argument("--update", action="store_true", help="更新跟踪数据")
    parser.add_argument("--report", action="store_true", help="生成跟踪报告")
    parser.add_argument("--start", type=str, default="2026-09-01",
                        help="模拟盘开始日期")
    args = parser.parse_args()

    ensure_sim_dir()

    if args.daily:
        scan_and_record()

    if args.update:
        update_tracking()

    if args.report:
        report = generate_report()
        print(report)

    if not (args.daily or args.update or args.report):
        print("用法:")
        print("  python sim_tracker.py --daily    # 每日扫描信号")
        print("  python sim_tracker.py --update   # 更新跟踪数据")
        print("  python sim_tracker.py --report   # 生成跟踪报告")
        print(f"\n模拟盘数据目录: {SIM_DATA_DIR}")
