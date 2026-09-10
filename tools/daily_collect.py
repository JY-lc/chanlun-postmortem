# -*- coding: utf-8 -*-
"""
每日数据采集（前向积累，防数据永久丢失）
==========================================
背景：同花顺「个股异动/飙升榜/热股榜」仅提供当日快照，龙虎榜/热榜历史仅1年。
      今天不采集，明天这些数据就永久丢失。建议每个交易日 15:10 后运行一次。

用法:
    python tools/daily_collect.py                # 采集今日
    python tools/daily_collect.py --date 2026-09-10   # 补采指定日期(涨停池/龙虎榜支持历史)
    python tools/daily_collect.py --force        # 覆盖已存在的当日文件

数据落地: data_collect/<YYYY-MM-DD>/*.json  +  _manifest.json（采集清单与状态）

定时任务(Windows): schtasks /create /tn "ths_daily_collect" /tr "python <路径>\\tools\\daily_collect.py" /sc daily /st 15:10
"""
import os, sys, json, time, argparse
from datetime import datetime

import requests

BASE = 'https://fuyao.aicubes.cn'
ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data_collect')


import sys as _sys
_sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from ths_auth import get_api_key


def load_key():
    """读取同花顺 API Key（环境变量优先，多平台回退；详见 CREDENTIALS.md）"""
    return get_api_key()


KEY = load_key()
H = {'X-api-key': KEY} if KEY else {}


def ms(ymd):
    return int(time.mktime(time.strptime(ymd + ' 00:00:00', '%Y%m%d %H:%M:%S')) * 1000)


def fetch(path, params=None, retries=3):
    """带退避重试的GET；返回 (code, data)"""
    for i in range(retries):
        try:
            r = requests.get(BASE + path, params=params or {}, headers=H, timeout=30).json()
            if r.get('code') == 0:
                return 0, r.get('data')
            if r.get('code') in (4001, 5001, 5002, 5003):
                time.sleep(1.5 * (i + 1)); continue
            return r.get('code'), None
        except Exception:
            time.sleep(1.5 * (i + 1))
    return 'ERR', None


def collect_limit_up(date_yyyymmdd):
    """涨停池（分页取全）"""
    items, page = [], 1
    while page <= 10:
        code, d = fetch('/api/a-share/special-data/limit-up-pool',
                        {'date_ms': ms(date_yyyymmdd), 'page': page, 'size': 200})
        if code != 0 or not d:
            break
        batch = d.get('item') or []
        items.extend(batch)
        pg = d.get('pagination') or {}
        if page >= (pg.get('pages') or 1):
            break
        page += 1
        time.sleep(0.3)
    return items


def collect(date_str, force=False):
    date_compact = date_str.replace('-', '')
    day_dir = os.path.join(ROOT, date_str)
    os.makedirs(day_dir, exist_ok=True)
    manifest = {'date': date_str, 'collected_at': datetime.now().isoformat(), 'files': {}}

    tasks = [
        ('limit_up_pool', '/api/a-share/special-data/limit-up-pool', None, 'special'),
        ('limit_up_ladder', '/api/a-share/special-data/limit-up-ladder', None, 'special'),
        ('dragon_tiger_all', '/api/a-share/special-data/dragon-tiger-list', {'board_type': 'all', 'date': date_str}, 'special'),
        ('dragon_tiger_org', '/api/a-share/special-data/dragon-tiger-list', {'board_type': 'org', 'date': date_str}, 'special'),
        ('dragon_tiger_hot_money', '/api/a-share/special-data/dragon-tiger-list', {'board_type': 'hot_money', 'date': date_str}, 'special'),
        ('anomaly_list', '/api/a-share/special-data/anomaly-analysis-list', None, 'special'),
        ('skyrocket_list', '/api/a-share/special-data/skyrocket-list', {'period': 'day'}, 'special'),
        ('hot_stock_list', '/api/a-share/special-data/hot-stock-list', {'period': 'day'}, 'special'),
        ('hot_stock_history', '/api/a-share/special-data/hot-stock-list-history', {'date': date_str}, 'special'),
    ]

    for name, path, params, _kind in tasks:
        fp = os.path.join(day_dir, name + '.json')
        if os.path.exists(fp) and not force:
            manifest['files'][name] = 'skipped(exists)'
            continue
        if name == 'limit_up_pool':
            items = collect_limit_up(date_compact)
            code, payload = (0, {'item': items}) if items else (0, {'item': []})
        else:
            code, payload = fetch(path, params)
        if code == 0 and payload is not None:
            with open(fp, 'w', encoding='utf-8') as f:
                json.dump(payload, f, ensure_ascii=False)
            n = len(payload.get('item') or payload.get('stock_items') or [])
            manifest['files'][name] = f'ok(n={n})'
        else:
            manifest['files'][name] = f'fail(code={code})'
        time.sleep(0.35)

    with open(os.path.join(day_dir, '_manifest.json'), 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return manifest


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=datetime.now().strftime('%Y-%m-%d'))
    ap.add_argument('--force', action='store_true')
    a = ap.parse_args()
    if not KEY:
        print('未找到同花顺凭据(HITHINK_FINANCE_API_KEY 或 credentials.env)'); sys.exit(1)
    m = collect(a.date, a.force)
    print(f"采集 {m['date']}:")
    for k, v in m['files'].items():
        print(f'  {k}: {v}')
    print(f"落地目录: {os.path.join(ROOT, a.date)}")
