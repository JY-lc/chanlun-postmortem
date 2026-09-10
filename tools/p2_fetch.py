# -*- coding: utf-8 -*-
"""
P2 数据管道: 沪深300成分股 + 全历史日K + 财务(三表)
用法:
  python p2_fetch.py members              # 拉成分股清单
  python p2_fetch.py prices <start> <cnt> # 分批拉日K(每只2切片)
  python p2_fetch.py financials <start> <cnt>  # 分批拉利润表+资产负债表
  python p2_fetch.py status               # 查看进度
"""
import os, sys, json, time, pickle
import requests

BASE = 'https://fuyao.aicubes.cn'
CACHE = 'data_cache'
os.makedirs(CACHE, exist_ok=True)
MEMBERS = os.path.join(CACHE, 'hs300_members.pkl')
PRICES = os.path.join(CACHE, 'hs300_prices.pkl')
FIN = os.path.join(CACHE, 'hs300_financials.pkl')

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ths_auth import get_api_key
KEY = get_api_key()
H = {'X-api-key': KEY}


def ms(ymd):
    return int(time.mktime(time.strptime(ymd + ' 00:00:00', '%Y%m%d %H:%M:%S')) * 1000)


def get(path, params, retries=3):
    for i in range(retries):
        try:
            r = requests.get(BASE + path, params=params, headers=H, timeout=30).json()
            if r.get('code') == 0:
                return r.get('data')
            if r.get('code') in (4001, 5001, 5002, 5003):
                time.sleep(1.5 * (i + 1)); continue
            return {'__err': r.get('code'), '__msg': r.get('message')}
        except Exception as e:
            time.sleep(1.2 * (i + 1))
    return {'__err': 'net'}


def stage_members():
    d = get('/api/a-share-index/constituents/ths-stock-list', {'thscode': '000300.SH'})
    items = (d or {}).get('item') or []
    members = [{'thscode': it['thscode'], 'ticker': it['ticker'], 'name': it['name']} for it in items]
    pickle.dump(members, open(MEMBERS, 'wb'))
    print(f'成分股 {len(members)} 只已保存')


def stage_prices(start, cnt):
    members = pickle.load(open(MEMBERS, 'rb'))
    data = pickle.load(open(PRICES, 'rb')) if os.path.exists(PRICES) else {}
    batch = members[start:start + cnt]
    t0 = time.time()
    for m in batch:
        tc = m['thscode']
        if tc in data:
            continue
        rows = []
        for s, e in [('20160101', '20251230'), ('20251231', '20260828')]:
            d = get('/api/a-share/prices/historical',
                    {'thscode': tc, 'interval': '1d', 'start': ms(s), 'end': ms(e) + 86399999, 'adjust': 'forward'})
            if d:
                rows.extend(d.get('item') or [])
            time.sleep(0.25)
        data[tc] = rows
        time.sleep(0.15)
    pickle.dump(data, open(PRICES, 'wb'))
    print(f'价格: 本批{len(batch)}只, 累计{len(data)}/{len(members)}, 耗时{time.time()-t0:.0f}s')


def stage_financials(start, cnt):
    members = pickle.load(open(MEMBERS, 'rb'))
    data = pickle.load(open(FIN, 'rb')) if os.path.exists(FIN) else {}
    batch = members[start:start + cnt]
    t0 = time.time()
    for m in batch:
        tc = m['thscode']
        if tc in data:
            continue
        inc = get('/api/a-share/financials/income-statements',
                  {'thscode': tc, 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
        time.sleep(0.25)
        bal = get('/api/a-share/financials/balance-sheets',
                  {'thscode': tc, 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
        time.sleep(0.25)
        data[tc] = {'income': (inc or {}).get('item') if isinstance(inc, dict) else [],
                    'balance': (bal or {}).get('item') if isinstance(bal, dict) else []}
    pickle.dump(data, open(FIN, 'wb'))
    print(f'财务: 本批{len(batch)}只, 累计{len(data)}/{len(members)}, 耗时{time.time()-t0:.0f}s')


def stage_status():
    n = len(pickle.load(open(MEMBERS, 'rb'))) if os.path.exists(MEMBERS) else 0
    p = len(pickle.load(open(PRICES, 'rb'))) if os.path.exists(PRICES) else 0
    f = len(pickle.load(open(FIN, 'rb'))) if os.path.exists(FIN) else 0
    print(f'成分股{n} / 日K{p} / 财务{f}')


if __name__ == '__main__':
    cmd = sys.argv[1]
    if cmd == 'members':
        stage_members()
    elif cmd == 'prices':
        stage_prices(int(sys.argv[2]), int(sys.argv[3]))
    elif cmd == 'financials':
        stage_financials(int(sys.argv[2]), int(sys.argv[3]))
    else:
        stage_status()
