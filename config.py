"""
缠论量化策略系统 - 全局配置（V3大样本验证版）
扩展标的池至50+只，回测区间2016~2026
"""

# ==================== 回测配置 ====================
INITIAL_CAPITAL = 20000  # 初始资金（元）
COMMISSION_RATE = 0.00025  # 佣金费率（万2.5）
STAMP_TAX_RATE = 0.001  # 印花税（千1，仅卖出，2023-08-27及以前）
STAMP_TAX_RATE_NEW = 0.0005  # 印花税（万5，2023-08-28起减半，仅卖出）
STAMP_TAX_CUT_DATE = "2023-08-28"  # 印花税减半生效日
MIN_TRADE_UNIT = 100  # 最小交易单位（股/份）

# ==================== 交易成本：滑点 ====================
USE_SLIPPAGE = True        # 是否模拟滑点（实盘必然存在，建议保持True）
SLIPPAGE_RATE = 0.001      # 单边滑点0.1%（买入价=信号价×(1+滑点)，卖出价=信号价×(1-滑点)）

# ==================== 执行模式 ====================
# 'T+1_open': 信号当日收盘后生成 → 次日开盘成交（无需盯盘，收盘后跑脚本即可，实盘推荐）
# 'T_close' : 信号当日尾盘扫描 → 当日收盘价成交（需尾盘盯盘/条件单，含理想化成分）
#
# 【执行模式×滑点 交叉验证（2026-09，58只全池V5.3.2配置）】
#   T+1_open 在滑点0.05%/0.1%/0.2%/0.3%下年化 18.12/17.67/17.10/16.40%，
#   T_close  对应 17.03/16.57/16.06/15.16%——全部4档滑点下次日开盘模式稳定
#   优于尾盘模式约1~1.2pp/年，且回撤更低、夏普更高、胜率88% vs 80%。
#   主因：T_close"盘中击穿止损→收盘卖出"对长下影假破位过度敏感（频繁微亏割肉）；
#   买入侧尾盘追强势收盘价次日常回吐。→ 默认 T+1_open
DEFAULT_EXECUTION_MODE = 'T+1_open'

# ==================== 确认滞后处理（V5.3.3 逐日确认制） ====================
# 背景：缠论分型需右侧K线确认、笔端点在出现反向分型前持续被替换，
#       因此 signal.date(笔终点日)当日在算法上不可见，按该日撮合属“确认滞后型未来函数”。
# 【实测影响】58只全池：原口径年化16.79%/夏普1.89 → 逐日确认制年化2.05%/夏普-0.15；
#             294个买点中73个(24.8%)为“幻影信号”(截断扫描下不出现)，已剔除。
# 开启后：信号按“实盘可得确认日”撮合（买点逐日截断验证、卖点用分型确认日）。
# 关闭后：退回原口径（仅用于对照实验，正式评估必须开启）。
USE_CONFIRMATION_DELAY = True     # 逐日确认制（默认开启，消除确认滞后型未来函数）
CONFIRMATION_VERIFY_BUY = True    # 买点用逐日截断验证（剔除幻影信号）；False=仅分型确认日（更快）
CONFIRMATION_WINDOW_DAYS = 20     # 截断验证窗口（交易日），覆盖实测最大滞后19日

# ==================== 指数前置数据（市场环境预热） ====================
INDEX_PRE_START_DAYS = 250  # 指数数据提前于回测起始日的天数（覆盖MA120预热，约120交易日）


def get_stamp_tax_rate(date_str: str) -> float:
    """
    按日期返回印花税率（2023-08-28起由千1减半至万5）
    date_str: 'YYYY-MM-DD' 或 'YYYYMMDD'
    """
    d = str(date_str).replace('-', '')
    if len(d) >= 8:
        d = d[:8]
        if d >= STAMP_TAX_CUT_DATE.replace('-', ''):
            return STAMP_TAX_RATE_NEW
    return STAMP_TAX_RATE

# ==================== 市场环境适配参数 ====================

# 上涨市参数
BULL_MAX_POSITION_RATIO = 0.50  # 与全局 MAX_POSITION_RATIO 一致（原0.60被全局50%压制从未生效，参数矛盾已修复）
BULL_MAX_HOLD_COUNT = 3
BULL_STOP_LOSS_PCT = 0.10
BULL_TRAILING_STOP_PCT = 0.06
BULL_ALLOW_BUY3 = True
BULL_ALLOW_BUY2 = True
BULL_ALLOW_BUY1 = True
BULL_MAX_HOLD_DAYS = 999

# 震荡市参数
SIDEWAYS_MAX_POSITION_RATIO = 0.40
SIDEWAYS_MAX_HOLD_COUNT = 2
SIDEWAYS_STOP_LOSS_PCT = 0.06
SIDEWAYS_TRAILING_STOP_PCT = 0.05  # V5优化：移动止盈5%，小于止损6%，修复止盈>止损倒挂
SIDEWAYS_ALLOW_BUY3 = False
SIDEWAYS_ALLOW_BUY2 = True
SIDEWAYS_ALLOW_BUY1 = True
SIDEWAYS_MAX_HOLD_DAYS = 999

# 下跌市参数
BEAR_MAX_POSITION_RATIO = 0.25
BEAR_MAX_HOLD_COUNT = 1
BEAR_STOP_LOSS_PCT = 0.05
BEAR_TRAILING_STOP_PCT = 0.05
BEAR_ALLOW_BUY3 = False
BEAR_ALLOW_BUY2 = False
BEAR_ALLOW_BUY1 = True
BEAR_MAX_HOLD_DAYS = 5

# 时间止损通用参数
TIME_STOP_LOSS_DAYS = 10
TIME_STOP_LOSS_MIN_GAIN = 0.03

# ==================== 信号过滤参数 ====================
BUY1_MACD_AREA_RATIO = 0.7
BUY1_BEAR_RSI_THRESHOLD = 30
BUY3_VOLUME_RATIO = 1.2
BUY2_FIB_LOW = 0.382
BUY2_FIB_HIGH = 0.618

# ==================== 回测标的（大样本扩展版） ====================

# ETF（无印花税）
BACKTEST_ETFS = {
    # 宽基ETF
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "510050": "上证50ETF",
    "510880": "红利ETF",
    # 行业ETF
    "512010": "医药ETF",
    "512660": "军工ETF",
    "512880": "证券ETF",
    "159869": "游戏ETF",
    "515790": "光伏ETF",
    "518880": "黄金ETF",
    "513100": "纳指ETF",
    "588000": "科创50ETF",
    "159920": "恒生ETF",
    "159632": "消费电子ETF",
    "512480": "半导体ETF",
    "515030": "新能源车ETF",
    "159825": "农业ETF",
    "512200": "房地产ETF",
    "512690": "酒ETF",
    "512800": "银行ETF",
    "515050": "5GETF",
    "159996": "家电ETF",
    "512580": "环保ETF",
    "159928": "消费ETF",
    "512500": "计算机ETF",
    "515220": "煤炭ETF",
    "512400": "有色金属ETF",
    "159766": "旅游ETF",
    "516160": "新能源ETF",
    "512980": "传媒ETF",
    "512170": "医疗ETF",
    "515880": "通信ETF",
}

# 低价股票（股价<30元）
BACKTEST_STOCKS_V2 = {
    # 原有
    "000001": "平安银行",
    "000858": "五粮液",
    "002475": "立讯精密",
    "601318": "中国平安",
    "600036": "招商银行",
    "000333": "美的集团",
    "601012": "隆基绿能",
    "600030": "中信证券",
    "002594": "比亚迪",
    "601899": "紫金矿业",
    # 新增
    "600276": "恒瑞医药",
    "000651": "格力电器",
    "601166": "兴业银行",
    "002714": "牧原股份",
    "600887": "伊利股份",
    "601688": "华泰证券",
    "002304": "洋河股份",
    "000568": "泸州老窖",
    "600585": "海螺水泥",
    "601888": "中国中免",
    "002352": "顺丰控股",
    "600104": "上汽集团",
    "601601": "中国太保",
    "000002": "万科A",
    "600048": "保利发展",
}

# 合并标的池
BACKTEST_STOCKS = {**BACKTEST_ETFS, **BACKTEST_STOCKS_V2}

# 大盘指数（用于市场环境判定）
MARKET_INDEX_SYMBOL = "000300"
MARKET_INDEX_NAME = "沪深300"

# 市场环境允许的买点映射（与 chanlun/backtest.get_env_params 保持一致，供扫描器复用）
ENV_ALLOW_BUY = {
    'bull':     {'buy1': BULL_ALLOW_BUY1,     'buy2': BULL_ALLOW_BUY2,     'buy3': BULL_ALLOW_BUY3},
    'sideways': {'buy1': SIDEWAYS_ALLOW_BUY1, 'buy2': SIDEWAYS_ALLOW_BUY2, 'buy3': SIDEWAYS_ALLOW_BUY3},
    'bear':     {'buy1': BEAR_ALLOW_BUY1,     'buy2': BEAR_ALLOW_BUY2,     'buy3': BEAR_ALLOW_BUY3},
}

# V1版标的（用于对照实验）
BACKTEST_STOCKS_V1 = {
    "000001": "平安银行",
    "000858": "五粮液",
    "600519": "贵州茅台",
    "002475": "立讯精密",
    "300750": "宁德时代",
}

# ==================== 回测区间 ====================
BACKTEST_START_DATE = "20160101"
BACKTEST_END_DATE = "20260828"

# ==================== MACD参数 ====================
MACD_FAST = 12
MACD_SLOW = 26
MACD_SIGNAL = 9

# ==================== 笔的最少K线数 ====================
MIN_BI_KLINE_COUNT = 5

# ==================== 线段最少笔数 ====================
MIN_XD_BI_COUNT = 3

# ==================== 中枢最少线段数 ====================
MIN_ZS_SEGMENT_COUNT = 3

# ==================== 扫描器配置 ====================
SCANNER_MIN_LIST_DAYS = 60
SCANNER_FILTER_ST = True
SCANNER_FILTER_SUSPEND = True
SCANNER_LOOKBACK_DAYS = 750  # 实盘扫描K线回溯天数（约3年）。回测使用全历史(2016起)构建笔/线段/中枢，
                             # 扫描器若只用120日会导致结构不一致、信号对不上，故与回测口径对齐

# ==================== ETF标识 ====================
ETF_SYMBOLS = set(BACKTEST_ETFS.keys())

# ==================== V3优化参数 ====================
BUY3_VOLUME_RATIO_V3 = 0.8
BUY3_VOLUME_RATIO_BULL = 0.7  # V4优化：从0.5提高到0.7，提高三买量能门槛
BUY3_REQUIRE_MACD_GOLDEN = False
BUY3_REQUIRE_DIF_POSITIVE = True
BUY3_BULL_SKIP_MACD = True
BUY3_BEAR_BLOCK = True

SELL1_AREA_RATIO = 1.4
SELL1_CLOSE_RATIO = 0.5
SELL2_LOOKBACK_DAYS = 30
SELL3_ENABLED = True

FACTOR_SCORE_BUY_THRESHOLD = 75
FACTOR_SCORE_WATCH_THRESHOLD = 60
FACTOR_SCORE_SELL_THRESHOLD = 40

FACTOR_WEIGHT_DIVERGENCE = 0.25
FACTOR_WEIGHT_PIVOT_POS = 0.20
FACTOR_WEIGHT_ENV = 0.20
FACTOR_WEIGHT_VOLUME = 0.15
FACTOR_WEIGHT_TREND = 0.10
FACTOR_WEIGHT_FRACTAL = 0.10

# ==================== V3扩展ETF标的池（兼容旧代码） ====================
BACKTEST_ETFS_V3 = {
    "510300": "沪深300ETF",
    "510500": "中证500ETF",
    "159915": "创业板ETF",
    "512010": "医药ETF",
    "512660": "军工ETF",
    "512880": "证券ETF",
    "159869": "游戏ETF",
    "515790": "光伏ETF",
    "518880": "黄金ETF",
    "513100": "纳指ETF",
    "588000": "科创50ETF",
    "159920": "恒生ETF",
    "159632": "消费电子ETF",
    "512480": "半导体ETF",
    "515030": "新能源车ETF",
    "159825": "农业ETF",
    "512200": "房地产ETF",
}

BACKTEST_STOCKS_V3 = {**BACKTEST_ETFS_V3}
ETF_SYMBOLS_V3 = set(BACKTEST_ETFS_V3.keys())

# ==================== V5-ATR: ATR动态止损参数（回测验证启用）====================
USE_ATR_STOP = True  # V5-ATR: 启用ATR动态止损（替代固定止损，年化19.2%→20.55%，卡尔马3.65→3.91）
ATR_STOP_MULTIPLIER = 2.0  # V5-ATR: ATR止损倍数（止损价 = 买入价 - N * ATR）
ATR_STOP_MAX_PCT = 0.08  # V5-ATR: ATR止损最大百分比（不超过8%，参数扫描最优）
ATR_STOP_MIN_PCT = 0.03  # V5-ATR: ATR止损最小百分比（不低于3%）

# ==================== V5.3 新增：极端行情熔断 ====================
EXTREME_HALT_ENABLED = True           # 启用极端行情熔断
EXTREME_CRASH_5D = -0.20              # 5日暴跌20%触发熔断（暂停开仓）
EXTREME_LIMIT_DOWN = -0.095           # 跌停阈值（延迟平仓）

# ==================== V5.3 新增：最大持仓限制 ====================
MAX_POSITION_RATIO = 0.50             # 单账户最大仓位50%（总仓位上限）

# ==================== V5.3 新增：时间止损（全环境） ====================
# V5.3：时间止损在所有市场环境下生效（不再仅限下跌市）
V53_TIME_STOP_ENABLED = True          # 启用全环境时间止损
V53_TIME_STOP_DAYS = 10               # 持仓10天检查
V53_TIME_STOP_MIN_GAIN = 0.03         # 要求涨幅至少3%，否则清仓

# ==================== V5.3 新增：保本止损参数化 ====================
V53_BREAKEVEN_TRIGGER = 0.05          # 最高盈利5%后触发保本
V53_BREAKEVEN_STOP = 0.002            # 保本止损线：回撤到入场价+0.2%

# ==================== 实盘/模拟盘信号一致性 ====================
# 回测中买卖点是否允许由环境参数表控制（BULL/SIDEWAYS/BEAR_ALLOW_BUY*），
# 实盘扫描必须使用同一套过滤，否则扫描信号与回测信号不一致。
# 扫描环境过滤开关（scanner.py / sim_tracker.py 使用）
SCANNER_USE_ENV_FILTER = True

# ==================== V5.3.2 新增：吊灯止损（Chandelier Exit） ====================
# 【实盘回测验证，2026-09】开=年化+3pp、盈亏比3.4→9.2、回撤持平（实盘口径T+1_open+滑点0.1%）
USE_CHANDELIER_EXIT = True     # 吊灯止损替代固定%移动止盈（让利润奔跑）
CHANDELIER_MULTIPLIER = 3.0    # 出场线 = 持仓最高价 - k×ATR（敏感性:2.5~3.5区间稳定，默认3.0）
CHANDELIER_MIN_ACTIVATE = 0.03 # 盈利超过3%后才激活吊灯（与原有移动止盈激活条件衔接）

# ==================== V5.3.2 新增：时间止损ATR相对化 ====================
# 【实盘回测验证】该自适应方案被证伪（放宽阈值→低效持仓滞留，年化-1.5~-2pp），默认关闭，
# 保留固定3%纪律（V53_TIME_STOP_MIN_GAIN=0.03）；如需实验可打开
V532_TIME_STOP_ATR_RELATIVE = False  # 时间止损盈利阈值随波动率自适应（实测负贡献，默认关）
V532_TIME_STOP_ATR_MULT = 0.6        # 阈值 = max(0.6×ATR/买入价, 下限)
V532_TIME_STOP_MIN_GAIN_FLOOR = 0.01 # 阈值下限1%（低波动时也不低于1%）

# ==================== V5.3.2 新增：波动率平价仓位 ====================
# 【实盘回测验证】1.5%档:年化13.1%/回撤3.1%；2%档:年化17.7%/回撤4.6%≈基准收益、回撤减半、
# 盈亏比3.4→5.2、夏普1.90→1.95，均衡性最佳，选为默认。目标风险调小=更保守。
USE_VOL_PARITY_SIZING = True     # 波动率平价仓位：单笔目标风险/止损距离倒算仓位
VOL_PARITY_TARGET_RISK = 0.02    # 单笔目标风险2%权益（1.5%更保守/2.5%更进取）

# ==================== V5.3.2 新增：单标的上限 ====================
# 【实盘回测验证】25%上限在58只池内纯成本(年化-3.5pp、回撤改善有限)：该策略alpha来自
# 主升浪单票重仓，分散反而稀释。保留为可选风控（并入退市股池/扩容标的池时建议开启）
MAX_SINGLE_POSITION_RATIO = 0.5  # 单只标的不超过总权益50%（≈无单独限制，等于全局总仓上限）
