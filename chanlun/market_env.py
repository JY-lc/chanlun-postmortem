"""
市场环境识别模块
================
根据大盘指数（沪深300/上证指数）判断当前市场环境：
- 上涨市：均线多头排列 + 60日涨幅>10%
- 下跌市：均线空头排列 + 60日跌幅>10%
- 震荡市：均线纠缠 + 涨跌幅不大
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from dataclasses import dataclass


@dataclass
class MarketEnvResult:
    """市场环境判定结果"""
    date: str
    env_type: str  # 'bull', 'bear', 'sideways'
    env_label: str  # '上涨市', '下跌市', '震荡市'
    ma20: float = 0.0
    ma60: float = 0.0
    ma120: float = 0.0
    change_60d: float = 0.0  # 60日涨跌幅
    score: float = 0.0  # 综合评分 -1~1


class MarketEnvClassifier:
    """市场环境分类器"""

    def __init__(self):
        self.env_history: Dict[str, str] = {}  # {date: env_type}

    def classify(self, index_df: pd.DataFrame) -> Dict[str, str]:
        """
        对指数数据逐日判定市场环境
        index_df: 指数日线数据，需含 '日期' 和 '收盘' 列
        返回: {date_str: env_type}  ('bull'/'bear'/'sideways')
        """
        if index_df is None or len(index_df) < 120:
            print("  市场环境判定: 数据不足120日，默认震荡市")
            return {}

        closes = index_df['收盘'].values.astype(float)
        dates = index_df['日期'].values.astype(str)

        # 计算均线
        ma20 = pd.Series(closes).rolling(20).mean().values
        ma60 = pd.Series(closes).rolling(60).mean().values
        ma120 = pd.Series(closes).rolling(120).mean().values

        env_map = {}

        for i in range(120, len(closes)):
            date_str = str(dates[i])[:10]
            m20 = ma20[i]
            m60 = ma60[i]
            m120 = ma120[i]
            cur_close = closes[i]

            # 60日涨跌幅
            if i >= 60 and closes[i - 60] > 0:
                change_60d = (cur_close - closes[i - 60]) / closes[i - 60]
            else:
                change_60d = 0.0

            # 均线排列判定
            if m20 > m60 > m120:
                ma_signal = 1  # 多头排列
            elif m20 < m60 < m120:
                ma_signal = -1  # 空头排列
            else:
                ma_signal = 0  # 纠缠

            # 涨跌幅辅助判定
            if change_60d > 0.10:
                change_signal = 1  # 偏多
            elif change_60d < -0.10:
                change_signal = -1  # 偏空
            else:
                change_signal = 0  # 震荡

            # 综合判定（均线为主，涨跌幅为辅）
            score = ma_signal * 0.6 + change_signal * 0.4

            if score >= 0.5:
                env_type = 'bull'
            elif score <= -0.5:
                env_type = 'bear'
            else:
                env_type = 'sideways'

            env_map[date_str] = env_type

        self.env_history = env_map
        return env_map

    def get_env_on_date(self, date: str) -> str:
        """获取某日的环境类型"""
        return self.env_history.get(date, 'sideways')

    def get_env_label(self, env_type: str) -> str:
        """环境类型转中文标签"""
        labels = {'bull': '上涨市', 'bear': '下跌市', 'sideways': '震荡市'}
        return labels.get(env_type, '震荡市')


def build_index_data_from_closes(dates: List[str], closes: List[float]) -> pd.DataFrame:
    """
    从收盘价列表构建简易指数DataFrame（用于测试）
    """
    return pd.DataFrame({'日期': dates, '收盘': closes})
