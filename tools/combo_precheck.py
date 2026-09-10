# -*- coding: utf-8 -*-
"""
P3预检: 通过IC门槛的因子, 在组合层面(月度多头组合)是否仍有效(含成本/换手)
用法: python combo_precheck.py <pool>
"""
import sys, pickle
import numpy as np
import pandas as pd
import factor_ic2 as fi

CACHE = 'data_cache'


def build_panels(pool):
    mem, px, fin = fi.load_pool(pool)
    arr = fi.build_arrays(px)
    codes = list(arr.keys())
    all_dates = sorted(set().union(*[set(a[0]) for a in arr.values()]))
    dts = pd.Series(pd.to_datetime(all_dates))
    month_end = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
    close_me = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        dates, c, v = arr[tc]
        idx = np.searchsorted(dates, month_end.values.astype('datetime64[ns]'), side='right') - 1
        vals = np.where(idx >= 0, c[np.clip(idx, 0, len(c) - 1)], np.nan)
        close_me[tc] = np.where(idx >= 0, vals, np.nan)
    ret_next = close_me.shift(-1) / close_me - 1
    facs = {}
    for f in ['MOM12_1', 'REV1', 'VOL60', 'LIQ']:
        P = pd.DataFrame(index=month_end, columns=codes, dtype=float)
        for tc in codes:
            P[tc] = [fi.price_factor(arr[tc], dt, f) for dt in month_end]
        facs[f] = P
    ep = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        fd = fi.fin_factors(fin.get(tc))
        if fd is None:
            continue
        avails = fd['avail_ms'].values
        for dt in month_end:
            j = np.searchsorted(avails, int(pd.Timestamp(dt).timestamp() * 1000), side='right') - 1
            if j < 0:
                continue
            eps = fd.iloc[j]['EPS']
            cv = close_me.loc[dt, tc]
            if eps is not None and eps == eps and eps > 0 and cv and cv == cv and cv > 0:
                ep.loc[dt, tc] = eps / cv
    facs['EP'] = ep
    return facs, ret_next, month_end


def perf(rets, label):
    r = np.array([x for x in rets if x == x])
    if len(r) < 12:
        print(f'{label}: 样本不足')
        return None
    cum = np.cumprod(1 + r)
    years = len(r) / 12
    ann = cum[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(12)
    sharpe = (ann - 0.02) / vol if vol > 0 else 0
    peak = np.maximum.accumulate(cum)
    dd = ((peak - cum) / peak).max()
    print(f'{label:<28} 年化{ann:+.2%} 波动{vol:.2%} 夏普{sharpe:+.2f} 回撤{dd:.2%}')
    return ann, sharpe, dd


def main(pool, topn=50):
    facs, ret_next, month_end = build_panels(pool)
    print(f'\n池={pool} 选股数={topn} 月频调仓')
    # 基准: 全池等权(每月再平衡)
    base = [ret_next.loc[dt].mean() for dt in month_end[:-1]]
    perf(base, '基准:全池等权月度再平衡')
    print()
    configs = [('LIQ', 'low'), ('REV1', 'low'), ('VOL60', 'low'), ('MOM12_1', 'high'), ('EP', 'high')]
    results = {}
    for f, direction in configs:
        P = facs[f]
        gross, net1, net3 = [], [], []
        prev_sel = set()
        turnovers = []
        for dt in month_end[:-1]:
            x = P.loc[dt].dropna()
            y = ret_next.loc[dt].dropna()
            common = x.index.intersection(y.index)
            if len(common) < topn + 10:
                continue
            xs = x[common].sort_values(ascending=(direction == 'low'))
            sel = list(xs.index[:topn])
            gross.append(y[sel].mean())
            to = 1 - len(set(sel) & prev_sel) / max(len(sel), 1) if prev_sel else 1.0
            turnovers.append(to)
            net1.append(y[sel].mean() - to * 2 * 0.001)   # 0.1%单边
            net3.append(y[sel].mean() - to * 2 * 0.003)   # 0.3%单边
            prev_sel = set(sel)
        print(f'--- 因子 {f} ({"选低" if direction=="low" else "选高"}{topn}只) 平均月换手{np.mean(turnovers):.0%} ---')
        perf(gross, '  毛收益(无成本)')
        perf(net1, '  净收益(单边0.1%)')
        perf(net3, '  净收益(单边0.3%)')
        results[f] = (perf(net1, ''), perf(net3, ''))
        print()
    return results


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'csi1000')
