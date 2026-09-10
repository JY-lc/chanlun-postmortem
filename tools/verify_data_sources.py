# -*- coding: utf-8 -*-
"""
数据源交叉校验工具 (数据体检)
============================
用法:
  python tools/verify_data_sources.py                 # 校验全部回测池
  python tools/verify_data_sources.py 600519 510300   # 只校验指定标的
  python tools/verify_data_sources.py --etf-source em # ETF用东财(默认em); ths=同花顺(仅近1年)

主源: 新浪(回测在用)   对照: 同花顺官方API(股票全历史) / 东方财富(ETF全历史)
复权口径: 全部使用不复权(原始价), 与回测引擎一致
输出: 控制台摘要 + data_verify_report.csv
"""
import sys, os, time, csv
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_fetcher import fetch_stock_hist as sina_hist
import config

START, END = '20160101', '20260828'
import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ths_auth import get_api_key
THS_KEY = get_api_key()


def ms(ymd):
    return int(time.mktime(time.strptime(ymd + ' 00:00:00', '%Y%m%d %H:%M:%S')) * 1000)


def _to_df(items):
    if not items:
        return None
    df = pd.DataFrame(items)
    df['日期'] = pd.to_datetime(df['date_ms'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai').dt.strftime('%Y-%m-%d')
    df['开盘'] = pd.to_numeric(df['open_price'], errors='coerce')
    df['最高'] = pd.to_numeric(df['high_price'], errors='coerce')
    df['最低'] = pd.to_numeric(df['low_price'], errors='coerce')
    df['收盘'] = pd.to_numeric(df['close_price'], errors='coerce')
    df['成交量'] = pd.to_numeric(df['volume'], errors='coerce')
    df = df.sort_values('日期').drop_duplicates('日期').reset_index(drop=True)
    return df[['日期', '开盘', '最高', '最低', '收盘', '成交量']]


def ths_stock_hist(thscode):
    """同花顺个股历史K线(不复权), 窗口≤10年切片"""
    if not THS_KEY:
        return None
    items = []
    for s, e in [('20160101', '20251231'), ('20260101', END)]:
        try:
            r = requests.get('https://fuyao.aicubes.cn/api/a-share/prices/historical',
                             params={'thscode': thscode, 'interval': '1d',
                                     'start': ms(s), 'end': ms(e) + 86399999, 'adjust': 'none'},
                             headers={'X-api-key': THS_KEY}, timeout=30).json()
        except Exception:
            return None
        if r.get('code') != 0:
            return None
        items.extend((r.get('data') or {}).get('item') or [])
        time.sleep(0.2)
    return _to_df(items)


def em_etf_hist(secid):
    """东财ETF全历史K线(不复权, fqt=0)"""
    try:
        r = requests.get('https://push2his.eastmoney.com/api/qt/stock/kline/get',
                         params={'secid': secid, 'fields1': 'f1,f2,f3,f4,f5,f6',
                                 'fields2': 'f51,f52,f53,f54,f55,f56', 'klt': 101, 'fqt': 0,
                                 'beg': '20160101', 'end': '20260828', 'lmt': 100000},
                         headers={'User-Agent': 'Mozilla/5.0'}, timeout=30).json()
        klines = (r.get('data') or {}).get('klines') or []
        rows = []
        for k in klines:
            p = k.split(',')
            rows.append({'日期': p[0], '开盘': float(p[1]), '收盘': float(p[2]),
                         '最高': float(p[3]), '最低': float(p[4]), '成交量': float(p[5])})
        return pd.DataFrame(rows).sort_values('日期').reset_index(drop=True) if rows else None
    except Exception:
        return None


def compare(symbol, name, ref_df, source_label):
    sdf = sina_hist(symbol, START, END)
    if sdf is None or ref_df is None:
        return {'symbol': symbol, 'name': name, 'source': source_label,
                'status': '数据缺失(S=%s/R=%s)' % (sdf is not None, ref_df is not None)}
    s_dates, r_dates = set(sdf['日期']), set(ref_df['日期'])
    only_s, only_r = s_dates - r_dates, r_dates - s_dates
    common = sorted(s_dates & r_dates)
    sm, rm = sdf.set_index('日期'), ref_df.set_index('日期')
    nd, nv, worst = 0, 0, None
    for d in common:
        for col, tol in [('收盘', 0.001), ('开盘', 0.002), ('最高', 0.002), ('最低', 0.002)]:
            sv, rv = float(sm.loc[d, col]), float(rm.loc[d, col])
            rel = abs(sv - rv) / rv if rv != 0 else (0 if sv == 0 else 9.9)
            if rel > tol:
                nd += 1
                if worst is None or rel > worst[0]:
                    worst = (rel * 100, d, col)
                break
        vv, vt = float(sm.loc[d, '成交量']), float(rm.loc[d, '成交量'])
        if vt > 0 and abs(vv - vt) / vt > 0.05:
            nv += 1
    status = 'OK' if nd == 0 and not only_s and not only_r else '!!差异'
    if worst:
        status += f' (最差{worst[0]:.2f}% {worst[1]} {worst[2]})'
    print(f'  {symbol} {name}: {status} 行{len(sdf)}/{len(ref_df)} 独有S={len(only_s)} R={len(only_r)} OHLC差={nd} 量差={nv}')
    return {'symbol': symbol, 'name': name, 'source': source_label, 'status': status,
            'sina_rows': len(sdf), 'ref_rows': len(ref_df), 'only_sina': len(only_s),
            'only_ref': len(only_r), 'ohlc_diff': nd, 'vol_diff': nv}


def main():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    etf_source = 'em'
    for a in sys.argv[1:]:
        if a.startswith('--etf-source'):
            etf_source = a.split('=')[1] if '=' in a else 'ths'
    pool = config.BACKTEST_STOCKS
    if args:
        pool = {k: pool[k] for k in args if k in pool}
    rows = []
    for symbol, name in pool.items():
        is_etf = symbol.startswith(('51', '15', '56', '58', '159'))
        # 交易所后缀推断：与 data_fetcher 规则一致（北交所→.BJ，沪市→.SH，其余→.SZ）
        if symbol.startswith(('4', '8')) or symbol.startswith('920'):
            thscode = symbol + '.BJ'
        elif symbol.startswith(('5', '6', '9')):
            thscode = symbol + '.SH'
        else:
            thscode = symbol + '.SZ'
        if is_etf:
            if etf_source == 'ths':
                ref, label = ths_stock_hist(thscode), '同花顺(近1年)'
            else:
                secid = ('1.' if symbol.startswith(('5', '6', '9')) else '0.') + symbol
                ref, label = em_etf_hist(secid), '东财(全历史)'
        else:
            ref, label = ths_stock_hist(thscode), '同花顺(全历史)'
        rows.append(compare(symbol, name, ref, label))
        time.sleep(0.15)
    out = 'data_verify_report.csv'
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    bad = [r for r in rows if '!!' in str(r.get('status', ''))]
    print(f'\n完成: {len(rows)}只, 差异 {len(bad)}只, 报告已存 {out}')
    if bad:
        print('需人工检查:', [r['symbol'] for r in bad])


if __name__ == '__main__':
    main()
