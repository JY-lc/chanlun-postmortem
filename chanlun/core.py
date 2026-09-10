"""
缠论核心算法模块
================
实现缠论的基础数据结构与算法：
1. K线包含处理（合并包含关系的K线）
2. 分型识别（顶分型、底分型）
3. 笔的划分（连接相邻顶底分型）
4. 线段划分（至少3笔构成，特征序列终结）
5. 中枢构建（至少3段重叠区间）
6. 走势类型判断
"""

from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from enum import Enum


# ===================== 数据类定义 =====================

@dataclass
class RawKline:
    """原始K线"""
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    index: int = 0  # 在原始序列中的序号


@dataclass
class MergedKline:
    """经过包含处理后的K线"""
    date: str          # 取最后一根合并K线的日期
    high: float
    low: float
    start_date: str    # 合并起始日期
    end_date: str      # 合并结束日期
    direction: int = 0  # 合并方向：1=上涨, -1=下跌
    raw_count: int = 1  # 合并了几根原始K线
    index: int = 0     # 在处理序列中的序号


@dataclass
class Fractal:
    """分型"""
    date: str
    type: str          # 'top' 或 'bottom'
    high: float        # 分型中间K线的高点
    low: float         # 分型中间K线的低点
    index: int = 0     # 在合并K线序列中的序号（中间K线的索引）


@dataclass
class Stroke:
    """笔"""
    start: Fractal     # 起始分型
    end: Fractal       # 结束分型
    direction: int     # 1=向上笔, -1=向下笔
    high: float        # 笔的最高点
    low: float         # 笔的最低点

    @property
    def length(self) -> float:
        return self.high - self.low

    @property
    def start_date(self) -> str:
        return self.start.date

    @property
    def end_date(self) -> str:
        return self.end.date


@dataclass
class Segment:
    """线段"""
    start_stroke: Stroke   # 起始笔
    end_stroke: Stroke     # 结束笔
    direction: int         # 1=向上线段, -1=向下线段
    strokes: List[Stroke] = field(default_factory=list)  # 包含的笔

    @property
    def high(self) -> float:
        if self.direction == 1:
            return self.end_stroke.high
        else:
            return self.start_stroke.high

    @property
    def low(self) -> float:
        if self.direction == 1:
            return self.start_stroke.low
        else:
            return self.end_stroke.low

    @property
    def start_date(self) -> str:
        return self.start_stroke.start_date

    @property
    def end_date(self) -> str:
        return self.end_stroke.end_date


@dataclass
class Pivot:
    """中枢（走势中枢）"""
    zg: float              # 中枢上沿 = min(各段高点)
    zd: float              # 中枢下沿 = max(各段低点)
    segments: List[Segment] = field(default_factory=list)
    level: int = 1         # 中枢级别

    @property
    def is_valid(self) -> bool:
        return self.zg > self.zd

    @property
    def start_date(self) -> str:
        if self.segments:
            return self.segments[0].start_date
        return ""

    @property
    def end_date(self) -> str:
        if self.segments:
            return self.segments[-1].end_date
        return ""

    @property
    def center(self) -> float:
        """中枢中心价格"""
        return (self.zg + self.zd) / 2


@dataclass
class Trend:
    """走势"""
    type: str              # 'up'=上涨, 'down'=下跌, 'consolidation'=盘整
    pivots: List[Pivot] = field(default_factory=list)

    @property
    def start_date(self) -> str:
        if self.pivots:
            return self.pivots[0].start_date
        return ""

    @property
    def end_date(self) -> str:
        if self.pivots:
            return self.pivots[-1].end_date
        return ""


# ===================== 缠论核心分析类 =====================

class ChanLunAnalyzer:
    """缠论分析器"""

    def __init__(self):
        self.raw_klines: List[RawKline] = []
        self.merged_klines: List[MergedKline] = []
        self.fractals: List[Fractal] = []
        self.strokes: List[Stroke] = []
        self.segments: List[Segment] = []
        self.pivots: List[Pivot] = []
        self.trends: List[Trend] = []

    def analyze(self, klines: List[RawKline]) -> dict:
        """
        执行完整的缠论分析流程
        返回各级别分析结果
        """
        if len(klines) < 3:
            return {}

        self.raw_klines = klines

        # 第1步：K线包含处理
        self.merged_klines = self._merge_klines(klines)

        # 第2步：分型识别
        self.fractals = self._find_fractals(self.merged_klines)

        # 第3步：笔的划分
        self.strokes = self._build_strokes(self.fractals, self.merged_klines)

        # 第4步：线段划分
        self.segments = self._build_segments(self.strokes)

        # 第5步：中枢构建
        self.pivots = self._build_pivots(self.segments)

        # 第6步：走势类型判断
        self.trends = self._identify_trends(self.pivots)

        return {
            'raw_klines': self.raw_klines,
            'merged_klines': self.merged_klines,
            'fractals': self.fractals,
            'strokes': self.strokes,
            'segments': self.segments,
            'pivots': self.pivots,
            'trends': self.trends,
        }

    # ==================== 第1步：K线包含处理 ====================

    def _merge_klines(self, klines: List[RawKline]) -> List[MergedKline]:
        """
        K线包含处理
        规则：
        - 如果相邻两根K线存在包含关系（一根的高低点完全包含另一根），需要合并
        - 上涨方向：取两根K线高点的较高者、低点的较高者
        - 下跌方向：取两根K线低点的较低者、高点的较低者
        - 方向判断：当前已处理K线的高点 > 前一根已处理K线的高点 → 上涨方向
        """
        if not klines:
            return []

        result = []

        # 初始化第一根
        first = klines[0]
        prev = MergedKline(
            date=first.date,
            high=first.high,
            low=first.low,
            start_date=first.date,
            end_date=first.date,
            direction=0,
            raw_count=1,
            index=0,
        )
        result.append(prev)

        for i in range(1, len(klines)):
            cur = klines[i]

            # 判断是否存在包含关系
            # 包含条件：A包含B 或 B包含A
            contains = self._is_contain(prev, cur)

            if contains:
                # 确定合并方向
                direction = self._get_merge_direction(result)
                # 执行合并
                if direction >= 0:  # 上涨方向
                    new_high = max(prev.high, cur.high)
                    new_low = max(prev.low, cur.low)
                else:  # 下跌方向
                    new_high = min(prev.high, cur.high)
                    new_low = min(prev.low, cur.low)

                prev.high = new_high
                prev.low = new_low
                prev.end_date = cur.date
                prev.raw_count += 1
            else:
                # 不包含，新建一根处理后的K线
                new_mk = MergedKline(
                    date=cur.date,
                    high=cur.high,
                    low=cur.low,
                    start_date=cur.date,
                    end_date=cur.date,
                    direction=self._get_merge_direction(result),
                    raw_count=1,
                    index=len(result),
                )
                result.append(new_mk)
                prev = new_mk

        # 重新编号
        for i, mk in enumerate(result):
            mk.index = i

        return result

    def _is_contain(self, prev: MergedKline, cur: RawKline) -> bool:
        """判断两根K线是否存在包含关系"""
        # prev包含cur：prev.high >= cur.high 且 prev.low <= cur.low
        # cur包含prev：cur.high >= prev.high 且 cur.low <= prev.low
        return (prev.high >= cur.high and prev.low <= cur.low) or \
               (cur.high >= prev.high and cur.low <= prev.low)

    def _get_merge_direction(self, result: List[MergedKline]) -> int:
        """获取当前合并方向"""
        if len(result) < 2:
            return 1  # 默认上涨
        if result[-1].high > result[-2].high:
            return 1   # 上涨
        elif result[-1].high < result[-2].high:
            return -1  # 下跌
        else:
            return result[-1].direction if result[-1].direction != 0 else 1

    # ==================== 第2步：分型识别 ====================

    def _find_fractals(self, merged: List[MergedKline]) -> List[Fractal]:
        """
        分型识别
        - 三根经过包含处理的K线
        - 中间K线高点最高且低点最高 → 顶分型
        - 中间K线高点最低且低点最低 → 底分型
        """
        if len(merged) < 3:
            return []

        fractals = []
        for i in range(1, len(merged) - 1):
            prev_k = merged[i - 1]
            curr_k = merged[i]
            next_k = merged[i + 1]

            # 顶分型：中间K线高点最高，且低点也最高
            if curr_k.high > prev_k.high and curr_k.high > next_k.high and \
               curr_k.low > prev_k.low and curr_k.low > next_k.low:
                fractals.append(Fractal(
                    date=curr_k.date,
                    type='top',
                    high=curr_k.high,
                    low=curr_k.low,
                    index=i,
                ))
            # 底分型：中间K线高点最低，且低点也最低
            elif curr_k.high < prev_k.high and curr_k.high < next_k.high and \
                 curr_k.low < prev_k.low and curr_k.low < next_k.low:
                fractals.append(Fractal(
                    date=curr_k.date,
                    type='bottom',
                    high=curr_k.high,
                    low=curr_k.low,
                    index=i,
                ))

        return fractals

    # ==================== 第3步：笔的划分 ====================

    def _build_strokes(self, fractals: List[Fractal],
                       merged: List[MergedKline]) -> List[Stroke]:
        """
        笔的划分规则：
        1. 顶分型到底分型为一笔（向下笔），底分型到顶分型为一笔（向上笔）
        2. 顶分型和底分型之间至少有1根独立K线（新笔定义至少5根K线）
           即两个分型的中间K线索引差 >= 3（中间至少隔3根合并K线）
        3. 向上笔的顶分型高点必须高于前一个向下笔的底分型低点
        4. 向下笔的底分型低点必须低于前一个向上笔的顶分型高点
        5. 笔必须交替出现：上-下-上-下...
        """
        if len(fractals) < 2:
            return []

        strokes = []
        # 先找到第一个有效的起始分型
        # 从第一个分型开始，尝试构建笔

        selected = [fractals[0]]  # 先放入第一个分型

        for i in range(1, len(fractals)):
            curr = fractals[i]
            last = selected[-1]

            # 要求：分型类型必须交替（顶-底-顶-底...）
            if curr.type == last.type:
                # 同类分型：取更极端的
                if curr.type == 'top':
                    # 取高点更高的
                    if curr.high > last.high:
                        selected[-1] = curr
                else:  # bottom
                    # 取低点更低的
                    if curr.low < last.low:
                        selected[-1] = curr
                continue

            # 不同类型分型，检查距离（至少间隔3根合并K线索引）
            if abs(curr.index - last.index) < 3:
                continue

            # 检查有效性
            if last.type == 'bottom' and curr.type == 'top':
                # 向上笔：顶的高点必须高于底的高点（合理）
                if curr.high > last.high:
                    # 检查如果前面有笔，顶必须高于前一向下笔的底
                    if len(strokes) >= 1:
                        prev_stroke = strokes[-1]
                        if curr.high <= prev_stroke.low:
                            continue
                    selected.append(curr)
                else:
                    continue
            elif last.type == 'top' and curr.type == 'bottom':
                # 向下笔：底的低点必须低于顶的低点（合理）
                if curr.low < last.low:
                    # 检查如果前面有笔，底必须低于前一向上笔的顶
                    if len(strokes) >= 1:
                        prev_stroke = strokes[-1]
                        if curr.low >= prev_stroke.high:
                            continue
                    selected.append(curr)
                else:
                    continue

        # 将选中的分型序列转换为笔
        for i in range(len(selected) - 1):
            f1 = selected[i]
            f2 = selected[i + 1]

            if f1.type == 'bottom' and f2.type == 'top':
                direction = 1  # 向上笔
                high = f2.high
                low = f1.low
            elif f1.type == 'top' and f2.type == 'bottom':
                direction = -1  # 向下笔
                high = f1.high
                low = f2.low
            else:
                continue

            strokes.append(Stroke(
                start=f1,
                end=f2,
                direction=direction,
                high=high,
                low=low,
            ))

        return strokes

    # ==================== 第4步：线段划分 ====================

    def _build_segments(self, strokes: List[Stroke]) -> List[Segment]:
        """
        线段划分
        规则：
        1. 至少由3笔构成
        2. 线段终结：出现反向的显著突破
        3. 向上线段终结条件：出现一笔向下，其低点跌破了前一个向上笔的低点
        4. 向下线段终结条件：出现一笔向上，其高点突破了前一个向下笔的高点
        """
        if len(strokes) < 3:
            if strokes:
                direction = strokes[0].direction
                return [Segment(
                    start_stroke=strokes[0],
                    end_stroke=strokes[-1],
                    direction=direction,
                    strokes=strokes[:],
                )]
            return []

        segments = []
        seg_start_idx = 0

        while seg_start_idx < len(strokes) - 2:
            # 当前线段的起始笔决定方向
            seg_dir = strokes[seg_start_idx].direction
            
            if seg_dir == 1:  # 向上线段
                # 寻找终结：向下笔的低点跌破前一个向下笔的低点
                # 即回调创新低，上涨力度减弱
                down_strokes = [(j + seg_start_idx, s) 
                               for j, s in enumerate(strokes[seg_start_idx:]) 
                               if s.direction == -1]
                
                terminated = False
                for k in range(1, len(down_strokes)):
                    prev_idx, prev_ds = down_strokes[k - 1]
                    curr_idx, curr_ds = down_strokes[k]
                    
                    # 当前向下笔的低点 < 前一个向下笔的低点 → 终结
                    if curr_ds.low < prev_ds.low:
                        # 线段终结于前一个向下笔
                        end_idx = prev_idx
                        if end_idx - seg_start_idx >= 2:  # 至少3笔
                            seg = self._make_segment(strokes[seg_start_idx:end_idx + 1])
                            if seg:
                                segments.append(seg)
                            seg_start_idx = end_idx
                            terminated = True
                            break
                
                if not terminated:
                    # 没有终结，剩余笔归入当前线段
                    remaining = strokes[seg_start_idx:]
                    if len(remaining) >= 3:
                        seg = self._make_segment(remaining)
                        if seg:
                            segments.append(seg)
                    break
                    
            else:  # 向下线段
                # 寻找终结：向上笔的高点突破前一个向上笔的高点
                # 即反弹创新高，下跌力度减弱
                up_strokes = [(j + seg_start_idx, s) 
                             for j, s in enumerate(strokes[seg_start_idx:]) 
                             if s.direction == 1]
                
                terminated = False
                for k in range(1, len(up_strokes)):
                    prev_idx, prev_us = up_strokes[k - 1]
                    curr_idx, curr_us = up_strokes[k]
                    
                    # 当前向上笔的高点 > 前一个向上笔的高点 → 终结
                    if curr_us.high > prev_us.high:
                        end_idx = prev_idx
                        if end_idx - seg_start_idx >= 2:  # 至少3笔
                            seg = self._make_segment(strokes[seg_start_idx:end_idx + 1])
                            if seg:
                                segments.append(seg)
                            seg_start_idx = end_idx
                            terminated = True
                            break
                
                if not terminated:
                    remaining = strokes[seg_start_idx:]
                    if len(remaining) >= 3:
                        seg = self._make_segment(remaining)
                        if seg:
                            segments.append(seg)
                    break

        # 处理最后不足的情况
        if seg_start_idx < len(strokes) and not segments:
            remaining = strokes[seg_start_idx:]
            if len(remaining) >= 3:
                seg = self._make_segment(remaining)
                if seg:
                    segments.append(seg)

        return segments

    def _make_segment(self, strokes: List[Stroke]) -> Optional[Segment]:
        """从一组笔构建线段"""
        if not strokes:
            return None
        direction = strokes[0].direction
        return Segment(
            start_stroke=strokes[0],
            end_stroke=strokes[-1],
            direction=direction,
            strokes=strokes[:],
        )

    # ==================== 第5步：中枢构建 ====================

    def _build_pivots(self, segments: List[Segment]) -> List[Pivot]:
        """
        中枢构建
        规则：
        1. 至少连续3段有价格重叠区间的线段
        2. 中枢区间 [ZD, ZG]：
           - ZG = min(各段高点)（中枢上沿）
           - ZD = max(各段低点)（中枢下沿）
           - 必须 ZG > ZD 才是有效中枢
        3. 后续线段如果与中枢区间有重叠，则归入该中枢
        """
        if len(segments) < 3:
            return []

        pivots = []
        i = 0

        while i < len(segments) - 2:
            # 尝试以第i段为起点构建中枢
            s1, s2, s3 = segments[i], segments[i + 1], segments[i + 2]

            # 计算三段的重叠区间
            zg = min(s1.high, s2.high, s3.high)  # 中枢上沿
            zd = max(s1.low, s2.low, s3.low)      # 中枢下沿

            if zg > zd:  # 有效中枢
                pivot_segments = [s1, s2, s3]
                j = i + 3

                # 尝试扩展中枢
                while j < len(segments):
                    seg = segments[j]
                    # 判断该段是否与中枢有重叠
                    if seg.low < zg and seg.high > zd:
                        pivot_segments.append(seg)
                        j += 1
                    else:
                        break

                pivots.append(Pivot(
                    zg=zg,
                    zd=zd,
                    segments=pivot_segments,
                    level=1,
                ))
                i = j  # 从中枢结束后的下一段继续
            else:
                i += 1

        return pivots

    # ==================== 第6步：走势类型判断 ====================

    def _identify_trends(self, pivots: List[Pivot]) -> List[Trend]:
        """
        走势类型判断
        - 上涨走势：至少2个中枢，且中枢依次上移
        - 下跌走势：至少2个中枢，且中枢依次下移
        - 盘整走势：只有1个中枢
        """
        if not pivots:
            return []

        trends = []
        i = 0

        while i < len(pivots):
            # 尝试识别走势
            if i + 1 < len(pivots):
                # 检查是否有连续上移的中枢
                if pivots[i + 1].zd > pivots[i].zg:
                    # 可能上涨走势
                    trend_pivots = [pivots[i]]
                    j = i + 1
                    while j < len(pivots) and pivots[j].zd > pivots[j - 1].zg:
                        trend_pivots.append(pivots[j])
                        j += 1
                    trends.append(Trend(type='up', pivots=trend_pivots))
                    i = j
                    continue

                elif pivots[i + 1].zg < pivots[i].zd:
                    # 可能下跌走势
                    trend_pivots = [pivots[i]]
                    j = i + 1
                    while j < len(pivots) and pivots[j].zg < pivots[j - 1].zd:
                        trend_pivots.append(pivots[j])
                        j += 1
                    trends.append(Trend(type='down', pivots=trend_pivots))
                    i = j
                    continue

            # 单个中枢 → 盘整
            trends.append(Trend(type='consolidation', pivots=[pivots[i]]))
            i += 1

        return trends


# ===================== 辅助函数 =====================

def calculate_macd(closes: List[float],
                   fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[List[float], List[float], List[float]]:
    """
    计算MACD指标
    返回: (dif_list, dea_list, macd_hist_list)
    MACD柱 = 2 * (DIF - DEA)
    """
    if len(closes) < slow:
        return [], [], []

    # 计算EMA
    def ema(data, period):
        result = [0.0] * len(data)
        k = 2.0 / (period + 1)
        result[0] = data[0]
        for i in range(1, len(data)):
            result[i] = data[i] * k + result[i - 1] * (1 - k)
        return result

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)

    dif = [ema_fast[i] - ema_slow[i] for i in range(len(closes))]
    dea = ema(dif, signal)
    macd_hist = [2 * (dif[i] - dea[i]) for i in range(len(closes))]

    return dif, dea, macd_hist


def calc_macd_area(macd_hist: List[float], start_idx: int, end_idx: int) -> float:
    """
    计算指定区间内MACD柱子的面积（带符号）
    正值面积代表多头力量，负值面积代表空头力量
    """
    area = 0.0
    for i in range(start_idx, min(end_idx + 1, len(macd_hist))):
        area += macd_hist[i]
    return area
