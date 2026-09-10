# -*- coding: utf-8 -*-
"""P1探测: 同花顺特色数据/估值 的历史可得性实测"""
import os, time, json
import requests

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ths_auth import get_api_key
KEY = get_api_key()
B = 'https://fuyao.aicubes.cn'
H = {'X-api-key': KEY}


def ms(ymd):
    return int(time.mktime(time.strptime(ymd + ' 00:00:00', '%Y%m%d %H:%M:%S')) * 1000)


def get(path, params):
    try:
        r = requests.get(B + path, params=params, headers=H, timeout=30).json()
        code = r.get('code')
        d = r.get('data') or {}
        n = None
        if isinstance(d.get('item'), list):
            n = len(d['item'])
        elif isinstance(d.get('stock_items'), list):
            n = len(d['stock_items'])
        elif isinstance(d.get('pagination'), dict):
            n = d['pagination'].get('total')
        return code, n, r.get('message', '')
    except Exception as e:
        return 'ERR', None, str(e)[:60]


print('=== 1) 涨停池 历史深度 (date_ms) ===')
for d in ['20160104', '20180601', '20200601', '20230601', '20240603', '20250630', '20260828']:
    code, n, msg = get('/api/a-share/special-data/limit-up-pool', {'date_ms': ms(d), 'size': 200})
    print(f'  {d}: code={code} 条数={n} {msg}')
    time.sleep(0.3)

print('\n=== 2) 龙虎榜 历史深度 (date) ===')
for d in ['2016-06-01', '2019-06-03', '2023-06-01', '2025-06-30', '2025-09-30', '2026-08-28']:
    code, n, msg = get('/api/a-share/special-data/dragon-tiger-list', {'board_type': 'all', 'date': d})
    print(f'  {d}: code={code} 股票数={n} {msg}')
    time.sleep(0.3)

print('\n=== 3) 历史热股榜 (date, 声称最近1年) ===')
for d in ['2025-06-30', '2024-06-03', '2026-08-28']:
    code, n, msg = get('/api/a-share/special-data/hot-stock-list-history', {'date': d})
    print(f'  {d}: code={code} 条数={n} {msg}')
    time.sleep(0.3)

print('\n=== 4) 连板天梯(固定30日) ===')
code, n, msg = get('/api/a-share/special-data/limit-up-ladder', {})
print(f'  code={code} 天数={n} {msg}')

print('\n=== 5) 估值: 是否有历史参数(预期只有最新快照) ===')
for params in [{'thscodes': '600519.SH'}, {'thscodes': '600519.SH', 'date': '2024-06-03'},
               {'thscodes': '600519.SH', 'date_ms': ms('20240603')}]:
    try:
        r = requests.get(B + '/api/a-share/valuations/snapshot', params=params, headers=H, timeout=30).json()
        print(f'  params={list(params.keys())}: code={r.get("code")} {r.get("message","")}')
    except Exception as e:
        print(f'  params={list(params.keys())}: ERR {str(e)[:50]}')
    time.sleep(0.3)

print('\n=== 6) 财务数据 历史深度(利润表, 方向A需要) ===')
for params in [{'thscode': '600519.SH'}, {'thscode': '600519.SH', 'start_date': '2016-01-01', 'end_date': '2026-08-31'}]:
    try:
        r = requests.get(B + '/api/a-share/financials/income', params=params, headers=H, timeout=30).json()
        d = r.get('data') or {}
        n = len(d.get('item') or []) if isinstance(d.get('item'), list) else None
        print(f'  params={list(params.keys())}: code={r.get("code")} 期数={n} {r.get("message","")}')
    except Exception as e:
        print(f'  params={list(params.keys())}: ERR {str(e)[:50]}')
    time.sleep(0.3)
