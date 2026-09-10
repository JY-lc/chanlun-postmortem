# -*- coding: utf-8 -*-
"""
P2 数据管道 v2: 多池 + 并发(4线程) + 限流重试
用法:
  python p2_fetch2.py members <pool>                 # pool: hs300/csi500/csi1000
  python p2_fetch2.py prices <pool> <start> <cnt>
  python p2_fetch2.py financials <pool> <start> <cnt>
  python p2_fetch2.py status <pool>
"""
import os, sys, time, pickle
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests

BASE = 'https://fuyao.aicubes.cn'
CACHE = 'data_cache'
os.makedirs(CACHE, exist_ok=True)
POOLS = {'hs300': '000300.SH', 'csi500': '000905.SH', 'csi1000': '000852.SH'}
WORKERS = 4

import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ths_auth import get_api_key
KEY = get_api_key()
H = {'X-api-key': KEY}


def ms(ymd):
    return int(time.mktime(time.strptime(ymd + ' 00:00:00', '%Y%m%d %H:%M:%S')) * 1000)


def get(path, params, retries=4):
    for i in range(retries):
        try:
            r = requests.get(BASE + path, params=params, headers=H, timeout=30).json()
            if r.get('code') == 0:
                return r.get('data')
            if r.get('code') in (4001, 5001, 5002, 5003):
                time.sleep(1.0 + 1.2 * i); continue
            return None
        except Exception:
            time.sleep(0.8 + i)
    return None


def f_members(pool):
    d = get('/api/a-share-index/constituents/ths-stock-list', {'thscode': POOLS[pool]})
    items = (d or {}).get('item') or []
    members = [{'thscode': it['thscode'], 'ticker': it['ticker'], 'name': it['name']} for it in items]
    pickle.dump(members, open(f'{CACHE}/{pool}_members.pkl', 'wb'))
    print(f'{pool} 成分股 {len(members)} 只已保存')


def _fetch_price(m):
    tc = m['thscode']
    rows = []
    for s, e in [('20160101', '20251230'), ('20251231', '20260828')]:
        d = get('/api/a-share/prices/historical',
                {'thscode': tc, 'interval': '1d', 'start': ms(s), 'end': ms(e) + 86399999, 'adjust': 'forward'})
        if d:
            rows.extend(d.get('item') or [])
        time.sleep(0.15)
    return tc, rows


def _fetch_fin(m):
    tc = m['thscode']
    inc = get('/api/a-share/financials/income-statements',
              {'thscode': tc, 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
    time.sleep(0.15)
    bal = get('/api/a-share/financials/balance-sheets',
              {'thscode': tc, 'period': 'annual', 'start': ms('20160101'), 'end': ms('20251230')})
    return tc, {'income': (inc or {}).get('item') if isinstance(inc, dict) else [],
                'balance': (bal or {}).get('item') if isinstance(bal, dict) else []}


def f_batch(pool, kind, start, cnt):
    members = pickle.load(open(f'{CACHE}/{pool}_members.pkl', 'rb'))
    fp = f'{CACHE}/{pool}_{"prices" if kind == "prices" else "financials"}.pkl'
    data = pickle.load(open(fp, 'rb')) if os.path.exists(fp) else {}
    batch = [m for m in members[start:start + cnt] if m['thscode'] not in data]
    fn = _fetch_price if kind == 'prices' else _fetch_fin
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(fn, m): m['thscode'] for m in batch}
        for fu in as_completed(futs):
            try:
                tc, val = fu.result()
                data[tc] = val
            except Exception:
                pass
    pickle.dump(data, open(fp, 'wb'))
    print(f'{pool} {kind}: 本批{len(batch)}只, 累计{len(data)}/{len(members)}, 耗时{time.time()-t0:.0f}s')


def f_status(pool):
    def n(kind):
        p = f'{CACHE}/{pool}_{kind}.pkl'
        return len(pickle.load(open(p, 'rb'))) if os.path.exists(p) else 0
    print(f'{pool}: members={n("members")} prices={n("prices")} financials={n("financials")}')


if __name__ == '__main__':
    cmd, pool = sys.argv[1], sys.argv[2]
    if cmd == 'members':
        f_members(pool)
    elif cmd == 'status':
        f_status(pool)
    else:
        f_batch(pool, cmd, int(sys.argv[3]), int(sys.argv[4]))
