"""
轻量级股票数据获取模块（V4全市场扫描版）
==================================
使用新浪财经公开API获取A股和ETF日线数据
使用新浪财经+批量行情API获取全市场股票列表
支持2016年起10年+数据获取，支持全市场5000+标的扫描
"""

import requests
import pandas as pd
from typing import Dict, Tuple, Optional, List
from datetime import datetime, timedelta
import time
import json


_INDEX_SINA_MAP = {
    # ============ 指数专用映射（与股票池严格隔离）============
    # 教训：股票与指数存在“同码”问题(如000001=上证指数/平安银行、399xxx与300xxx段重叠等)，
    # 因此指数代码只允许通过 fetch_index_data 解析，绝不允许进入股票/ETF的映射逻辑。
    '000001': 'sh000001',  # 上证指数
    '000016': 'sh000016',  # 上证50
    '000300': 'sh000300',  # 沪深300（策略环境判断用）
    '000905': 'sh000905',  # 中证500
    '000852': 'sh000852',  # 中证1000
    '399001': 'sz399001',  # 深证成指
    '399005': 'sz399005',  # 中小板指（已并入深市主板，保留兼容）
    '399006': 'sz399006',  # 创业板指
}

# 北交所代码段：43xxxx/83xxxx/87xxxx/88xxxx/920xxx（新浪行情不覆盖北交所）
def _is_bse_symbol(symbol: str) -> bool:
    return symbol.startswith(('4', '8')) or symbol.startswith('920')


def _get_sina_symbol(symbol: str) -> str:
    """将股票/ETF代码转换为新浪格式（仅限 A股/ETF，不含指数与北交所）

    代码段规则（扩池前对照本表检查）：
    - 沪市A股    600/601/603/605/688(科创)      -> sh
    - 沪市B股    900                             -> sh
    - 沪市ETF    51xxxx/56xxxx/58xxxx(科创50等)  -> sh
    - 沪市封基   500xxxx                         -> sh
    - 深市A股    000/001/002/003(主板) 300/301(创业) -> sz
    - 深市B股    200                             -> sz
    - 深市ETF    159xxx                          -> sz
    - 深市LOF    16xxxx                          -> sz
    - 深市封基   184xxx                          -> sz
    - 北交所     43/83/87/88/920                 -> 不支持（新浪无北交所行情）
    - 指数代码   （000001/000300/399xxx等）      -> 只能走 fetch_index_data
    """
    if _is_bse_symbol(symbol):
        raise ValueError(f"北交所代码 {symbol} 不受支持：新浪行情不覆盖北交所，且代码段规则与深市冲突")
    if symbol.startswith(('5',)):
        return f"sh{symbol}"      # 沪市ETF/封基
    if symbol.startswith(('1',)):
        return f"sz{symbol}"      # 深市ETF/LOF/封基
    if symbol.startswith(('6', '9')):
        return f"sh{symbol}"      # 沪A股/科创板/沪B股
    if symbol.startswith(('0', '2', '3')):
        return f"sz{symbol}"      # 深A股(主板/创业)/深B股
    raise ValueError(f"无法识别的代码段: {symbol}（扩池前请对照 _get_sina_symbol 规则表检查）")


def fetch_stock_hist(symbol: str, start_date: str, end_date: str,
                     adjust: str = "qfq", _sina_symbol: Optional[str] = None) -> Optional[pd.DataFrame]:
    """
    获取A股/ETF日线数据（新浪财经API）
    支持最长10年+数据
    """
    try:
        sina_symbol = _sina_symbol if _sina_symbol else _get_sina_symbol(symbol)
    except ValueError as e:
        print(f"  跳过 {symbol}: {e}")
        return None
    
    try:
        sd = datetime.strptime(start_date, "%Y%m%d")
        ed = datetime.strptime(end_date, "%Y%m%d")
        days = (ed - sd).days
        datalen = int(days * 1.3) + 200
        datalen = min(datalen, 5000)
    except:
        datalen = 5000
    
    url = 'https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData'
    params = {
        'symbol': sina_symbol,
        'scale': 240,
        'ma': 'no',
        'datalen': datalen,
    }
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://finance.sina.com.cn",
    }
    
    try:
        resp = requests.get(url, params=params, headers=headers, timeout=30)
        if resp.status_code != 200:
            return None
        
        text = resp.text.strip()
        if not text or text == 'null':
            return None
        
        data = json.loads(text)
        if not data:
            return None
        
        rows = []
        for item in data:
            date_str = item['day'][:10]
            date_cmp = date_str.replace('-', '')
            if date_cmp < start_date or date_cmp > end_date:
                continue
            
            rows.append({
                '日期': date_str,
                '开盘': float(item['open']),
                '最高': float(item['high']),
                '最低': float(item['low']),
                '收盘': float(item['close']),
                '成交量': float(item['volume']),
            })
        
        if not rows:
            return None
        
        df = pd.DataFrame(rows)
        df = df.sort_values('日期').reset_index(drop=True)
        
        for col in ['成交额', '振幅', '涨跌幅', '涨跌额', '换手率']:
            if col not in df.columns:
                df[col] = 0
        
        return df
        
    except Exception as e:
        print(f"  获取 {symbol} 数据失败: {e}")
        return None


def fetch_stock_list_eastmoney() -> pd.DataFrame:
    """
    获取全A股+ETF列表（使用新浪财经API）
    
    策略：
    1. 新浪财经 hs_a 节点分页获取全部A股（~5500只，~30秒）
    2. 批量行情API扫描ETF代码段（510000-519999, 588000-589999, 159000-159999）
    3. 合并返回
    
    返回DataFrame包含: 代码, 名称, 最新价, 最高, 涨跌幅 等
    已过滤ST/退市/停牌
    """
    print("  [1/3] 获取A股列表（新浪财经分页接口）...")
    a_shares = _fetch_a_share_list()
    print(f"    A股: {len(a_shares)}只")
    
    print("  [2/3] 扫描ETF代码段（批量行情接口）...")
    etfs = _fetch_etf_list()
    print(f"    ETF: {len(etfs)}只")
    
    print("  [3/3] 合并与过滤...")
    # 合并
    all_df = pd.concat([a_shares, etfs], ignore_index=True)
    
    # 过滤ST、退市
    all_df = all_df[~all_df['名称'].str.contains('ST|退市', na=False)]
    
    # 过滤停牌（最新价=0）
    all_df = all_df[all_df['最新价'] > 0]
    
    print(f"  获取完成: 共{len(all_df)}只标的（已过滤ST/退市/停牌）")
    return all_df.reset_index(drop=True)


def _fetch_a_share_list() -> pd.DataFrame:
    """通过新浪财经分页接口获取全部A股列表"""
    url = 'https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/Market_Center.getHQNodeData'
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn',
    }
    
    all_rows = []
    
    for page in range(1, 80):  # 最多80页，实际约56页
        params = {
            'page': page,
            'num': 100,
            'sort': 'symbol',
            'asc': 1,
            'node': 'hs_a',
            '_s_r_a': 'page',
        }
        
        try:
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code != 200:
                break
            
            data = json.loads(resp.text)
            if not data:
                break
            
            for item in data:
                code = item.get('code', '')
                name = item.get('name', '')
                price = item.get('trade', '0')
                high = item.get('high', '0')
                low = item.get('low', '0')
                open_price = item.get('open', '0')
                prev_close = item.get('settlement', '0')
                change_pct = item.get('changepercent', '0')
                volume = item.get('volume', '0')
                amount = item.get('amount', '0')
                
                try:
                    price = float(price) if price else 0
                    high = float(high) if high else 0
                    low = float(low) if low else 0
                    open_price = float(open_price) if open_price else 0
                    prev_close = float(prev_close) if prev_close else 0
                    change_pct = float(change_pct) if change_pct else 0
                    volume = float(volume) if volume else 0
                    amount = float(amount) if amount else 0
                except (ValueError, TypeError):
                    price, high, low, open_price, prev_close = 0, 0, 0, 0, 0
                    change_pct, volume, amount = 0, 0, 0
                
                all_rows.append({
                    '代码': code,
                    '名称': name,
                    '最新价': price,
                    '最高': high,
                    '最低': low,
                    '今开': open_price,
                    '昨收': prev_close,
                    '涨跌幅': change_pct,
                    '成交量': volume,
                    '成交额': amount,
                    '振幅': 0,
                    '市场': 0,
                })
            
            if page % 10 == 0:
                print(f"    已获取 {len(all_rows)} 只A股...")
            
            time.sleep(0.1)
            
        except Exception as e:
            print(f"    第{page}页异常: {e}")
            break
    
    return pd.DataFrame(all_rows)


def _fetch_etf_list() -> pd.DataFrame:
    """通过批量行情API扫描ETF代码段"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Referer': 'https://finance.sina.com.cn',
    }
    
    # ETF代码段
    etf_ranges = [
        # (起始, 结束, 前缀) 上海ETF
        (510000, 519999, 'sh'),
        (588000, 589999, 'sh'),
        # 深圳ETF
        (159000, 159999, 'sz'),
    ]
    
    all_rows = []
    
    for start_code, end_code, prefix in etf_ranges:
        codes = [str(i) for i in range(start_code, end_code + 1)]
        
        # 每批80个代码
        for batch_start in range(0, len(codes), 80):
            batch = codes[batch_start:batch_start + 80]
            symbols = ','.join([f'{prefix}{c}' for c in batch])
            
            try:
                url = f'https://hq.sinajs.cn/list={symbols}'
                resp = requests.get(url, headers=headers, timeout=10)
                
                for line in resp.text.strip().split('\n'):
                    if '=""' in line:
                        continue
                    if '="' not in line:
                        continue
                    
                    code_part = line.split('=')[0].replace('var hq_str_', '')
                    data_str = line.split('"')[1]
                    if not data_str:
                        continue
                    
                    data = data_str.split(',')
                    if len(data) < 5 or not data[0]:
                        continue
                    
                    name = data[0]
                    try:
                        price = float(data[3]) if data[3] else 0
                        high = float(data[4]) if data[4] else 0
                    except (ValueError, IndexError):
                        continue
                    
                    if price <= 0:
                        continue
                    
                    code = code_part[2:]  # 去掉sh/sz前缀
                    
                    all_rows.append({
                        '代码': code,
                        '名称': name,
                        '最新价': price,
                        '最高': high,
                        '最低': 0,
                        '今开': 0,
                        '昨收': 0,
                        '涨跌幅': 0,
                        '成交量': 0,
                        '成交额': 0,
                        '振幅': 0,
                        '市场': 1 if prefix == 'sh' else 0,
                    })
                
            except Exception:
                pass
            
            time.sleep(0.05)
    
    return pd.DataFrame(all_rows)


def fetch_stock_hist_batch(symbols: List[str], days_back: int = 120,
                           progress_interval: int = 50) -> Dict[str, pd.DataFrame]:
    """
    批量获取多只股票的历史K线数据
    使用新浪财经API，带速率控制
    
    参数:
        symbols: 股票代码列表
        days_back: 获取最近多少天的数据
        progress_interval: 每隔多少只打印一次进度
    
    返回:
        {symbol: DataFrame} 字典，只包含获取成功的
    """
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=days_back)).strftime('%Y%m%d')
    
    result = {}
    total = len(symbols)
    failed = 0
    request_count = 0
    
    print(f"  批量获取K线: {total}只标的, 区间{start_date}~{end_date}")
    
    for idx, symbol in enumerate(symbols):
        if (idx + 1) % progress_interval == 0 or idx == 0:
            print(f"    [{idx+1}/{total}] 已获取{len(result)}成功, {failed}失败...")
        
        df = fetch_stock_hist(symbol, start_date, end_date)
        
        if df is not None and len(df) > 0:
            result[symbol] = df
        else:
            failed += 1
        
        request_count += 1
        # 每5个请求间隔0.3秒（速率控制）
        if request_count % 5 == 0:
            time.sleep(0.3)
        else:
            time.sleep(0.05)
    
    print(f"  批量获取完成: {len(result)}成功, {failed}失败, 共{total}只")
    return result


def fetch_all_stocks(symbols: Dict[str, str],
                     start_date: str, end_date: str) -> Dict[str, Tuple[str, pd.DataFrame]]:
    """
    批量获取股票/ETF数据
    symbols: {code: name}
    返回: {code: (name, dataframe)}
    """
    result = {}
    total = len(symbols)
    for idx, (symbol, name) in enumerate(symbols.items()):
        print(f"  [{idx+1}/{total}] 获取 {symbol} {name} ...")
        df = fetch_stock_hist(symbol, start_date, end_date)
        if df is not None and len(df) > 0:
            result[symbol] = (name, df)
            print(f"    成功: {len(df)}条 ({df['日期'].iloc[0]} ~ {df['日期'].iloc[-1]})")
        else:
            print(f"    失败/无数据，跳过")
        time.sleep(0.5)
    
    return result


def fetch_index_data(symbol: str, start_date: str, end_date: str) -> Optional[pd.DataFrame]:
    """获取指数日线数据（指数代码专用，与股票池隔离，避免同码冲突）"""
    if symbol not in _INDEX_SINA_MAP:
        print(f"  未知指数代码: {symbol}（支持: {sorted(_INDEX_SINA_MAP)}）")
        return None
    return fetch_stock_hist(symbol, start_date, end_date, _sina_symbol=_INDEX_SINA_MAP[symbol])


if __name__ == "__main__":
    print("测试: 获取全市场列表...")
    df = fetch_stock_list_eastmoney()
    print(f"结果: {len(df)}只标的")
    if not df.empty:
        print(df.head(10))
