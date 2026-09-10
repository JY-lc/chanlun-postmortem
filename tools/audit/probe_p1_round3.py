# -*- coding: utf-8 -*-
"""P1探测第三轮: 财务区间/现金流/成分股/指标/指数K线"""
import os, time
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


print('=== 1) 财务区间切片(利润表, 9.99年窗口) ===')
r = get('/api/a-share/financials/income-statements',
        {'thscode': '600519.SH', 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
items = (r.get('data') or {}).get('item') or []
yrs = [time.strftime('%Y', time.localtime(it['period_end_ms'] / 1000)) for it in items]
print(f'  利润表(年报): code={r.get("code")} 期数={len(items)} 年份={yrs}')
r2 = get('/api/a-share/financials/income-statements',
         {'thscode': '600519.SH', 'period': 'quarterly', 'limit': 20})
it2 = (r2.get('data') or {}).get('item') or []
print(f'  利润表(季报,最近20期): 期数={len(it2)}')

print('\n=== 2) 现金流量表(正确路径) ===')
r = get('/api/a-share/financials/cash-flow-statements',
        {'thscode': '600519.SH', 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
items = (r.get('data') or {}).get('item') or []
print(f'  现金流(年报): code={r.get("code")} 期数={len(items)}')

print('\n=== 3) 指数成分股(沪深300) ===')
r = get('/api/a-share-index/constituents/ths-stock-list', {'thscode': '000300.SH'})
items = (r.get('data') or {}).get('item') or []
print(f'  沪深300成分股: code={r.get("code")} 数量={len(items)}')
if items:
    print('   样例:', [it.get('thscode') for it in items[:5]])
r = get('/api/a-share-index/constituents/ths-stock-list', {'thscode': '886042.TI'})
items2 = (r.get('data') or {}).get('item') or []
print(f'  同花顺板块886042.TI成分股: code={r.get("code")} 数量={len(items2)}')

print('\n=== 4) 财务指标(report=2024-4) ===')
r = get('/api/a-share/financials/indicators', {'thscode': '600519.SH', 'report': '2024-4'})
ab = (r.get('data') or {}).get('abilities') or []
print(f'  code={r.get("code")} 指标块数={len(ab)}')
if ab:
    for a in ab[:2]:
        inds = a.get('indicators') or []
        print(f'    {a.get("ability")}: {len(inds)}个指标, 样例={json.dumps(inds[:2], ensure_ascii=False) if False else inds[:2]}')

print('\n=== 5) 指数历史K线(沪深300, 2016-2026切片) ===')
tot = []
for s, e in [('20160101', '20251230'), ('20260101', '20260828')]:
    r = get('/api/a-share-index/prices/historical',
            {'thscode': '000300.SH', 'interval': '1d', 'start': ms(s), 'end': ms(e) + 86399999})
    items = (r.get('data') or {}).get('item') or []
    tot.extend(items)
print(f'  沪深300指数K线: 合计{len(tot)}根 (2016~2026)')

print('\n=== 6) 同花顺指数列表(概念/行业板块) ===')
for tag in ['industry', 'cn_concept']:
    r = get('/api/a-share-index/catalog/ths-index-list', {'tag': tag})
    items = (r.get('data') or {}).get('item') or []
    print(f'  tag={tag}: 数量={len(items)} 样例={[it.get("name") for it in items[:4]]}')
    time.sleep(0.2)
