"""
缠论买卖点识别模块（V2增强版）
==============================
在V1基础上增加：
1. 三买增强过滤：MACD金叉确认 + 成交量放大 + 下跌市直接过滤
2. 一买增强过滤：背驰面积比<0.7 + 下跌市额外RSI<30
3. 二买优化：斐波那契回调区间确认 + 量价背离确认
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict
from .core import (
    ChanLunAnalyzer, RawKline, Stroke, Segment, Pivot,
    calculate_macd, calc_macd_area, Trend
)
import sys
import os
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import (
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    BUY1_MACD_AREA_RATIO, BUY1_BEAR_RSI_THRESHOLD,
    BUY3_VOLUME_RATIO, BUY2_FIB_LOW, BUY2_FIB_HIGH,
    # V3参数
    BUY3_VOLUME_RATIO_V3, BUY3_VOLUME_RATIO_BULL,
    BUY3_REQUIRE_DIF_POSITIVE, BUY3_BULL_SKIP_MACD, BUY3_BEAR_BLOCK,
    SELL1_AREA_RATIO, SELL1_CLOSE_RATIO, SELL2_LOOKBACK_DAYS, SELL3_ENABLED,
)


@dataclass
class Signal:
    """交易信号"""
    signal_type: str     # 'buy1','buy2','buy3','sell1','sell2','sell3'
    date: str            # 信号日期
    price: float         # 信号价格（分型的高低点）
    description: str     # 信号描述
    pivot: Optional[Pivot] = None  # 关联的中枢
    market_env: str = ''  # 当时市场环境


def calc_rsi(closes: List[float], period: int = 14) -> List[float]:
    """计算RSI指标（Wilder平滑）
    【V5.3.1修复】原实现返回 len(closes)+1 个值，索引与K线错位一天；
    现改为与closes等长，rsi_values[i] 对应 closes[i]。
    """
    n = len(closes)
    rsi_values = [50.0] * n  # 前period根无法精确计算，填充中性值50
    if n < period + 1:
        return rsi_values

    deltas = np.diff(closes)
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)

    avg_gain = float(np.mean(gains[:period]))
    avg_loss = float(np.mean(losses[:period]))

    # 第一个可计算的RSI位于索引period（用到closes[0..period]共period+1根）
    if avg_loss == 0:
        rsi_values[period] = 100.0
    else:
        rsi_values[period] = 100 - 100 / (1 + avg_gain / avg_loss)

    for i in range(period, n - 1):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period

        if avg_loss == 0:
            rsi_values[i + 1] = 100.0
        else:
            rs = avg_gain / avg_loss
            rsi_values[i + 1] = 100 - 100 / (1 + rs)

    return rsi_values


def check_macd_golden_cross(dif: List[float], dea: List[float], 
                             idx: int, lookback: int = 5) -> bool:
    """
    检查在idx附近是否出现MACD金叉（DIF上穿DEA）
    lookback: 向前看几根K线内是否有金叉
    """
    if idx < 1 or idx >= len(dif):
        return False
    start = max(0, idx - lookback)
    for i in range(start + 1, idx + 1):
        if i >= len(dif):
            break
        if dif[i-1] <= dea[i-1] and dif[i] > dea[i]:
            return True
    return False


class SignalDetector:
    """买卖点检测器（V2增强版）"""

    def __init__(self, market_env_map: Dict[str, str] = None):
        self.signals: List[Signal] = []
        self.market_env_map = market_env_map or {}  # {date: env_type}

    def detect(self, klines: List[RawKline], analyzer: ChanLunAnalyzer) -> List[Signal]:
        """对已分析的数据检测所有买卖点信号"""
        self.signals = []

        if not analyzer.strokes or not analyzer.pivots:
            return self.signals

        closes = [k.close for k in klines]
        volumes = [k.volume for k in klines]
        date_to_idx = {k.date: i for i, k in enumerate(klines)}
        dif, dea, macd_hist = calculate_macd(closes, MACD_FAST, MACD_SLOW, MACD_SIGNAL)
        rsi_values = calc_rsi(closes, 14)

        # 检测一买一卖（增强过滤）
        self._detect_buy1_sell1(analyzer, macd_hist, dif, dea, rsi_values, date_to_idx, klines)

        # 检测二买二卖（优化）
        self._detect_buy2_sell2(analyzer, volumes, date_to_idx)

        # 检测三买三卖（增强过滤）
        self._detect_buy3_sell3(analyzer, macd_hist, dif, dea, volumes, date_to_idx, klines)

        # 按日期排序
        self.signals.sort(key=lambda s: s.date)

        return self.signals

    def _get_env(self, date: str) -> str:
        """获取某日的市场环境"""
        return self.market_env_map.get(date, 'sideways')

    def _detect_buy1_sell1(self, analyzer: ChanLunAnalyzer,
                            macd_hist: List[float],
                            dif: List[float], dea: List[float],
                            rsi_values: List[float],
                            date_to_idx: dict,
                            klines: List[RawKline]):
        """
        检测一买和一卖（增强版）
        一买：
          - 标准一买：下跌趋势（2+中枢）末端底背驰
          - 类一买：单中枢下方出现底背驰（盘整背驰）
        """
        detected_buy1_dates = set()
        
        # 方法1：标准一买（下跌趋势2+中枢）
        for trend in analyzer.trends:
            if trend.type == 'down' and len(trend.pivots) >= 2:
                self._try_detect_bottom_divergence(
                    trend.pivots[-1], analyzer, macd_hist, dif, dea,
                    rsi_values, date_to_idx, 'buy1', detected_buy1_dates)

            elif trend.type == 'up' and len(trend.pivots) >= 2:
                self._try_detect_top_divergence(
                    trend.pivots[-1], analyzer, macd_hist, date_to_idx, 'sell1')

        # 方法2：类一买（盘整背驰）- 中枢下方背驰
        for pivot in analyzer.pivots:
            # 找到中枢之后的向下笔
            after_down = [s for s in analyzer.strokes
                         if s.start_date >= pivot.end_date and s.direction == -1]
            # 找到中枢之前的向下笔（进入中枢的那一笔）
            before_down = [s for s in analyzer.strokes
                          if s.end_date <= pivot.start_date and s.direction == -1]
            
            if after_down and before_down:
                last_down = after_down[0]  # 紧接中枢后的第一笔下跌
                prev_down = before_down[-1]  # 进入中枢前的最后一笔下跌
                
                before_area = self._get_stroke_macd_area(prev_down, macd_hist, date_to_idx)
                after_area = self._get_stroke_macd_area(last_down, macd_hist, date_to_idx)
                
                area_ratio = abs(after_area) / abs(before_area) if abs(before_area) > 0 else 999
                
                # 放宽条件：只要MACD面积明显缩小且价格在低位区域
                if area_ratio < BUY1_MACD_AREA_RATIO and last_down.low <= prev_down.low * 1.02:
                    sig_date = last_down.end_date
                    if sig_date in detected_buy1_dates:
                        continue
                    detected_buy1_dates.add(sig_date)
                    
                    env = self._get_env(sig_date)
                    
                    # 下跌市额外要求RSI<30
                    if env == 'bear':
                        idx = date_to_idx.get(sig_date, 0)
                        if idx < len(rsi_values) and rsi_values[idx] >= BUY1_BEAR_RSI_THRESHOLD:
                            continue
                    
                    self.signals.append(Signal(
                        signal_type='buy1',
                        date=sig_date,
                        price=last_down.low,
                        description=f"类一买：盘整背驰(面积比{area_ratio:.2f})",
                        pivot=pivot,
                        market_env=env,
                    ))
        
        # 方法3：中枢内底背驰 - 连续中枢中最后一次下跌的背驰
        for i, pivot in enumerate(analyzer.pivots):
            down_strokes_in_pivot = [s for s in pivot.segments[0].strokes if s.direction == -1] if pivot.segments else []
            if len(down_strokes_in_pivot) >= 2:
                for j in range(1, len(down_strokes_in_pivot)):
                    curr_down = down_strokes_in_pivot[j]
                    prev_down_s = down_strokes_in_pivot[j-1]
                    
                    before_area = self._get_stroke_macd_area(prev_down_s, macd_hist, date_to_idx)
                    after_area = self._get_stroke_macd_area(curr_down, macd_hist, date_to_idx)
                    
                    area_ratio = abs(after_area) / abs(before_area) if abs(before_area) > 0 else 999
                    
                    if curr_down.low <= prev_down_s.low and area_ratio < 0.5:
                        sig_date = curr_down.end_date
                        if sig_date in detected_buy1_dates:
                            continue
                        detected_buy1_dates.add(sig_date)
                        
                        env = self._get_env(sig_date)
                        if env == 'bear':
                            idx = date_to_idx.get(sig_date, 0)
                            if idx < len(rsi_values) and rsi_values[idx] >= BUY1_BEAR_RSI_THRESHOLD:
                                continue
                        
                        self.signals.append(Signal(
                            signal_type='buy1',
                            date=sig_date,
                            price=curr_down.low,
                            description=f"类一买：中枢内背驰(面积比{area_ratio:.2f})",
                            pivot=pivot,
                            market_env=env,
                        ))

    def _try_detect_bottom_divergence(self, pivot, analyzer, macd_hist, dif, dea,
                                       rsi_values, date_to_idx, signal_type, detected_dates):
        """尝试在中枢末端检测底背驰"""
        pivot_end_date = pivot.end_date
        after_strokes = [s for s in analyzer.strokes
                        if s.start_date >= pivot_end_date and s.direction == -1]
        before_strokes = [s for s in analyzer.strokes
                         if s.end_date <= pivot.start_date and s.direction == -1]
        
        if after_strokes and before_strokes:
            last_down = after_strokes[-1]
            prev_down = before_strokes[-1]
            before_area = self._get_stroke_macd_area(prev_down, macd_hist, date_to_idx)
            after_area = self._get_stroke_macd_area(last_down, macd_hist, date_to_idx)
            
            area_ratio = abs(after_area) / abs(before_area) if abs(before_area) > 0 else 999
            
            if last_down.low <= prev_down.low and area_ratio < BUY1_MACD_AREA_RATIO:
                sig_date = last_down.end_date
                if sig_date in detected_dates:
                    return
                detected_dates.add(sig_date)
                
                env = self._get_env(sig_date)
                if env == 'bear':
                    idx = date_to_idx.get(sig_date, 0)
                    if idx < len(rsi_values) and rsi_values[idx] >= BUY1_BEAR_RSI_THRESHOLD:
                        return
                
                self.signals.append(Signal(
                    signal_type='buy1',
                    date=sig_date,
                    price=last_down.low,
                    description=f"一买：底背驰(面积比{area_ratio:.2f})",
                    pivot=pivot,
                    market_env=env,
                ))

    def _try_detect_top_divergence(self, pivot, analyzer, macd_hist, date_to_idx, signal_type):
        """尝试在中枢末端检测顶背驰"""
        pivot_end_date = pivot.end_date
        after_strokes = [s for s in analyzer.strokes
                        if s.start_date >= pivot_end_date and s.direction == 1]
        before_strokes = [s for s in analyzer.strokes
                         if s.end_date <= pivot.start_date and s.direction == 1]
        
        if after_strokes and before_strokes:
            last_up = after_strokes[-1]
            prev_up = before_strokes[-1]
            before_area = self._get_stroke_macd_area(prev_up, macd_hist, date_to_idx)
            after_area = self._get_stroke_macd_area(last_up, macd_hist, date_to_idx)
            
            # V3: 使用可配置的背驰阈值（前段面积/后段面积 > SELL1_AREA_RATIO）
            area_ratio_sell = abs(before_area) / abs(after_area) if abs(after_area) > 0.001 else 999
            if last_up.high >= prev_up.high and area_ratio_sell >= SELL1_AREA_RATIO:
                self.signals.append(Signal(
                    signal_type='sell1',
                    date=last_up.end_date,
                    price=last_up.high,
                    description=f"一卖：顶背驰",
                    pivot=pivot,
                    market_env=self._get_env(last_up.end_date),
                ))

    def _detect_buy2_sell2(self, analyzer: ChanLunAnalyzer,
                            volumes: List[float],
                            date_to_idx: dict):
        """
        检测二买和二卖（V4修复版）
        ========================
        V4修复：
        - P0-Bug1: 遍历所有一买后的向下笔，找到第一个不破一买低点的回调（而非只取第一笔）
        - P0-Bug2: 环境判断改用回调完成日期的环境（而非一买日期的环境）
        二买优化：斐波那契回调区间确认 + 成交量萎缩
        """
        buy1_signals = [s for s in self.signals if s.signal_type == 'buy1']
        sell1_signals = [s for s in self.signals if s.signal_type == 'sell1']

        # 防止同一笔产生多个二买信号
        detected_buy2_dates = set()

        for b1 in buy1_signals:
            # 【P0-Bug1修复】遍历所有一买后的向下笔，找到第一个不破一买低点的回调
            after_strokes = [s for s in analyzer.strokes
                            if s.start_date > b1.date and s.direction == -1]
            
            valid_pullback = None
            for candidate in after_strokes:
                if candidate.low > b1.price:
                    # 找到了不破一买低点的回调笔
                    valid_pullback = candidate
                    break
                # 如果这笔破了一买低点，继续找下一笔
            
            if valid_pullback is None:
                continue  # 没有有效的回调笔
            
            # 【P0-Bug2修复】用回调完成日期的环境（而非一买日期的环境）
            pullback_env = self._get_env(valid_pullback.end_date)
            if pullback_env == 'bear':
                continue  # 回调完成时处于下跌市，禁止二买
            
            # 检查是否已有二买信号在该日期
            if valid_pullback.end_date in detected_buy2_dates:
                continue
            detected_buy2_dates.add(valid_pullback.end_date)
            
            # 斐波那契回调检查
            prev_up_strokes = [s for s in analyzer.strokes
                               if s.end_date <= b1.date and s.direction == 1]
            if prev_up_strokes:
                swing_high = prev_up_strokes[-1].high
                swing_low = b1.price  # 一买低点
                fib_range = swing_high - swing_low
                
                if fib_range > 0:
                    retracement = (swing_high - valid_pullback.low) / fib_range
                    # V5优化：容差从±0.15收紧到±0.05，减少噪音二买
                    if not (BUY2_FIB_LOW - 0.05 <= retracement <= BUY2_FIB_HIGH + 0.05):
                        continue  # 回调幅度不在斐波那契区间
            
            # 成交量萎缩检查
            pullback_end_idx = date_to_idx.get(valid_pullback.end_date, 0)
            pullback_start_idx = date_to_idx.get(valid_pullback.start_date, 0)
            
            vol_shrink = True
            if pullback_end_idx > pullback_start_idx and len(volumes) > pullback_end_idx:
                up_strokes_before = [s for s in analyzer.strokes
                                    if s.end_date <= valid_pullback.start_date and s.direction == 1]
                if up_strokes_before:
                    up_end_idx = date_to_idx.get(up_strokes_before[-1].end_date, 0)
                    up_start_idx = date_to_idx.get(up_strokes_before[-1].start_date, 0)
                    if up_end_idx > up_start_idx:
                        avg_vol_up = np.mean(volumes[up_start_idx:up_end_idx+1]) if up_end_idx < len(volumes) else 0
                        avg_vol_pb = np.mean(volumes[pullback_start_idx:pullback_end_idx+1]) if pullback_end_idx < len(volumes) else 0
                        if avg_vol_up > 0 and avg_vol_pb > avg_vol_up * 0.9:
                            vol_shrink = False  # 量没有萎缩
            
            self.signals.append(Signal(
                signal_type='buy2',
                date=valid_pullback.end_date,
                price=valid_pullback.low,
                description=f"二买：回调不破一买低点{b1.price:.2f}，回调低点{valid_pullback.low:.2f}",
                pivot=b1.pivot,
                market_env=pullback_env,
            ))

        # 二卖
        for s1 in sell1_signals:
            after_strokes = [s for s in analyzer.strokes
                            if s.start_date > s1.date and s.direction == 1]
            if after_strokes:
                first_bounce = after_strokes[0]
                if first_bounce.high < s1.price:
                    self.signals.append(Signal(
                        signal_type='sell2',
                        date=first_bounce.end_date,
                        price=first_bounce.high,
                        description=f"二卖：反弹不破一卖高点{s1.price:.2f}",
                        pivot=s1.pivot,
                        market_env=self._get_env(first_bounce.end_date),
                    ))

    def _detect_buy3_sell3(self, analyzer: ChanLunAnalyzer,
                            macd_hist: List[float],
                            dif: List[float], dea: List[float],
                            volumes: List[float],
                            date_to_idx: dict,
                            klines: List[RawKline]):
        """
        检测三买和三卖（V3放宽版）
        V3变化：
        - 成交量要求从1.2倍降到0.8倍
        - MACD条件：不要求金叉，只要求DIF > 0
        - 上涨市：MACD条件完全取消，量能>0.5倍即可
        - 下跌市：仍然禁止三买
        """
        for pivot in analyzer.pivots:
            after_strokes = [s for s in analyzer.strokes
                            if s.start_date >= pivot.end_date]

            if not after_strokes:
                continue

            # 计算中枢内平均成交量
            pivot_start_idx = date_to_idx.get(pivot.start_date, 0)
            pivot_end_idx = date_to_idx.get(pivot.end_date, len(volumes) - 1)
            if pivot_end_idx > pivot_start_idx and pivot_end_idx < len(volumes):
                avg_vol_in_pivot = np.mean(volumes[pivot_start_idx:pivot_end_idx + 1])
            else:
                avg_vol_in_pivot = 0

            # 检测三买（V3放宽条件）
            for i, stroke in enumerate(after_strokes):
                if stroke.direction == 1 and stroke.high > pivot.zg:
                    if i + 1 < len(after_strokes):
                        pullback = after_strokes[i + 1]
                        if pullback.direction == -1 and pullback.low > pivot.zg:
                            sig_date = pullback.end_date
                            env = self._get_env(sig_date)
                            
                            # 下跌市直接过滤三买（保留原规则）
                            if BUY3_BEAR_BLOCK and env == 'bear':
                                break
                            
                            # V3: MACD条件放宽
                            sig_idx = date_to_idx.get(sig_date, 0)
                            if env == 'bull' and BUY3_BULL_SKIP_MACD:
                                pass  # 上涨市完全跳过MACD检查
                            elif BUY3_REQUIRE_DIF_POSITIVE:
                                # 只要求DIF > 0（零轴上方）
                                if sig_idx >= len(dif) or dif[sig_idx] <= 0:
                                    break  # DIF不在零轴上方
                            
                            # V3: 成交量条件放宽
                            leave_idx = date_to_idx.get(stroke.end_date, 0)
                            if leave_idx < len(volumes) and avg_vol_in_pivot > 0:
                                leave_vol = volumes[leave_idx]
                                # 根据市场环境使用不同量能阈值
                                if env == 'bull':
                                    vol_threshold = avg_vol_in_pivot * BUY3_VOLUME_RATIO_BULL
                                else:
                                    vol_threshold = avg_vol_in_pivot * BUY3_VOLUME_RATIO_V3
                                if leave_vol < vol_threshold:
                                    break  # 量不够
                            
                            desc = f"三买：回调不跌回中枢上沿{pivot.zg:.2f}"
                            if env == 'bull':
                                desc += "（上涨市放宽条件）"
                            else:
                                desc += f"（DIF={dif[sig_idx]:.4f}，量比={volumes[leave_idx]/avg_vol_in_pivot:.2f}）"
                            
                            self.signals.append(Signal(
                                signal_type='buy3',
                                date=sig_date,
                                price=pullback.low,
                                description=desc,
                                pivot=pivot,
                                market_env=env,
                            ))
                    break

            # 检测三卖（V3增强）
            if SELL3_ENABLED:
                for i, stroke in enumerate(after_strokes):
                    if stroke.direction == -1 and stroke.low < pivot.zd:
                        if i + 1 < len(after_strokes):
                            bounce = after_strokes[i + 1]
                            if bounce.direction == 1 and bounce.high < pivot.zd:
                                self.signals.append(Signal(
                                    signal_type='sell3',
                                    date=bounce.end_date,
                                    price=bounce.high,
                                    description=f"三卖：反弹不进中枢下沿{pivot.zd:.2f}",
                                    pivot=pivot,
                                    market_env=self._get_env(bounce.end_date),
                                ))
                        break

    def _get_stroke_macd_area(self, stroke: Stroke,
                               macd_hist: List[float],
                               date_to_idx: dict) -> float:
        """获取一笔对应的MACD面积"""
        start_idx = date_to_idx.get(stroke.start_date, 0)
        end_idx = date_to_idx.get(stroke.end_date, len(macd_hist) - 1)
        return calc_macd_area(macd_hist, start_idx, end_idx)


def detect_signals(klines: List[RawKline], 
                   market_env_map: Dict[str, str] = None) -> List[Signal]:
    """便捷函数"""
    analyzer = ChanLunAnalyzer()
    analyzer.analyze(klines)
    detector = SignalDetector(market_env_map)
    return detector.detect(klines, analyzer)
