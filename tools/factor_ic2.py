# -*- coding: utf-8 -*-
"""
P2 因子IC扫描 v2 (numpy加速, 支持多池对照)
用法: python factor_ic2.py <pool> [<pool2> ...]
"""
import sys, pickle, time
import numpy as np
import pandas as pd

CACHE = 'data_cache'


def load_pool(pool):
    mem = pickle.load(open(f'{CACHE}/{pool}_members.pkl', 'rb'))
    px = pickle.load(open(f'{CACHE}/{pool}_prices.pkl', 'rb'))
    fin = pickle.load(open(f'{CACHE}/{pool}_financials.pkl', 'rb'))
    return mem, px, fin


def build_arrays(px):
    """{tc: (dates_np, close, volume)}"""
    arr = {}
    for tc, rows in px.items():
        if not rows:
            continue
        df = pd.DataFrame(rows)
        df['date'] = pd.to_datetime(df['date_ms'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
        df = df.sort_values('date').drop_duplicates('date')
        if len(df) < 300:
            continue
        arr[tc] = (df['date'].values.astype('datetime64[ns]'),
                   pd.to_numeric(df['close_price'], errors='coerce').values.astype(float),
                   pd.to_numeric(df['volume'], errors='coerce').values.astype(float))
    return arr


def price_factor(arr_tc, dt, name):
    dates, c, v = arr_tc
    i = np.searchsorted(dates, np.datetime64(dt), side='right')
    if i < 260 or i < 30:
        return np.nan
    try:
        if name == 'MOM12_1':
            return c[i-22] / c[i-252] - 1 if c[i-252] > 0 else np.nan
        if name == 'REV1':
            return c[i-1] / c[i-22] - 1 if c[i-22] > 0 else np.nan
        if name == 'VOL60':
            seg = c[i-61:i]
            r = np.diff(seg) / seg[:-1]
            return np.nanstd(r) * np.sqrt(252) if len(r) > 10 else np.nan
        if name == 'LIQ':
            return np.mean(v[i-20:i]) / (np.mean(v[i-250:i]) + 1e-9)
    except Exception:
        return np.nan
    return np.nan


def fin_factors(fin_tc):
    e = fin_tc or {}
    inc = e.get('income') or []
    bal = e.get('balance') or []
    inc_by = {i['fiscal_year']: i for i in inc if i.get('period_end_ms')}
    bal_by = {i['fiscal_year']: i for i in bal if i.get('period_end_ms')}
    recs = []
    for y, i in inc_by.items():
        b = bal_by.get(y)
        if not b:
            continue
        avail = min(i.get('report_date_ms') or 0, b.get('report_date_ms') or 0)
        if not avail:
            continue
        oi, oc = i.get('operating_income'), i.get('operating_costs')
        npf = i.get('parent_holder_net_profit') or i.get('net_profit')
        eq, at, td = b.get('holder_equity_total'), b.get('assets_total'), b.get('total_debt')
        prev = inc_by.get(y - 1) or {}
        oi_prev = prev.get('operating_income')
        recs.append({'avail_ms': avail, 'year': y,
                     'ROE': (npf / eq) if (npf and eq and eq > 0) else np.nan,
                     'GROWTH': ((oi / oi_prev - 1) if (oi and oi_prev and oi_prev > 0) else np.nan),
                     'MARGIN': ((oi - oc) / oi) if (oi and oc and oi > 0) else np.nan,
                     'LEV': (td / at) if (td is not None and at and at > 0) else np.nan,
                     'EPS': i.get('basic_eps')})
    return pd.DataFrame(recs).sort_values('avail_ms') if recs else None


def run(pool):
    print(f'\n{"="*80}\n池: {pool}')
    mem, px, fin = load_pool(pool)
    arr = build_arrays(px)
    codes = list(arr.keys())
    print(f'  标的: 成分{len(mem)} 有效价格{len(codes)} 财务{len(fin)}')

    all_dates = sorted(set().union(*[set(a[0]) for a in arr.values()]))
    dts = pd.Series(pd.to_datetime(all_dates))
    month_end = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)

    # 月末收盘(用于下月收益)
    close_me = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        dates, c, v = arr[tc]
        idx = np.searchsorted(dates, month_end.values.astype('datetime64[ns]'), side='right') - 1
        vals = np.where(idx >= 0, c[np.clip(idx, 0, len(c)-1)], np.nan)
        vals = np.where(idx >= 0, vals, np.nan)
        close_me[tc] = vals
    ret_next = close_me.shift(-1) / close_me - 1

    t0 = time.time()
    facs = {}
    for f in ['MOM12_1', 'REV1', 'VOL60', 'LIQ']:
        P = pd.DataFrame(index=month_end, columns=codes, dtype=float)
        for tc in codes:
            a = arr[tc]
            P[tc] = [price_factor(a, dt, f) for dt in month_end]
        facs[f] = P
    print(f'  价格因子 {time.time()-t0:.0f}s')

    fin_p = {f: pd.DataFrame(index=month_end, columns=codes, dtype=float) for f in ['ROE', 'GROWTH', 'MARGIN', 'LEV']}
    ep_p = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        fd = fin_factors(fin.get(tc))
        if fd is None:
            continue
        avails = fd['avail_ms'].values
        for dt in month_end:
            j = np.searchsorted(avails, int(pd.Timestamp(dt).timestamp() * 1000), side='right') - 1
            if j < 0:
                continue
            row = fd.iloc[j]
            for f in ['ROE', 'GROWTH', 'MARGIN', 'LEV']:
                fin_p[f].loc[dt, tc] = row[f]
            eps = row['EPS']
            if eps is not None and eps == eps and eps > 0:
                cv = close_me.loc[dt, tc]
                if cv and cv == cv and cv > 0:
                    ep_p.loc[dt, tc] = eps / cv
    facs.update(fin_p)
    facs['EP'] = ep_p

    print(f'\n{"因子":<10}{"IC均值":>9}{"IC标准差":>10}{"IR":>8}{"IC>0":>8}{"t值":>8}{"样本月":>7}  判定')
    print('-' * 76)
    rows = []
    for f, p in facs.items():
        ics = []
        for dt in month_end[:-1]:
            x = p.loc[dt].dropna()
            y = ret_next.loc[dt].dropna()
            common = x.index.intersection(y.index)
            if len(common) < 30:
                continue
            ic = x[common].rank().corr(y[common].rank())
            if ic == ic:
                ics.append(ic)
        if not ics:
            continue
        ics = np.array(ics)
        mean, sd = ics.mean(), ics.std(ddof=1)
        ir = mean / sd if sd > 0 else 0
        t = mean / (sd / np.sqrt(len(ics))) if sd > 0 else 0
        win = (ics > 0).mean()
        verdict = '★通过' if (abs(mean) > 0.03 and abs(ir) > 0.3) else '不达标'
        print(f'{f:<10}{mean:>+9.4f}{sd:>10.4f}{ir:>+8.2f}{win:>8.1%}{t:>+8.2f}{len(ics):>7}  {verdict}')
        rows.append({'pool': pool, 'factor': f, 'ic': mean, 'ir': ir, 'win': win, 't': t, 'n': len(ics)})
    pd.DataFrame(rows).to_csv(f'{CACHE}/factor_ic_{pool}.csv', index=False)
    return rows


if __name__ == '__main__':
    pools = sys.argv[1:] or ['csi1000']
    allrows = []
    for p in pools:
        allrows.extend(run(p))
    pd.DataFrame(allrows).to_csv(f'{CACHE}/factor_ic_all_pools.csv', index=False)
    print('\n门槛: |IC|>0.03 且 |IR|>0.3 进入P3; 已保存 factor_ic_all_pools.csv')
