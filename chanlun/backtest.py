"""
缠论回测引擎（V2增强版）
========================
在V1基础上增加：
1. 移动止盈：记录持仓最高价，从最高点回撤X%触发
2. 时间止损：持仓超N天且涨幅<3%，主动卖出
3. 环境感知仓位管理：根据市场环境动态调整参数
4. ETF交易支持：ETF无印花税
5. 分环境统计：按市场环境分别统计收益
"""

import os
import sys
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Tuple
from datetime import datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from chanlun.core import RawKline, ChanLunAnalyzer, calculate_macd
from chanlun.signal import SignalDetector, Signal
from chanlun.market_env import MarketEnvClassifier
from config import (
    INITIAL_CAPITAL, COMMISSION_RATE, STAMP_TAX_RATE,
    MIN_TRADE_UNIT, MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ETF_SYMBOLS, get_stamp_tax_rate, MARKET_INDEX_SYMBOL,
    USE_SLIPPAGE, SLIPPAGE_RATE,
    # V2环境参数
    BULL_MAX_POSITION_RATIO, BULL_MAX_HOLD_COUNT, BULL_STOP_LOSS_PCT,
    BULL_TRAILING_STOP_PCT, BULL_ALLOW_BUY3, BULL_ALLOW_BUY2,
    BULL_ALLOW_BUY1, BULL_MAX_HOLD_DAYS,
    SIDEWAYS_MAX_POSITION_RATIO, SIDEWAYS_MAX_HOLD_COUNT, SIDEWAYS_STOP_LOSS_PCT,
    SIDEWAYS_TRAILING_STOP_PCT, SIDEWAYS_ALLOW_BUY3, SIDEWAYS_ALLOW_BUY2,
    SIDEWAYS_ALLOW_BUY1, SIDEWAYS_MAX_HOLD_DAYS,
    BEAR_MAX_POSITION_RATIO, BEAR_MAX_HOLD_COUNT, BEAR_STOP_LOSS_PCT,
    BEAR_TRAILING_STOP_PCT, BEAR_ALLOW_BUY3, BEAR_ALLOW_BUY2,
    BEAR_ALLOW_BUY1, BEAR_MAX_HOLD_DAYS,
    TIME_STOP_LOSS_DAYS, TIME_STOP_LOSS_MIN_GAIN,
    # V3卖点参数
    SELL1_CLOSE_RATIO,
    # V5-ATR: ATR止损参数
    USE_ATR_STOP, ATR_STOP_MULTIPLIER, ATR_STOP_MAX_PCT, ATR_STOP_MIN_PCT,
    # V5.3 新增参数
    EXTREME_HALT_ENABLED, EXTREME_CRASH_5D, EXTREME_LIMIT_DOWN,
    MAX_POSITION_RATIO,
    V53_TIME_STOP_ENABLED, V53_TIME_STOP_DAYS, V53_TIME_STOP_MIN_GAIN,
    V53_BREAKEVEN_TRIGGER, V53_BREAKEVEN_STOP,
    # V5.3.2 新增：吊灯止损 / ATR相对时间止损 / 波动率平价仓位 / 单票上限
    USE_CHANDELIER_EXIT, CHANDELIER_MULTIPLIER, CHANDELIER_MIN_ACTIVATE,
    V532_TIME_STOP_ATR_RELATIVE, V532_TIME_STOP_ATR_MULT, V532_TIME_STOP_MIN_GAIN_FLOOR,
    USE_VOL_PARITY_SIZING, VOL_PARITY_TARGET_RISK, MAX_SINGLE_POSITION_RATIO,
    # V5.3.3 新增：确认滞后处理（逐日确认制）
    USE_CONFIRMATION_DELAY, CONFIRMATION_VERIFY_BUY, CONFIRMATION_WINDOW_DAYS,
)


@dataclass
class Position:
    """持仓"""
    symbol: str
    name: str
    shares: int
    buy_price: float
    buy_date: str
    buy_signal_type: str = ""
    highest_price: float = 0.0  # 持仓期间最高价（移动止盈用）


@dataclass
class Trade:
    """交易记录"""
    symbol: str
    name: str
    direction: str        # 'buy' or 'sell'
    price: float
    shares: int
    date: str
    signal_type: str = ""
    commission: float = 0.0
    tax: float = 0.0
    pnl: float = 0.0
    market_env: str = ''  # 交易时的市场环境
    hold_days: int = 0    # 持仓天数
    buy_price: float = 0.0  # 【V5.3.1新增】买入价（用于单笔收益率计算）


@dataclass
class BacktestResult:
    """回测结果"""
    symbol: str
    name: str
    initial_capital: float
    final_capital: float
    total_return: float
    annual_return: float
    max_drawdown: float
    sharpe_ratio: float
    win_rate: float
    profit_loss_ratio: float
    trade_count: int
    trades: List[Trade] = field(default_factory=list)
    equity_curve: List[dict] = field(default_factory=list)
    # V2新增：分环境统计
    env_stats: Dict[str, dict] = field(default_factory=dict)


# ==================== V5.3.3 确认滞后处理（逐日确认制） ====================

def _fractal_confirm_date(f, merged) -> Optional[str]:
    """分型确认日 = 右侧合并K线的end_date（分型需右侧K线才成立）"""
    if f.index + 1 < len(merged):
        return merged[f.index + 1].end_date
    return None


def resolve_confirmation_dates(klines, analyzer, signals, env_map=None,
                               window: int = None, verify_buy: bool = None):
    """
    把信号日期修正为“实盘可得确认日”，并剔除幻影信号。

    原理（参考《确认滞后型未来函数_独立审查报告》）：
      - 分型/笔需右侧K线确认，signal.date(笔终点日)当日不可得；
      - 买点：用“逐日截断扫描”取真实首见确认日（窗口内检不出→幻影信号，剔除）；
      - 卖点：用分型确认日（已验证与逐日截断结果高度一致，零额外成本）。

    返回 (new_signals, stats)；stats含 total/dropped/lag
    """
    if window is None:
        window = CONFIRMATION_WINDOW_DAYS
    if verify_buy is None:
        verify_buy = CONFIRMATION_VERIFY_BUY

    merged = analyzer.merged_klines
    strokes = analyzer.strokes

    # 笔端点分型 → 分型确认日
    conf = {}
    for st in strokes:
        for f in (st.start, st.end):
            cd = _fractal_confirm_date(f, merged)
            k = (f.index, f.type, f.date)
            if k not in conf or (cd and (conf[k] is None or cd < conf[k])):
                conf[k] = cd

    dmap = {k.date: i for i, k in enumerate(klines)}
    out, lag_list = [], []
    dropped = 0
    for sg in signals:
        key = None
        for st in strokes:
            if st.end.date == sg.date:
                key = (st.end.index, st.end.type, st.end.date); break
            if st.start.date == sg.date:
                key = (st.start.index, st.start.type, st.start.date); break
        d = conf.get(key) if key else None

        # 买点：逐日截断验证（剔除幻影信号）
        if sg.signal_type.startswith('buy') and verify_buy:
            d0 = dmap.get(sg.date)
            first = None
            if d0 is not None:
                for j in range(d0 + 2, min(d0 + window + 1, len(klines) + 1)):
                    a2 = ChanLunAnalyzer()
                    a2.analyze(klines[:j])
                    det2 = SignalDetector(env_map) if env_map else SignalDetector()
                    hit = any(s2.signal_type == sg.signal_type and s2.date == sg.date
                              for s2 in det2.detect(klines[:j], a2))
                    if hit:
                        first = klines[j - 1].date
                        break
            d = first

        if not d:
            dropped += 1
            continue
        lag = (dmap.get(d, 0) - dmap.get(sg.date, 0))
        lag_list.append(lag)
        out.append(Signal(signal_type=sg.signal_type, date=d, price=sg.price,
                          description=sg.description, pivot=sg.pivot,
                          market_env=(env_map or {}).get(d, 'sideways')))

    return out, {'total': len(signals), 'dropped': dropped, 'lag': lag_list}


def get_env_params(env_type: str) -> dict:
    """根据市场环境获取对应参数"""
    if env_type == 'bull':
        return {
            'max_position_ratio': BULL_MAX_POSITION_RATIO,
            'max_hold_count': BULL_MAX_HOLD_COUNT,
            'stop_loss_pct': BULL_STOP_LOSS_PCT,
            'trailing_stop_pct': BULL_TRAILING_STOP_PCT,
            'allow_buy1': BULL_ALLOW_BUY1,
            'allow_buy2': BULL_ALLOW_BUY2,
            'allow_buy3': BULL_ALLOW_BUY3,
            'max_hold_days': BULL_MAX_HOLD_DAYS,
        }
    elif env_type == 'bear':
        return {
            'max_position_ratio': BEAR_MAX_POSITION_RATIO,
            'max_hold_count': BEAR_MAX_HOLD_COUNT,
            'stop_loss_pct': BEAR_STOP_LOSS_PCT,
            'trailing_stop_pct': BEAR_TRAILING_STOP_PCT,
            'allow_buy1': BEAR_ALLOW_BUY1,
            'allow_buy2': BEAR_ALLOW_BUY2,
            'allow_buy3': BEAR_ALLOW_BUY3,
            'max_hold_days': BEAR_MAX_HOLD_DAYS,
        }
    else:  # sideways
        return {
            'max_position_ratio': SIDEWAYS_MAX_POSITION_RATIO,
            'max_hold_count': SIDEWAYS_MAX_HOLD_COUNT,
            'stop_loss_pct': SIDEWAYS_STOP_LOSS_PCT,
            'trailing_stop_pct': SIDEWAYS_TRAILING_STOP_PCT,
            'allow_buy1': SIDEWAYS_ALLOW_BUY1,
            'allow_buy2': SIDEWAYS_ALLOW_BUY2,
            'allow_buy3': SIDEWAYS_ALLOW_BUY3,
            'max_hold_days': SIDEWAYS_MAX_HOLD_DAYS,
        }


class BacktestEngine:
    """回测引擎（V2增强版）"""

    def __init__(self, use_market_env: bool = False,
                 execution_mode: str = 'T+1_open'):
        # V5优化：新增 execution_mode 执行模式
        #   'T+1_open'（默认）：次日开盘价执行，与V4行为一致
        #   'T_close'：当日收盘价执行（尾盘执行模式）
        if execution_mode not in ('T+1_open', 'T_close'):
            raise ValueError(f"不支持的执行模式: {execution_mode}")
        # 【V5.3.1修复】参数一致性断言：环境仓位上限不得突破全局总仓位上限
        for env_name, env_max in [('上涨市', BULL_MAX_POSITION_RATIO),
                                  ('震荡市', SIDEWAYS_MAX_POSITION_RATIO),
                                  ('下跌市', BEAR_MAX_POSITION_RATIO)]:
            if env_max > MAX_POSITION_RATIO:
                raise ValueError(
                    f"参数矛盾: {env_name}最大仓位{env_max:.0%} > 全局上限{MAX_POSITION_RATIO:.0%}，"
                    f"请修改config.py")
        self.capital = INITIAL_CAPITAL
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.equity_curve: List[dict] = []
        self.use_market_env = use_market_env  # V1=False, V2=True
        self.env_classifier = MarketEnvClassifier() if use_market_env else None
        self.env_map: Dict[str, str] = {}  # {date: env_type}
        self.execution_mode = execution_mode  # V5优化
        # V5.3 新增：极端行情熔断状态
        self._extreme_halt_active = False        # 是否处于熔断状态（暂停开仓）
        self._extreme_halt_date = None            # 熔断触发日期
        self._extreme_halt_duration = 5           # 熔断持续天数
        self._limit_down_pending_sells = []       # 跌停延迟平仓队列 [(symbol, pos, trigger_date)]

    def set_market_env(self, index_df: pd.DataFrame):
        """设置市场环境数据"""
        # 【V5.3.1修复】保存指数数据：极端行情熔断需要用到指数K线（原实现未把指数加入
        # date_kline_map，导致 _check_extreme_halt 中的市场级熔断从未触发——死代码）
        self.index_df = index_df
        if self.env_classifier and index_df is not None:
            self.env_map = self.env_classifier.classify(index_df)
            # 统计各环境交易日数
            env_counts = defaultdict(int)
            for d, e in self.env_map.items():
                env_counts[e] += 1
            print(f"  市场环境分布: 上涨市{env_counts.get('bull', 0)}天, "
                  f"震荡市{env_counts.get('sideways', 0)}天, "
                  f"下跌市{env_counts.get('bear', 0)}天")

    def run(self, stock_data: Dict[str, Tuple[str, pd.DataFrame]],
            signals_override: Dict[str, List] = None) -> List[BacktestResult]:
        """
        运行多股票回测
        signals_override: 【V5.3.1新增】可选。{symbol: [Signal,...]}，
        提供后跳过缠论分析与信号检测，直接使用给定信号（用于蒙特卡洛
        "打乱信号日期"检验——分析只做一次，每次迭代只重跑交易模拟）。
        """
        all_signals = {}
        kline_cache = {}
        # 【V5.3.3】确认制统计（须在信号分析循环前初始化）
        self._conf_total = 0
        self._conf_dropped = 0
        self._conf_lag = []

        for symbol, (name, df) in stock_data.items():
            klines = self._df_to_klines(df)
            kline_cache[symbol] = (klines, name)

            if signals_override is not None:
                # 使用外部预置信号（蒙特卡洛打乱日期场景）
                all_signals[symbol] = signals_override.get(symbol, [])
                continue

            analyzer = ChanLunAnalyzer()
            result = analyzer.analyze(klines)
            
            if self.use_market_env:
                detector = SignalDetector(self.env_map)
            else:
                detector = SignalDetector()  # V1: 无环境过滤
            
            signals = detector.detect(klines, analyzer)
            # 【V5.3.3】确认滞后处理：按实盘可得确认日撮合，剔除幻影信号
            if USE_CONFIRMATION_DELAY and signals:
                signals, cstats = resolve_confirmation_dates(
                    klines, analyzer, signals, self.env_map)
                self._conf_total += cstats['total']
                self._conf_dropped += cstats['dropped']
                self._conf_lag.extend(cstats['lag'])
            all_signals[symbol] = signals
            
            sig_summary = defaultdict(int)
            for s in signals:
                sig_summary[s.signal_type] += 1
            sig_str = ", ".join(f"{k}:{v}" for k, v in sig_summary.items())
            print(f"  [{symbol}] {name}: {len(klines)}根K线, "
                  f"{len(analyzer.strokes)}笔, {len(analyzer.pivots)}中枢, "
                  f"{len(signals)}个信号 ({sig_str})")

        # 构建信号映射
        signal_map = {}
        for symbol, signals in all_signals.items():
            for sig in signals:
                date_key = sig.date
                if date_key not in signal_map:
                    signal_map[date_key] = []
                signal_map[date_key].append((symbol, sig))

        # 获取所有交易日
        all_dates = set()
        for symbol, (klines, name) in kline_cache.items():
            for k in klines:
                all_dates.add(k.date)
        all_dates = sorted(all_dates)

        # 构建日期到K线的映射
        date_kline_map = {}
        for symbol, (klines, name) in kline_cache.items():
            date_kline_map[symbol] = {k.date: k for k in klines}

        # 【V5.3.1修复】把指数K线加入date_kline_map，供极端行情熔断(市场级5日暴跌)使用。
        # 原实现只把指数交给MarketEnvClassifier，_check_extreme_halt里'000300'永远不在映射中，
        # EXTREME_HALT_ENABLED形同虚设。
        if getattr(self, 'index_df', None) is not None and len(self.index_df) > 0:
            index_klines = self._df_to_klines(self.index_df)
            if index_klines:
                date_kline_map[MARKET_INDEX_SYMBOL] = {k.date: k for k in index_klines}

        # V5.3.2：把date_kline_map暂存到self，供_execute_buy计算ATR仓位时使用
        self._dkm = date_kline_map

        # 模拟交易
        self.capital = INITIAL_CAPITAL
        self.positions = {}
        self.trades = []
        self.equity_curve = []
        self._pending_buys = []
        self._pending_sells = []
        # 【P2修复】待执行的止损/止盈卖出队列（T日确认，T+1开盘执行）
        self._pending_stop_sells = []  # [(symbol, pos, price, reason, env)]
        # V5.3重置极端行情熔断状态
        self._extreme_halt_active = False
        self._extreme_halt_date = None
        self._limit_down_pending_sells = []

        for i, today in enumerate(all_dates):
            # 获取当日市场环境
            today_env = self.env_map.get(today, 'sideways') if self.use_market_env else 'sideways'
            env_params = get_env_params(today_env)

            # V5优化：根据 execution_mode 决定止损/止盈的执行时机
            if self.execution_mode == 'T_close':
                # T_close：止损/止盈确认后以当日收盘价立即执行
                self._check_stops(today, date_kline_map, env_params, today_env)
                # 不再调用 _execute_pending_stop_sells，因为已在 _check_stops 内直接执行
            else:
                # T+1_open：原逻辑，T日标记待卖，T+1以开盘价执行
                self._check_stops(today, date_kline_map, env_params, today_env)
                self._execute_pending_stop_sells(today, date_kline_map)

            # V5.3新增：极端行情熔断检查（跌停延迟平仓 + 暴跌熔断）
            self._check_extreme_halt(today, date_kline_map)

            # 3. 执行待执行的卖出订单（卖点信号）
            # V5优化：T_close 模式下，新产生的卖点信号（来自前一日或更早）仍以收盘价执行
            # 但 _execute_pending_sells 默认用开盘价；在 T_close 下需要特殊处理
            if self.execution_mode == 'T_close':
                # T_close：当日发现的卖点信号当日收盘价执行
                # 由于本循环中信号是在步骤6才识别的，此处 pending 只包含昨日遗留的
                # 对 T_close 模式，我们直接在此步骤把 pending 中的卖出以当日收盘价执行
                self._execute_pending_sells_today_close(today, date_kline_map)
            else:
                self._execute_pending_sells(today, date_kline_map)

            # 4. 执行待执行的买入订单
            if self.execution_mode == 'T_close':
                # T_close：把昨日 pending 买入以当日收盘价执行
                self._execute_pending_buys_today_close(today, date_kline_map, env_params, today_env)
            else:
                self._execute_pending_buys(today, date_kline_map, env_params, today_env)

            # 5. 记录权益
            equity = self._calc_equity(today, date_kline_map)
            self.equity_curve.append({
                'date': today,
                'equity': equity,
                'cash': self.capital,
                'positions': len(self.positions),
                'market_env': today_env,
            })

            # 6. 检查新信号
            # V5优化：T_close 模式下直接执行；T+1_open 下放入 pending
            if today in signal_map:
                for symbol, sig in signal_map[today]:
                    if sig.signal_type.startswith('buy'):
                        # V5.3新增：极端行情熔断时禁止开仓
                        if self._extreme_halt_active:
                            continue

                        # 检查环境是否允许该买点
                        if self.use_market_env and not self._is_signal_allowed(sig, env_params):
                            continue

                        # 【P0-Bug3修复】二买/三买支持替代/加仓逻辑
                        if symbol in self.positions:
                            existing_pos = self.positions[symbol]
                            if sig.signal_type == 'buy2' and existing_pos.buy_signal_type == 'buy1':
                                sell_sig = Signal(
                                    signal_type='sell_for_buy2',
                                    date=today,
                                    price=0,
                                    description='二买替换一买',
                                )
                                if self.execution_mode == 'T_close':
                                    # V5优化：T_close 模式下先卖后买均以收盘价立即执行
                                    if symbol in self.positions:
                                        self._execute_sell(symbol, self.positions[symbol],
                                                           date_kline_map[symbol][today].close,
                                                           today, 'sell_for_buy2', today_env)
                                    if len(self.positions) < env_params['max_hold_count']:
                                        self._execute_buy(symbol, sig,
                                                          date_kline_map[symbol][today].close,
                                                          today, env_params, today_env)
                                else:
                                    self._pending_sells.append((symbol, sell_sig))
                                    self._pending_buys.append((symbol, sig))
                            elif sig.signal_type == 'buy3' and existing_pos.buy_signal_type in ('buy1', 'buy2'):
                                sell_sig = Signal(
                                    signal_type='sell_for_buy3',
                                    date=today,
                                    price=0,
                                    description='三买替换低级别买点',
                                )
                                if self.execution_mode == 'T_close':
                                    if symbol in self.positions:
                                        self._execute_sell(symbol, self.positions[symbol],
                                                           date_kline_map[symbol][today].close,
                                                           today, 'sell_for_buy3', today_env)
                                    if len(self.positions) < env_params['max_hold_count']:
                                        self._execute_buy(symbol, sig,
                                                          date_kline_map[symbol][today].close,
                                                          today, env_params, today_env)
                                else:
                                    self._pending_sells.append((symbol, sell_sig))
                                    self._pending_buys.append((symbol, sig))
                            continue

                        max_hold = env_params['max_hold_count']
                        if len(self.positions) < max_hold:
                            if self.execution_mode == 'T_close':
                                # V5优化：T_close 模式当日收盘价直接执行买入
                                self._execute_buy(symbol, sig,
                                                  date_kline_map[symbol][today].close,
                                                  today, env_params, today_env)
                            else:
                                self._pending_buys.append((symbol, sig))
                    elif sig.signal_type.startswith('sell'):
                        if symbol in self.positions:
                            if self.execution_mode == 'T_close':
                                # V5优化：T_close 模式当日收盘价直接执行卖出
                                pos = self.positions[symbol]
                                kline = date_kline_map[symbol][today]
                                if sig.signal_type == 'sell1':
                                    shares_to_sell = int(pos.shares * SELL1_CLOSE_RATIO / MIN_TRADE_UNIT) * MIN_TRADE_UNIT
                                    if shares_to_sell >= MIN_TRADE_UNIT:
                                        self._execute_partial_sell(symbol, pos, shares_to_sell,
                                                                   kline.close, today, 'sell1', today_env)
                                else:
                                    self._execute_sell(symbol, pos, kline.close, today,
                                                       sig.signal_type, today_env)
                            else:
                                self._pending_sells.append((symbol, sig))

        # 清理剩余持仓
        self._liquidate_all(all_dates[-1] if all_dates else "", date_kline_map)

        # 【V5.3.3】确认制统计输出
        if USE_CONFIRMATION_DELAY and getattr(self, '_conf_total', 0):
            import numpy as _np
            lag = _np.array(self._conf_lag) if self._conf_lag else _np.array([0])
            print(f"  [确认制] 信号{self._conf_total}个 → 可用{self._conf_total - self._conf_dropped}个, "
                  f"幻影信号剔除{self._conf_dropped}个({self._conf_dropped / self._conf_total * 100:.1f}%), "
                  f"滞后中位{int(_np.median(lag))}交易日")

        results = self._calc_results(stock_data, all_dates)
        return results

    def _is_signal_allowed(self, sig: Signal, env_params: dict) -> bool:
        """检查信号是否在当前环境下被允许"""
        if sig.signal_type == 'buy1':
            return env_params['allow_buy1']
        elif sig.signal_type == 'buy2':
            return env_params['allow_buy2']
        elif sig.signal_type == 'buy3':
            return env_params['allow_buy3']
        return True

    def _check_stops(self, today: str, date_kline_map: dict,
                     env_params: dict, today_env: str):
        """
        检查止损（含移动止盈+时间止损+保本止损）
        【V4修复】不立即执行卖出，而是标记为待卖出，次日以开盘价执行
        【P1-1修复】增加保本止损：曾盈利5%以上时，止损不低于成本+手续费
        【V5优化】T_close 模式下：直接以当日收盘价执行，不放入 pending
        """
        stop_loss_pct = env_params['stop_loss_pct']
        trailing_stop_pct = env_params['trailing_stop_pct']
        max_hold_days = env_params['max_hold_days']
        is_t_close = (self.execution_mode == 'T_close')

        for symbol, pos in list(self.positions.items()):
            if symbol not in date_kline_map or today not in date_kline_map[symbol]:
                continue

            kline = date_kline_map[symbol][today]

            # 更新持仓最高价
            pos.highest_price = max(pos.highest_price, kline.high)

            # 决定止损触发的辅助函数
            stop_reason = None

            # 【V5.3.2】ATR提前算好（吊灯止损/时间止损自适应共用），数据不足时为None
            atr_val = None
            if USE_ATR_STOP or USE_CHANDELIER_EXIT or V532_TIME_STOP_ATR_RELATIVE:
                atr_val, _ = self._calc_atr_stop(symbol, kline, date_kline_map, today, stop_loss_pct)

            # 1. ATR硬止损（以买入价为基准，吊灯止损外的最终保护）
            if USE_ATR_STOP and atr_val is not None:
                # ATR动态止损价
                atr_stop_price = pos.buy_price - ATR_STOP_MULTIPLIER * atr_val
                # 限制在min~max范围内
                max_stop = pos.buy_price * (1 - ATR_STOP_MIN_PCT)  # 最少止损ATR_STOP_MIN_PCT
                min_stop = pos.buy_price * (1 - ATR_STOP_MAX_PCT)  # 最多止损ATR_STOP_MAX_PCT
                atr_stop_price = max(min(atr_stop_price, max_stop), min_stop)
                if kline.low <= atr_stop_price:
                    stop_reason = 'ATR止损'
            else:
                # ATR数据不足或未启用，回退到固定止损
                if kline.low <= pos.buy_price * (1 - stop_loss_pct):
                    stop_reason = '止损'

            # 【V5.3参数化】保本止损（不受ATR影响，参数来自config）
            if stop_reason is None and pos.highest_price >= pos.buy_price * (1 + V53_BREAKEVEN_TRIGGER):
                breakeven_stop = pos.buy_price * (1 + V53_BREAKEVEN_STOP)
                if kline.low <= breakeven_stop:
                    stop_reason = '保本止损'

            # 2. 移动止盈 → 【V5.3.2】吊灯止损（Chandelier Exit）
            #    出场线 = 最高价 - k×ATR（随波动率自适应）；与原固定%线取较宽松者，防过早离场；
            #    即使吊灯线过松，ATR硬止损(1)仍在买入价下方保护。无ATR数据时回退原固定%逻辑。
            if stop_reason is None and pos.highest_price > pos.buy_price * CHANDELIER_MIN_ACTIVATE:
                trailing_stop_price = pos.highest_price * (1 - trailing_stop_pct)
                exit_label = '移动止盈'
                if USE_CHANDELIER_EXIT and atr_val is not None:
                    chandelier_price = pos.highest_price - CHANDELIER_MULTIPLIER * atr_val
                    trailing_stop_price = min(chandelier_price, trailing_stop_price)  # 取较宽松
                    exit_label = '吊灯止损'
                if kline.low <= trailing_stop_price:
                    stop_reason = exit_label

            # 3. 时间止损（V5.3：所有环境统一生效）
            #    【V5.3.2】盈利阈值ATR相对化：波动大要求更高浮盈，波动小放宽，避免"错杀"
            if stop_reason is None and V53_TIME_STOP_ENABLED:
                try:
                    buy_dt = datetime.strptime(pos.buy_date[:10], '%Y-%m-%d')
                    today_dt = datetime.strptime(today[:10], '%Y-%m-%d')
                    hold_days = (today_dt - buy_dt).days
                    gain = (kline.close - pos.buy_price) / pos.buy_price
                    min_gain = V53_TIME_STOP_MIN_GAIN
                    if V532_TIME_STOP_ATR_RELATIVE and atr_val is not None and pos.buy_price > 0:
                        min_gain = max(V532_TIME_STOP_ATR_MULT * atr_val / pos.buy_price,
                                       V532_TIME_STOP_MIN_GAIN_FLOOR)
                    if hold_days >= V53_TIME_STOP_DAYS and gain < min_gain:
                        stop_reason = '时间止损'
                except:
                    pass

            if stop_reason is None:
                continue

            if is_t_close:
                # V5优化：T_close 模式直接以收盘价执行
                if symbol in self.positions:
                    cur_pos = self.positions[symbol]
                    self._execute_sell(symbol, cur_pos, kline.close, today,
                                       stop_reason, today_env)
            else:
                # T+1_open 模式：放入 pending 次日执行
                self._pending_stop_sells.append(
                    (symbol, pos, stop_reason, today_env)
                )

    def _check_extreme_halt(self, today: str, date_kline_map: dict):
        """
        【V5.3新增】极端行情熔断检查
        1. 市场层面：5日暴跌20%触发熔断，暂停开仓
        2. 个股层面：跌停触发延迟平仓（次日再尝试卖出）
        """
        if not EXTREME_HALT_ENABLED:
            return

        # 1. 检查熔断状态是否过期（熔断持续5个交易日后自动解除）
        if self._extreme_halt_active and self._extreme_halt_date:
            try:
                halt_dt = datetime.strptime(self._extreme_halt_date[:10], '%Y-%m-%d')
                today_dt = datetime.strptime(today[:10], '%Y-%m-%d')
                elapsed = (today_dt - halt_dt).days
                if elapsed > self._extreme_halt_duration:
                    self._extreme_halt_active = False
                    self._extreme_halt_date = None
            except:
                pass

        # 2. 检查市场5日暴跌熔断（使用沪深300指数判断）
        if not self._extreme_halt_active:
            # 查找大盘指数数据
            index_symbol = '000300'
            if index_symbol in date_kline_map and today in date_kline_map[index_symbol]:
                dates_list = sorted(date_kline_map[index_symbol].keys())
                today_idx = dates_list.index(today)
                if today_idx >= 5:
                    # 计算5日跌幅
                    close_today = date_kline_map[index_symbol][today].close
                    close_5d_ago = date_kline_map[index_symbol][dates_list[today_idx - 5]].close
                    if close_5d_ago > 0:
                        change_5d = (close_today - close_5d_ago) / close_5d_ago
                        if change_5d <= EXTREME_CRASH_5D:
                            self._extreme_halt_active = True
                            self._extreme_halt_date = today
                            print(f"  [V5.3熔断] {today}: 5日暴跌{change_5d:.2%}，触发熔断暂停开仓")

        # 3. 检查个股跌停延迟平仓
        for symbol, pos in list(self.positions.items()):
            if symbol not in date_kline_map or today not in date_kline_map[symbol]:
                continue
            kline = date_kline_map[symbol][today]
            # 检测跌停：收盘价接近最低价且跌幅超阈值
            if kline.open > 0:
                day_change = (kline.close - kline.open) / kline.open
                # 简化检测：当日跌幅接近跌停
                if kline.low <= kline.close * 1.001 and day_change <= EXTREME_LIMIT_DOWN:
                    # 跌停时无法卖出，延迟到下一交易日
                    already_pending = any(s == symbol for s, _, _ in self._limit_down_pending_sells)
                    if not already_pending:
                        self._limit_down_pending_sells.append((symbol, pos, today))

        # 4. 处理跌停延迟平仓队列：次日尝试卖出
        remaining = []
        for symbol, pos, trigger_date in self._limit_down_pending_sells:
            if symbol not in self.positions:
                continue  # 已被其他逻辑清掉
            if symbol in date_kline_map and today in date_kline_map[symbol]:
                kline = date_kline_map[symbol][today]
                # 检查今天是否还是跌停
                if kline.open > 0:
                    day_change = (kline.close - kline.open) / kline.open
                    if kline.low <= kline.close * 1.001 and day_change <= EXTREME_LIMIT_DOWN:
                        # 仍然跌停，继续延迟
                        remaining.append((symbol, pos, today))
                        continue
                # 不再跌停，以开盘价卖出
                today_env = self.env_map.get(today, 'sideways') if self.use_market_env else 'sideways'
                self._execute_sell(symbol, pos, kline.open, today,
                                   '跌停延迟平仓', today_env)
            else:
                remaining.append((symbol, pos, trigger_date))
        self._limit_down_pending_sells = remaining

    def _execute_pending_stop_sells(self, today: str, date_kline_map: dict):
        """
        【P2修复】执行待执行的止损/止盈卖出
        T日收盘后确认止损信号 → T+1日开盘价执行
        """
        remaining = []
        for symbol, pos, reason, signal_env in self._pending_stop_sells:
            if symbol not in self.positions:
                continue  # 可能已被其他操作清掉
            if symbol in date_kline_map and today in date_kline_map[symbol]:
                kline = date_kline_map[symbol][today]
                # 以次日开盘价执行
                self._execute_sell(symbol, pos, kline.open, today, reason, signal_env)
            else:
                remaining.append((symbol, pos, reason, signal_env))
        self._pending_stop_sells = remaining

    def _execute_pending_sells_today_close(self, today: str, date_kline_map: dict):
        """
        【V5优化】T_close 模式：执行昨日遗留的待执行卖出订单
        以当日收盘价执行（尾盘执行模式）
        """
        remaining = []
        for symbol, sig in getattr(self, '_pending_sells', []):
            if symbol in self.positions and symbol in date_kline_map:
                if today in date_kline_map[symbol]:
                    kline = date_kline_map[symbol][today]
                    today_env = self.env_map.get(today, 'sideways') if self.use_market_env else 'sideways'
                    pos = self.positions[symbol]
                    price = kline.close  # V5优化：使用收盘价

                    if sig.signal_type == 'sell1':
                        shares_to_sell = int(pos.shares * SELL1_CLOSE_RATIO / MIN_TRADE_UNIT) * MIN_TRADE_UNIT
                        if shares_to_sell >= MIN_TRADE_UNIT:
                            self._execute_partial_sell(symbol, pos, shares_to_sell,
                                                       price, today, 'sell1', today_env)
                        continue
                    elif sig.signal_type in ('sell2', 'sell_for_buy2', 'sell3', 'sell_for_buy3'):
                        self._execute_sell(symbol, pos, price, today, sig.signal_type, today_env)
                        continue
                    else:
                        self._execute_sell(symbol, pos, price, today, sig.signal_type, today_env)
                        continue
            remaining.append((symbol, sig))
        self._pending_sells = remaining

    def _execute_pending_buys_today_close(self, today: str, date_kline_map: dict,
                                           env_params: dict, today_env: str):
        """
        【V5优化】T_close 模式：执行昨日遗留的待执行买入订单
        以当日收盘价执行（尾盘执行模式）
        """
        remaining = []
        for symbol, sig in getattr(self, '_pending_buys', []):
            max_hold = env_params['max_hold_count']
            if len(self.positions) >= max_hold:
                break
            if symbol in self.positions:
                continue
            if symbol in date_kline_map and today in date_kline_map[symbol]:
                kline = date_kline_map[symbol][today]
                self._execute_buy(symbol, sig, kline.close, today, env_params, today_env)
                continue
            remaining.append((symbol, sig))
        self._pending_buys = remaining

    def _calc_atr_stop(self, symbol: str, kline, date_kline_map: dict,
                       today: str, stop_loss_pct: float, direction: str = 'long'):
        """
        【V5优化】基于ATR的动态止损计算（预留，USE_ATR_STOP=True 时启用）
        返回 (atr_stop_price, atr_stop_pct)，若ATR数据不足返回 (None, None)
        """
        if symbol not in date_kline_map:
            return None, None
        dates = sorted(date_kline_map[symbol].keys())
        if today not in dates:
            return None, None
        today_idx = dates.index(today)
        if today_idx < 14:
            return None, None

        atr_values = []
        for i in range(max(0, today_idx - 14), today_idx + 1):
            k = date_kline_map[symbol][dates[i]]
            tr = max(k.high - k.low,
                     abs(k.high - k.close),
                     abs(k.low - k.close))
            atr_values.append(tr)
        if len(atr_values) < 14:
            return None, None
        atr = float(np.mean(atr_values[-14:]))
        return atr, None  # 仅返回ATR值，百分比由调用方结合乘子计算

    def _execute_pending_sells(self, today: str, date_kline_map: dict):
        """
        执行待执行的卖出订单（V4增强）
        卖点优先级：一卖(50%) > 二卖(清仓) > 三卖(清仓)
        卖出价：次日开盘价（信号日的下一交易日）
        新增：sell_for_buy2/sell_for_buy3 替换卖出
        """
        remaining = []
        for symbol, sig in getattr(self, '_pending_sells', []):
            if symbol in self.positions and symbol in date_kline_map:
                if today in date_kline_map[symbol]:
                    kline = date_kline_map[symbol][today]
                    today_env = self.env_map.get(today, 'sideways') if self.use_market_env else 'sideways'
                    pos = self.positions[symbol]
                    
                    if sig.signal_type == 'sell1':
                        # 一卖：卖出指定比例仓位
                        shares_to_sell = int(pos.shares * SELL1_CLOSE_RATIO / MIN_TRADE_UNIT) * MIN_TRADE_UNIT
                        if shares_to_sell >= MIN_TRADE_UNIT:
                            self._execute_partial_sell(symbol, pos, shares_to_sell,
                                                       kline.open, today, 'sell1', today_env)
                        continue
                    elif sig.signal_type in ('sell2', 'sell_for_buy2'):
                        # 二卖 或 二买替换一买：清仓
                        self._execute_sell(symbol, pos, kline.open, today, 
                                          sig.signal_type, today_env)
                        continue
                    elif sig.signal_type in ('sell3', 'sell_for_buy3'):
                        # 三卖 或 三买替换：清仓
                        self._execute_sell(symbol, pos, kline.open, today, 
                                          sig.signal_type, today_env)
                        continue
                    else:
                        # 其他卖点信号：全仓卖出
                        self._execute_sell(symbol, pos, kline.open, today, sig.signal_type, today_env)
                        continue
            remaining.append((symbol, sig))
        self._pending_sells = remaining
    
    def _execute_partial_sell(self, symbol: str, pos: Position, shares_to_sell: int,
                               price: float, date: str, signal_type: str, today_env: str):
        """
        执行部分卖出（V3新增）
        卖出一部分仓位，保留剩余
        """
        revenue = shares_to_sell * price
        commission = max(revenue * COMMISSION_RATE, 5)
        
        # ETF无印花税
        if symbol in ETF_SYMBOLS:
            tax = 0.0
        else:
            tax = revenue * get_stamp_tax_rate(date)

        # 计算这部分的盈亏
        cost_basis = shares_to_sell * pos.buy_price
        pnl = revenue - cost_basis - commission - tax
        self.capital += (revenue - commission - tax)
        
        hold_days = 0
        try:
            buy_dt = datetime.strptime(pos.buy_date[:10], '%Y-%m-%d')
            sell_dt = datetime.strptime(date[:10], '%Y-%m-%d')
            hold_days = (sell_dt - buy_dt).days
        except:
            pass
        
        self.trades.append(Trade(
            symbol=symbol,
            name=pos.name,
            direction='sell',
            price=price,
            shares=shares_to_sell,
            date=date,
            signal_type=signal_type,
            commission=commission,
            tax=tax,
            pnl=pnl,
            market_env=today_env,
            hold_days=hold_days,
            buy_price=pos.buy_price,
        ))
        
        # 更新持仓（减少股数）
        pos.shares -= shares_to_sell
        if pos.shares < MIN_TRADE_UNIT:
            # 剩余不足一手，全部清掉
            del self.positions[symbol]

    def _execute_pending_buys(self, today: str, date_kline_map: dict,
                               env_params: dict, today_env: str):
        """执行待执行的买入订单"""
        remaining = []
        for symbol, sig in getattr(self, '_pending_buys', []):
            max_hold = env_params['max_hold_count']
            if len(self.positions) >= max_hold:
                break
            if symbol in self.positions:
                continue
            if symbol in date_kline_map and today in date_kline_map[symbol]:
                kline = date_kline_map[symbol][today]
                self._execute_buy(symbol, sig, kline.open, today, env_params, today_env)
                continue
            remaining.append((symbol, sig))
        self._pending_buys = remaining

    def _execute_buy(self, symbol: str, sig: Signal, price: float, 
                     date: str, env_params: dict, today_env: str):
        """执行买入"""
        # 【V5.3.1优化】滑点模拟：实际成交价 = 信号价 × (1 + 滑点)
        if USE_SLIPPAGE:
            price = price * (1 + SLIPPAGE_RATE)
        max_ratio = env_params['max_position_ratio']
        # V5.3新增：MAX_POSITION_RATIO 总仓位上限约束
        # 计算当前持仓市值占总资产比例
        total_equity = self._calc_equity_simple()
        current_position_value = sum(
            pos.shares * price for pos in self.positions.values()
        ) if self.positions else 0
        current_ratio = current_position_value / total_equity if total_equity > 0 else 0
        if current_ratio >= MAX_POSITION_RATIO:
            return  # 总仓位已达上限，禁止新开仓
        # 调整可用额度：取 env max_ratio 和 剩余额度的较小值
        remaining_ratio = MAX_POSITION_RATIO - current_ratio
        effective_ratio = min(max_ratio, remaining_ratio)
        # 【V5.3.2】单票上限：单只标的≤MAX_SINGLE_POSITION_RATIO（原逻辑首笔可到50%，防单票黑天鹅）
        effective_ratio = min(effective_ratio, MAX_SINGLE_POSITION_RATIO)
        # 【V5.3.2】波动率平价仓位：单笔目标风险÷实际止损距离，高波动标的自动降仓
        if USE_VOL_PARITY_SIZING:
            dkm = getattr(self, '_dkm', None)
            atr_v = None
            if dkm and symbol in dkm and date in dkm[symbol]:
                atr_v, _ = self._calc_atr_stop(symbol, dkm[symbol][date], dkm, date, 0.0)
            if atr_v and atr_v > 0:
                stop_dist = min(max(ATR_STOP_MULTIPLIER * atr_v / price, ATR_STOP_MIN_PCT),
                                ATR_STOP_MAX_PCT)
                vol_ratio = VOL_PARITY_TARGET_RISK / stop_dist
                effective_ratio = min(effective_ratio, vol_ratio)
        max_amount = total_equity * effective_ratio
        shares = int(max_amount / price / MIN_TRADE_UNIT) * MIN_TRADE_UNIT

        if shares < MIN_TRADE_UNIT:
            return

        cost = shares * price
        commission = max(cost * COMMISSION_RATE, 5)

        # 【V5.3.1修复】循环缩减至资金足够为止（原实现只减一次，极端情况仍可能超资金）
        while cost + commission > self.capital and shares >= 2 * MIN_TRADE_UNIT:
            shares -= MIN_TRADE_UNIT
            cost = shares * price
            commission = max(cost * COMMISSION_RATE, 5)
        if shares < MIN_TRADE_UNIT or cost + commission > self.capital:
            return

        self.capital -= (cost + commission)

        self.positions[symbol] = Position(
            symbol=symbol,
            name=sig.description[:20] or "",
            shares=shares,
            buy_price=price,
            buy_date=date,
            buy_signal_type=sig.signal_type,
            highest_price=price,
        )

        self.trades.append(Trade(
            symbol=symbol,
            name="",
            direction='buy',
            price=price,
            shares=shares,
            date=date,
            signal_type=sig.signal_type,
            commission=commission,
            market_env=today_env,
        ))

    def _execute_sell(self, symbol: str, pos: Position, price: float,
                      date: str, signal_type: str, today_env: str = ''):
        """执行卖出"""
        # 【V5.3.1优化】滑点模拟：实际成交价 = 信号价 × (1 - 滑点)
        if USE_SLIPPAGE:
            price = price * (1 - SLIPPAGE_RATE)
        revenue = pos.shares * price
        commission = max(revenue * COMMISSION_RATE, 5)
        
        # ETF无印花税；股票按日期差异化印花税（2023-08-28起万5）
        if symbol in ETF_SYMBOLS:
            tax = 0.0
        else:
            tax = revenue * get_stamp_tax_rate(date)

        pnl = revenue - pos.shares * pos.buy_price - commission - tax
        self.capital += (revenue - commission - tax)

        # 计算持仓天数
        hold_days = 0
        try:
            buy_dt = datetime.strptime(pos.buy_date[:10], '%Y-%m-%d')
            sell_dt = datetime.strptime(date[:10], '%Y-%m-%d')
            hold_days = (sell_dt - buy_dt).days
        except:
            pass

        self.trades.append(Trade(
            symbol=symbol,
            name=pos.name,
            direction='sell',
            price=price,
            shares=pos.shares,
            date=date,
            signal_type=signal_type,
            commission=commission,
            tax=tax,
            pnl=pnl,
            market_env=today_env or pos.buy_signal_type,
            hold_days=hold_days,
            buy_price=pos.buy_price,
        ))

        if symbol in self.positions:
            del self.positions[symbol]

    def _calc_equity(self, today: str, date_kline_map: dict) -> float:
        """计算总权益"""
        equity = self.capital
        for symbol, pos in self.positions.items():
            if symbol in date_kline_map and today in date_kline_map[symbol]:
                kline = date_kline_map[symbol][today]
                equity += pos.shares * kline.close
            else:
                equity += pos.shares * pos.buy_price
        return equity

    def _calc_equity_simple(self) -> float:
        """V5.3新增：简化权益计算（不含当日K线，用于买入时快速估算）"""
        equity = self.capital
        for symbol, pos in self.positions.items():
            equity += pos.shares * pos.buy_price  # 用买入价近似
        return equity

    def _liquidate_all(self, last_date: str, date_kline_map: dict):
        """清仓（V5优化：使用开盘价而非收盘价，更贴近实盘）"""
        for symbol in list(self.positions.keys()):
            pos = self.positions[symbol]
            if symbol in date_kline_map and last_date in date_kline_map[symbol]:
                kline = date_kline_map[symbol][last_date]
                price = kline.open  # V5优化：实盘更真实
            else:
                price = pos.buy_price
            today_env = self.env_map.get(last_date, 'sideways') if self.use_market_env else 'sideways'
            self._execute_sell(symbol, pos, price, last_date, '清仓', today_env)

    def _calc_results(self, stock_data: dict, all_dates: List[str]) -> List[BacktestResult]:
        """计算回测指标（含分环境统计）"""
        if not self.equity_curve:
            return []

        initial = INITIAL_CAPITAL
        final = self.equity_curve[-1]['equity']
        total_return = (final - initial) / initial

        # 年化
        if len(all_dates) > 1:
            start_dt = datetime.strptime(all_dates[0][:10], '%Y-%m-%d')
            end_dt = datetime.strptime(all_dates[-1][:10], '%Y-%m-%d')
            days = (end_dt - start_dt).days
            if days > 0:
                annual_return = (1 + total_return) ** (365.0 / days) - 1
            else:
                annual_return = 0
        else:
            annual_return = 0

        # 最大回撤
        peak = 0
        max_drawdown = 0
        for point in self.equity_curve:
            equity = point['equity']
            if equity > peak:
                peak = equity
            dd = (peak - equity) / peak if peak > 0 else 0
            if dd > max_drawdown:
                max_drawdown = dd

        # 夏普
        equity_values = [p['equity'] for p in self.equity_curve]
        if len(equity_values) > 1:
            returns = pd.Series(equity_values).pct_change().dropna()
            if len(returns) > 0 and returns.std() > 0:
                rf_daily = 0.03 / 252
                sharpe = (returns.mean() - rf_daily) / returns.std() * np.sqrt(252)
            else:
                sharpe = 0
        else:
            sharpe = 0

        # 胜率和盈亏比
        sell_trades = [t for t in self.trades if t.direction == 'sell' and t.signal_type not in ('清仓',)]
        win_count = sum(1 for t in sell_trades if t.pnl > 0)
        lose_count = sum(1 for t in sell_trades if t.pnl <= 0)
        win_rate = win_count / len(sell_trades) if sell_trades else 0

        avg_win = np.mean([t.pnl for t in sell_trades if t.pnl > 0]) if win_count > 0 else 0
        avg_lose = abs(np.mean([t.pnl for t in sell_trades if t.pnl <= 0])) if lose_count > 0 else 0
        profit_loss_ratio = avg_win / avg_lose if avg_lose > 0 else (float('inf') if avg_win > 0 else 0)

        # 分环境统计
        env_stats = self._calc_env_stats()

        result = BacktestResult(
            symbol="综合",
            name="综合回测",
            initial_capital=initial,
            final_capital=final,
            total_return=total_return,
            annual_return=annual_return,
            max_drawdown=max_drawdown,
            sharpe_ratio=sharpe,
            win_rate=win_rate,
            profit_loss_ratio=profit_loss_ratio,
            trade_count=len([t for t in self.trades if t.direction == 'buy']),
            trades=self.trades[:],
            equity_curve=self.equity_curve[:],
            env_stats=env_stats,
        )

        return [result]

    def _calc_env_stats(self) -> Dict[str, dict]:
        """分市场环境统计"""
        env_stats = {}
        
        for env_type in ['bull', 'sideways', 'bear']:
            env_labels = {'bull': '上涨市', 'bear': '下跌市', 'sideways': '震荡市'}
            label = env_labels[env_type]
            
            # 找出该环境下的卖出交易
            env_sells = [t for t in self.trades 
                        if t.direction == 'sell' and t.market_env == env_type]
            env_buys = [t for t in self.trades
                       if t.direction == 'buy' and t.market_env == env_type]
            
            if not env_sells and not env_buys:
                env_stats[env_type] = {
                    'label': label,
                    'trade_count': 0,
                    'win_count': 0,
                    'win_rate': 0,
                    'total_pnl': 0,
                    'avg_pnl': 0,
                    'buy1_count': 0, 'buy1_win': 0, 'buy1_wr': 0,
                    'buy2_count': 0, 'buy2_win': 0, 'buy2_wr': 0,
                    'buy3_count': 0, 'buy3_win': 0, 'buy3_wr': 0,
                }
                continue

            total_pnl = sum(t.pnl for t in env_sells)
            win_count = sum(1 for t in env_sells if t.pnl > 0)
            trade_count = len(env_sells)
            win_rate = win_count / trade_count if trade_count > 0 else 0

            # 按买点类型统计
            buy_stats = {}
            for bt in ['buy1', 'buy2', 'buy3']:
                bt_sells = [t for t in env_sells if t.signal_type == bt or 
                           any(b.signal_type == bt for b in env_buys if b.symbol == t.symbol)]
                # 简化：按买入信号的买点类型统计
                bt_buys = [b for b in env_buys if b.signal_type == bt]
                bt_count = len(bt_buys)
                
                # 找对应的卖出
                bt_pnls = []
                for b in bt_buys:
                    matching_sells = [s for s in env_sells if s.symbol == b.symbol and s.date > b.date]
                    if matching_sells:
                        bt_pnls.append(matching_sells[0].pnl)
                
                bt_wins = sum(1 for p in bt_pnls if p > 0)
                bt_wr = bt_wins / len(bt_pnls) if bt_pnls else 0
                
                buy_stats[bt] = {'count': bt_count, 'wins': bt_wins, 'wr': bt_wr}

            env_stats[env_type] = {
                'label': label,
                'trade_count': trade_count,
                'win_count': win_count,
                'win_rate': win_rate,
                'total_pnl': total_pnl,
                'avg_pnl': total_pnl / trade_count if trade_count > 0 else 0,
                'buy1_count': buy_stats.get('buy1', {}).get('count', 0),
                'buy1_win': buy_stats.get('buy1', {}).get('wins', 0),
                'buy1_wr': buy_stats.get('buy1', {}).get('wr', 0),
                'buy2_count': buy_stats.get('buy2', {}).get('count', 0),
                'buy2_win': buy_stats.get('buy2', {}).get('wins', 0),
                'buy2_wr': buy_stats.get('buy2', {}).get('wr', 0),
                'buy3_count': buy_stats.get('buy3', {}).get('count', 0),
                'buy3_win': buy_stats.get('buy3', {}).get('wins', 0),
                'buy3_wr': buy_stats.get('buy3', {}).get('wr', 0),
            }

        return env_stats

    def _df_to_klines(self, df: pd.DataFrame) -> List[RawKline]:
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


def fetch_stock_data(symbols: Dict[str, str],
                     start_date: str, end_date: str) -> Dict[str, Tuple[str, pd.DataFrame]]:
    """获取股票数据"""
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from data_fetcher import fetch_all_stocks
    return fetch_all_stocks(symbols, start_date, end_date)
