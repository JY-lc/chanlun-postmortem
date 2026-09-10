"""
缠论全市场扫描器（V4两阶段高效版）
========================
功能：
1. 两阶段扫描：快速预筛(~10秒) + 精确分析(~15-25分钟)
2. Stage1: 东方财富API获取全市场列表，快速过滤
3. Stage2: 对候选标的逐一获取K线并运行缠论分析
4. 重点关注二买和三买（确定性更高）
"""

import os
import sys
from typing import List, Dict, Tuple, Optional
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.core import RawKline, ChanLunAnalyzer
from chanlun.signal import SignalDetector, Signal
from data_fetcher import fetch_stock_hist, fetch_stock_list_eastmoney, fetch_stock_hist_batch
from config import (
    ENV_ALLOW_BUY, SCANNER_USE_ENV_FILTER, SCANNER_LOOKBACK_DAYS,
    MARKET_INDEX_SYMBOL,
)


def signal_allowed_by_env(sig: Signal, env: str) -> bool:
    """
    【V5.3.1新增】按市场环境过滤买卖点，与回测引擎 _is_signal_allowed 同规则。
    回测中信号要经过 env_params['allow_buy*'] 过滤，实盘扫描也必须一致，
    否则扫描出的信号在回测中根本不会成交（例如震荡市的三买）。
    """
    if not SCANNER_USE_ENV_FILTER:
        return True
    if sig.signal_type.startswith('sell'):
        return True
    env_allow = ENV_ALLOW_BUY.get(env, {})
    return bool(env_allow.get(sig.signal_type, True))


def df_to_klines(df: pd.DataFrame) -> List[RawKline]:
    """DataFrame转RawKline列表"""
    klines = []
    for i, row in df.iterrows():
        date_str = str(row['日期'])[:10] if '日期' in df.columns else str(row.index)[:10]
        klines.append(RawKline(
            date=date_str,
            open=float(row['开盘']),
            high=float(row['最高']),
            low=float(row['最低']),
            close=float(row['收盘']),
            volume=float(row.get('成交量', 0)),
            index=len(klines),
        ))
    return klines


class MarketScanner:
    """全市场扫描器（支持两阶段高效扫描）"""

    def __init__(self):
        self.results = []

    def get_all_stocks(self) -> pd.DataFrame:
        """获取全市场股票列表，过滤不合格的股票"""
        print("获取全市场股票列表...")
        stock_info = fetch_stock_list_eastmoney()

        if stock_info.empty:
            print("  获取股票列表失败")
            return stock_info

        # 过滤ST
        stock_info = stock_info[~stock_info['名称'].str.contains('ST|退市', na=False)]

        # 过滤停牌
        stock_info = stock_info[pd.to_numeric(stock_info['最新价'], errors='coerce') > 0]

        print(f"  过滤后剩余 {len(stock_info)} 只股票")
        return stock_info

    def scan_full_market(self, min_price: float = 2.0, min_pullback: float = 0.05) -> Dict[str, dict]:
        """
        两阶段全市场扫描
        
        Stage 1 - 快速预筛(~10秒):
            1. 东方财富API获取全市场列表
            2. 过滤: 价格>min_price, 非ST/退市/停牌, 排除科创板(688)/北交所(8开头)
            3. 过滤: 当日最高价相对当前价回调 >= min_pullback
        
        Stage 2 - 精确分析(~15-25分钟):
            1. 批量获取候选标的120日K线
            2. 数据不足60日的跳过
            3. 运行缠论分析，只保留最近20个交易日内的信号
        
        返回: {symbol: {name, signals, score}} 字典
        """
        start_time = datetime.now()
        print("=" * 70)
        print("缠论全市场两阶段扫描")
        print(f"开始时间: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        
        # ========== Stage 1: 快速预筛 ==========
        print("\n【Stage 1】快速预筛...")
        t1 = datetime.now()
        
        # 获取全市场列表
        all_stocks = fetch_stock_list_eastmoney()
        total_market = len(all_stocks)
        print(f"  全市场总计: {total_market}只标的")
        
        # 过滤条件1: 价格 > min_price
        all_stocks = all_stocks[all_stocks['最新价'] > min_price]
        after_price = len(all_stocks)
        print(f"  价格>{min_price}元: {after_price}只 (排除{total_market - after_price}只低价股)")
        
        # 过滤条件2: 排除科创板(688)、北交所(8/920开头)、申赎基金
        all_stocks = all_stocks[~all_stocks['代码'].str.startswith('688')]
        all_stocks = all_stocks[~all_stocks['代码'].str.startswith('8')]
        all_stocks = all_stocks[~all_stocks['代码'].str.startswith('920')]
        after_board = len(all_stocks)
        print(f"  排除科创/北交: {after_board}只 (排除{after_price - after_board}只)")
        
        # 过滤条件3: 当日最高价相对当前价有回调 (最高-当前)/当前 >= min_pullback
        all_stocks['回调幅度'] = (all_stocks['最高'] - all_stocks['最新价']) / all_stocks['最新价']
        all_stocks = all_stocks[all_stocks['回调幅度'] >= min_pullback]
        after_pullback = len(all_stocks)
        print(f"  回调>={min_pullback*100:.0f}%: {after_pullback}只 (排除{after_board - after_pullback}只无回调标的)")
        
        t1_end = datetime.now()
        print(f"  Stage 1 完成: 预筛出 {after_pullback} 只候选标的, 耗时 {(t1_end - t1).total_seconds():.1f}秒")
        
        if after_pullback == 0:
            print("  无候选标的，扫描结束")
            return {}
        
        # ========== Stage 2: 精确分析 ==========
        print(f"\n【Stage 2】精确分析 {after_pullback} 只候选标的...")
        t2 = datetime.now()
        
        # 准备候选列表
        candidates = {}
        for _, row in all_stocks.iterrows():
            code = str(row['代码']).zfill(6)
            candidates[code] = row['名称']
        
        # 批量获取K线数据
        symbol_list = list(candidates.keys())
        hist_data = fetch_stock_hist_batch(symbol_list, days_back=120, progress_interval=100)
        
        # 逐一分析
        analyzed = 0
        skipped = 0
        signal_results = {}
        
        for idx, symbol in enumerate(symbol_list):
            if (idx + 1) % 100 == 0:
                print(f"    分析进度: {idx+1}/{len(symbol_list)}, 已发现{len(signal_results)}个信号")
            
            if symbol not in hist_data:
                skipped += 1
                continue
            
            df = hist_data[symbol]
            
            # 数据不足60日跳过
            if len(df) < 60:
                skipped += 1
                continue
            
            analyzed += 1
            
            # 运行缠论分析
            try:
                klines = df_to_klines(df)
                analyzer = ChanLunAnalyzer()
                analyzer.analyze(klines)
                detector = SignalDetector()
                signals = detector.detect(klines, analyzer)
                
                # 只保留最近20个交易日的信号
                if klines:
                    cutoff_date = klines[-min(20, len(klines))].date
                    signals = [s for s in signals if s.date >= cutoff_date]
                
                if signals:
                    signal_results[symbol] = {
                        'name': candidates.get(symbol, ''),
                        'signals': signals,
                    }
            except Exception as e:
                # 分析失败，静默跳过
                skipped += 1
                continue
        
        t2_end = datetime.now()
        stage2_time = (t2_end - t2).total_seconds()
        total_time = (t2_end - start_time).total_seconds()
        
        print(f"  Stage 2 完成: 有效分析{analyzed}只, 跳过{skipped}只, 发现{len(signal_results)}个有信号标的")
        print(f"  Stage 2 耗时: {stage2_time:.1f}秒 ({stage2_time/60:.1f}分钟)")
        print(f"  总耗时: {total_time:.1f}秒 ({total_time/60:.1f}分钟)")
        
        # 输出统计摘要
        print(f"\n{'='*50}")
        print(f"扫描统计:")
        print(f"  全市场总数 → {total_market}")
        print(f"  预筛候选数 → {after_pullback}")
        print(f"  有效分析数 → {analyzed}")
        print(f"  发现信号数 → {len(signal_results)}")
        print(f"{'='*50}")
        
        return signal_results

    def scan_stock(self, symbol: str, name: str, days_back: int = None,
                   env_map: Dict[str, str] = None) -> List[Signal]:
        """
        扫描单只股票
        days_back: K线回溯天数（默认SCANNER_LOOKBACK_DAYS≈3年；回测用全历史，
                   回溯太短会导致笔/线段/中枢结构与回测不一致、信号对不上）
        env_map: 市场环境映射 {date: 'bull'/'sideways'/'bear'}；传入后按回测同规则过滤信号
        """
        if days_back is None:
            days_back = SCANNER_LOOKBACK_DAYS
        end_date = datetime.now().strftime('%Y%m%d')
        start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')

        df = fetch_stock_hist(symbol, start_date, end_date)

        if df is None or len(df) < 30:
            return []

        klines = df_to_klines(df)
        analyzer = ChanLunAnalyzer()
        analyzer.analyze(klines)
        detector = SignalDetector(env_map or {})
        signals = detector.detect(klines, analyzer)

        # 【V5.3.1新增】环境过滤：与回测引擎一致（如震荡市禁三买、下跌市禁二三买）
        if SCANNER_USE_ENV_FILTER and env_map:
            filtered = []
            for s in signals:
                env = env_map.get(s.date, 'sideways')
                if signal_allowed_by_env(s, env):
                    s.market_env = env
                    filtered.append(s)
            signals = filtered

        # 只保留最近的信号（最后20个交易日内）
        if klines:
            cutoff_date = klines[-min(20, len(klines))].date
            signals = [s for s in signals if s.date >= cutoff_date]

        return signals

    def scan_batch(self, symbols: Dict[str, str], show_progress: bool = True,
                   env_map: Dict[str, str] = None) -> Dict[str, List[Signal]]:
        """
        批量扫描（快速模式，用于58只核心标的）
        symbols: {code: name}
        env_map: 市场环境映射（可选），传入后按回测规则过滤信号
        """
        all_results = {}

        total = len(symbols)
        for idx, (symbol, name) in enumerate(symbols.items()):
            if show_progress and (idx + 1) % 10 == 0:
                print(f"  扫描进度: {idx + 1}/{total}")

            signals = self.scan_stock(symbol, name, env_map=env_map)
            if signals:
                all_results[symbol] = {
                    'name': name,
                    'signals': signals,
                }

        return all_results

    def format_results(self, results: Dict[str, dict]) -> str:
        """格式化扫描结果（按信号优先级排序）"""
        if not results:
            return "未发现任何买卖点信号"

        lines = []
        lines.append("=" * 70)
        lines.append("缠论扫描结果")
        lines.append(f"扫描时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("=" * 70)

        # 信号优先级排序: buy3 > buy2 > buy1 > sell3 > sell2 > sell1
        signal_priority = {
            'buy3': 0, 'buy2': 1, 'buy1': 2,
            'sell3': 3, 'sell2': 4, 'sell1': 5,
        }
        
        signal_names = {
            'buy1': '🔴 一买（趋势底背驰）',
            'buy2': '🟢 二买（回调不破前低）⭐ 重点关注',
            'buy3': '🟡 三买（回调不进中枢）⭐⭐ 重点关注',
            'sell1': '🔴 一卖（趋势顶背驰）',
            'sell2': '🟢 二卖（反弹不破前高）',
            'sell3': '🟡 三卖（反弹不进中枢）',
        }

        # 收集所有信号并排序
        all_signals = []
        for symbol, data in results.items():
            for sig in data['signals']:
                all_signals.append({
                    'symbol': symbol,
                    'name': data['name'],
                    'signal': sig,
                    'priority': signal_priority.get(sig.signal_type, 99),
                })
        
        # 按优先级排序
        all_signals.sort(key=lambda x: x['priority'])

        # 按类型分组输出
        current_type = None
        for item in all_signals:
            sig = item['signal']
            if sig.signal_type != current_type:
                current_type = sig.signal_type
                # 统计该类型数量
                count = sum(1 for s in all_signals if s['signal'].signal_type == current_type)
                lines.append(f"\n{signal_names.get(current_type, current_type)} ({count}只)")
                lines.append("-" * 50)
            
            pivot_info = ""
            if sig.pivot:
                pivot_info = f" 中枢[{sig.pivot.zd:.2f}, {sig.pivot.zg:.2f}]"
            
            lines.append(
                f"  {item['symbol']} {item['name']:<8s} "
                f"信号日期:{sig.date} 价格:{sig.price:.2f}{pivot_info}"
            )

        lines.append("\n" + "=" * 70)
        return "\n".join(lines)


if __name__ == "__main__":
    scanner = MarketScanner()
    results = scanner.scan_full_market()
    print(scanner.format_results(results))
