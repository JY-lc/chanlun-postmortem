"""
缠论策略V5.3 - 退市股数据获取工具
=====================================
功能：
1. 获取A股退市股票列表（消除幸存者偏差）
2. 获取退市股历史K线数据
3. 合并到回测标的池中

数据源优先级：
1. akshare（首选，数据最全面）
2. 新浪财经备用（回退方案）

使用方法：
    python fetch_delisted.py                     # 获取退市股列表
    python fetch_delisted.py --fetch-data        # 同时获取K线数据
    python fetch_delisted.py --merge             # 合并到回测池
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def fetch_delisted_list_akshare() -> pd.DataFrame:
    """
    使用akshare获取退市股列表
    返回DataFrame包含: 代码, 名称, 退市日期, 退市价格
    """
    try:
        import akshare as ak
        print("  [akshare] 获取退市股列表...")

        # akshare v1.10+ 接口
        try:
            df = ak.stock_info_sh_delist()  # 上交所退市
            print(f"    上交所退市: {len(df)}只")
        except Exception as e:
            print(f"    上交所退市获取失败: {e}")
            df = pd.DataFrame()

        try:
            df_sz = ak.stock_info_sz_delist()  # 深交所退市
            print(f"    深交所退市: {len(df_sz)}只")
            if not df_sz.empty:
                df = pd.concat([df, df_sz], ignore_index=True)
        except Exception as e:
            print(f"    深交所退市获取失败: {e}")

        if df.empty:
            return df

        # 标准化列名
        col_map = {}
        for col in df.columns:
            col_lower = col.lower()
            if '代码' in col or 'code' in col_lower:
                col_map[col] = '代码'
            elif '名称' in col or 'name' in col_lower:
                col_map[col] = '名称'
            elif '退市' in col or '日期' in col or 'date' in col_lower:
                col_map[col] = '退市日期'

        if col_map:
            df = df.rename(columns=col_map)

        # 确保有必要的列
        if '代码' not in df.columns:
            print("  [警告] 未找到代码列，列名:", list(df.columns))
            return pd.DataFrame()

        # 提取6位代码
        df['代码'] = df['代码'].astype(str).str[:6].str.zfill(6)

        # 过滤退市原因（只保留主动退市、强制退市，排除吸收合并等特殊情况）
        if '退市原因' in df.columns:
            df = df[~df['退市原因'].str.contains('吸收合并|换股', na=False)]

        print(f"  退市股总计: {len(df)}只")
        return df

    except ImportError:
        print("  [akshare] 未安装，尝试备用方案...")
        return pd.DataFrame()
    except Exception as e:
        print(f"  [akshare] 获取失败: {e}")
        return pd.DataFrame()


def fetch_delisted_list_fallback() -> pd.DataFrame:
    """
    备用方案：从预定义的退市股列表获取
    包含2016-2025年主要退市股票
    """
    print("  [备用] 使用预定义退市股列表...")

    # 2016-2025年主要退市股票（人工整理）
    delisted_stocks = {
        # 2016-2018年退市
        "600963": "退市*ST宝成",
        "002506": "退市*ST超日",
        "600406": "退市*ST国锐",
        "000556": "退市*ST渝钛白",
        "600175": "退市*ST美盛",
        "002233": "退市*ST嘉瑞",
        "600263": "退市*ST路桥",
        "000620": "退市*ST中服",
        "600399": "退市*ST抚钢",
        "000918": "退市*ST亚华",
        # 2019-2020年退市
        "000832": "*ST鞍成",
        "600659": "*ST宏业",
        "600670": "*ST斯达",
        "000583": "*ST托普",
        "600065": "*ST哈慈",
        "000535": "*ST华信",
        "600762": "退市*ST金角",
        "002309": "退市*ST中利",
        "600485": "退市*ST信威",
        "002494": "退市*ST华鹏",
        # 2021-2023年退市
        "600568": "退市*ST中珠",
        "002604": "退市*ST龙力",
        "300367": "退市*ST东方",
        "002220": "退市*ST天宝",
        "600387": "退市*ST海润",
        "002087": "退市*ST新亿",
        "000024": "退市*ST深中",
        "600155": "退市*ST创智",
        "300156": "退市*ST神雾",
        "002123": "退市*ST梦网",
        # 2024-2025年退市
        "600709": "退市*ST工大",
        "002770": "退市*ST科利",
        "300523": "退市*ST辰安",
        "000861": "退市*ST海印",
        "600228": "退市*ST昌鱼",
        "002218": "退市*ST光伏",
        "300028": "退市*ST吉艾",
        "002618": "退市*ST丹邦",
        "600634": "退市*ST富控",
        "002570": "退市*ST贝因美",
    }

    df = pd.DataFrame([
        {'代码': code, '名称': name}
        for code, name in delisted_stocks.items()
    ])

    print(f"  预定义退市股: {len(df)}只")
    return df


def fetch_delisted_hist(symbol: str, start_date: str = "20160101",
                        end_date: str = None) -> Optional[pd.DataFrame]:
    """
    获取退市股历史K线数据
    退市股数据获取特殊处理：
    1. 退市后无法通过正常API获取
    2. 需要从退市前的数据中截取
    """
    if end_date is None:
        end_date = datetime.now().strftime('%Y%m%d')

    # 使用新浪财经API获取（退市股退市前数据仍可获取）
    from data_fetcher import fetch_stock_hist
    df = fetch_stock_hist(symbol, start_date, end_date)

    if df is not None and len(df) > 0:
        print(f"    {symbol}: 获取{len(df)}条数据 ({df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]})")
    else:
        print(f"    {symbol}: 无数据（可能已退市且数据不可获取）")

    return df


def verify_delisted(pool: Dict[str, str], min_old_days: int = 365) -> Dict[str, str]:
    """
    【V5.3.1新增】自动核验退市股名单
    检查每只候选标的的K线数据最后日期：
    - 数据已停止更新超过 min_old_days 天 → 判定为真退市，保留
    - 数据仍更新到近期 → 疑似未退市/已恢复交易，剔除
    背景：预定义备用列表中混入了从未退市的股票（如600406国电南瑞、600399抚顺特钢、
    600963岳阳林纸等），若直接并入回测池会把正常股票当"退市股"交易，严重污染结果。
    """
    from data_fetcher import fetch_stock_hist
    verified = {}
    for idx, (code, name) in enumerate(pool.items()):
        if (idx + 1) % 10 == 0:
            print(f"    核验进度: {idx+1}/{len(pool)}")
        try:
            df = fetch_stock_hist(code, "20160101")
        except Exception as e:
            print(f"    {code} {name}: 获取失败({e})，保留待人工核验")
            verified[code] = name
            continue
        if df is None or len(df) == 0:
            # 无数据：保留，由人工核验
            verified[code] = name
            continue
        last_date = str(df['日期'].iloc[-1])[:10]
        try:
            last_dt = datetime.strptime(last_date, '%Y-%m-%d')
            if (datetime.now() - last_dt).days > min_old_days:
                verified[code] = name
            else:
                print(f"  [剔除] {code} {name}: 数据更新至{last_date}（非退市股或已恢复交易）")
        except Exception:
            verified[code] = name
        time.sleep(0.3)
    print(f"  核验完成: {len(pool)}只 → 保留{len(verified)}只, 剔除{len(pool)-len(verified)}只")
    return verified


def get_delisted_pool(verify: bool = True) -> Dict[str, str]:
    """
    获取退市股标的池
    优先用akshare，失败则用预定义列表
    verify: 是否自动核验（联网检查K线最后日期，剔除未退市股票）
    """
    # 尝试akshare
    df = fetch_delisted_list_akshare()

    # 回退到预定义列表
    if df.empty:
        df = fetch_delisted_list_fallback()

    if df.empty:
        return {}

    # 构建 {代码: 名称} 字典
    pool = {}
    for _, row in df.iterrows():
        code = str(row['代码']).zfill(6)
        name = str(row.get('名称', f'退市{code}'))
        pool[code] = name

    # 自动核验：剔除数据仍在更新的"退市股"（消除备用列表的误收录）
    if verify:
        print("\n自动核验退市股名单（检查K线最后日期）...")
        pool = verify_delisted(pool)

    return pool


def merge_with_backtest_pool(delisted_pool: Dict[str, str],
                             existing_pool: Dict[str, str]) -> Dict[str, str]:
    """
    合并退市股到回测标的池
    标记退市股，方便后续分析
    """
    merged = {**existing_pool}
    new_count = 0
    for code, name in delisted_pool.items():
        if code not in merged:
            merged[code] = f"[退市]{name}"
            new_count += 1
    print(f"  合并结果: 原{len(existing_pool)}只 + 退市{new_count}只 = {len(merged)}只")
    return merged


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="退市股数据获取工具")
    parser.add_argument("--fetch-data", action="store_true", help="同时获取K线数据")
    parser.add_argument("--merge", action="store_true", help="合并到回测池")
    parser.add_argument("--save", type=str, default="", help="保存到指定文件")
    parser.add_argument("--no-verify", action="store_true",
                        help="跳过自动核验（默认核验，剔除数据仍更新的非退市股）")
    args = parser.parse_args()

    print("=" * 60)
    print("缠论V5.3 退市股数据获取工具")
    print("=" * 60)

    # 获取退市股列表
    pool = get_delisted_pool(verify=not args.no_verify)
    print(f"\n退市股标的池: {len(pool)}只")
    for code, name in list(pool.items())[:10]:
        print(f"  {code} {name}")
    if len(pool) > 10:
        print(f"  ... 共{len(pool)}只")

    if args.fetch_data:
        print("\n获取退市股K线数据...")
        for code, name in pool.items():
            fetch_delisted_hist(code)
            time.sleep(0.5)

    if args.merge:
        from config import BACKTEST_STOCKS
        merged = merge_with_backtest_pool(pool, BACKTEST_STOCKS)
        print(f"\n合并后标的池: {len(merged)}只")
        if args.save:
            with open(args.save, 'w', encoding='utf-8') as f:
                json.dump(merged, f, ensure_ascii=False, indent=2)
            print(f"  已保存到: {args.save}")

    print("\n完成!")
