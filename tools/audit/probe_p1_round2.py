# -*- coding: utf-8 -*-
"""P1探测第二轮: 涨停池边界 / 估值历史真伪 / 财务历史深度"""
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
        return requests.get(B + path, params=params, headers=H, timeout=30).json()
    except Exception as e:
        return {'code': 'ERR', 'message': str(e)[:60]}


print('=== 1) 涨停池覆盖边界 (2020~2023) ===')
for d in ['20200102', '20200701', '20210104', '20210701', '20220104', '20220701', '20230103', '20230703']:
    r = get('/api/a-share/special-data/limit-up-pool', {'date_ms': ms(d), 'size': 200})
    pg = (r.get('data') or {}).get('pagination') or {}
    print(f'  {d}: code={r.get("code")} total={pg.get("total")}')
    time.sleep(0.25)

print('\n=== 2) 涨停池最早边界细探 (2020下半年) ===')
for d in ['20201009', '20210401', '20211008']:
    r = get('/api/a-share/special-data/limit-up-pool', {'date_ms': ms(d), 'size': 200})
    pg = (r.get('data') or {}).get('pagination') or {}
    print(f'  {d}: total={pg.get("total")}')
    time.sleep(0.25)

print('\n=== 3) 估值: date参数是否被忽略(对比两次返回) ===')
r1 = get('/api/a-share/valuations/snapshot', {'thscodes': '600519.SH'})
r2 = get('/api/a-share/valuations/snapshot', {'thscodes': '600519.SH', 'date': '2016-06-30'})
d1 = (r1.get('data') or {}).get('item')
d2 = (r2.get('data') or {}).get('item')
print(f'  不带date: {json.dumps(d1, ensure_ascii=False)[:200]}')
print(f'  带2016-06-30: {json.dumps(d2, ensure_ascii=False)[:200]}')
print(f'  → 两次返回{"完全相同(参数被忽略, 无历史估值)" if d1 == d2 else "不同(支持历史?)"}')

print('\n=== 4) 财务历史深度: 利润表/资产负债表/现金流 (2016-2026区间) ===')
for name, path in [('利润表', '/api/a-share/financials/income-statements'),
                   ('资产负债表', '/api/a-share/financials/balance-sheets'),
                   ('现金流量表', '/api/a-share/financials/cashflow-statements')]:
    r = get(path, {'thscode': '600519.SH', 'period': 'annual',
                   'start': ms('20160101'), 'end': ms('20260831')})
    items = (r.get('data') or {}).get('item') or []
    periods = [it.get('period_end_ms') for it in items[:3]]
    if periods:
        fmt = [time.strftime('%Y-%m-%d', time.localtime(p / 1000)) for p in periods]
    else:
        fmt = []
    print(f'  {name}: code={r.get("code")} 期数={len(items)} 最近3期={fmt} {r.get("message","")}')
    time.sleep(0.3)

print('\n=== 5) 财务指标(如有) ===')
for p in ['/api/a-share/financials/indicators', '/api/a-share/financials/metrics']:
    r = get(p, {'thscode': '600519.SH', 'period': 'annual', 'start': ms('20160101'), 'end': ms('20260831')})
    items = (r.get('data') or {}).get('item') or []
    print(f'  {p}: code={r.get("code")} 期数={len(items)} {r.get("message","")}')
    time.sleep(0.2)

print('\n=== 6) 指数成分股(方向A选股域) ===')
for path, params in [('/api/index/constituents', {'thscode': '000300.SH'}),
                     ('/api/index/components', {'thscode': '000300.SH'})]:
    r = get(path, params)
    items = (r.get('data') or {}).get('item') or []
    print(f'  {path}: code={r.get("code")} 数量={len(items)} {r.get("message","")}')
    time.sleep(0.2)
