# -*- coding: utf-8 -*-
"""
P3: EP(低估值)组合的严格验证
=============================
1) 执行时点修正: 因子用月末收盘计算 → 次月首日开盘买入, 下月末收盘卖出(无前视)
2) 市值中性化: EP 对 log(市值) 横截面回归取残差 (股本=归母净利/EPS 反推)
3) 价值陷阱过滤: 剔除最近年报净利润<0 或 净资产<0
4) 逐年超额 + 滚动12月超额
"""
import sys, pickle
import numpy as np
import pandas as pd
import factor_ic2 as fi

CACHE = 'data_cache'
TOPN = 50


def build_all(pool):
    mem, px, fin = fi.load_pool(pool)
    arr = fi.build_arrays(px)
    codes = list(arr.keys())
    all_dates = sorted(set().union(*[set(a[0]) for a in arr.values()]))
    dts = pd.Series(pd.to_datetime(all_dates))
    month_end = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)

    close_me = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    open_next1 = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        dates, c, v = arr[tc]
        me = month_end.values.astype('datetime64[ns]')
        i_me = np.searchsorted(dates, me, side='right') - 1
        close_me[tc] = np.where(i_me >= 0, c[np.clip(i_me, 0, len(c) - 1)], np.nan)
        i_nx = np.searchsorted(dates, me, side='right')  # dt之后第一条
        o = px[tc]
        opens = np.array([r.get('open_price') for r in o], dtype=float)
        open_next1[tc] = np.where(i_nx < len(opens), opens[np.clip(i_nx, 0, len(opens) - 1)], np.nan)

    # 执行修正后的下月收益: 下月末收盘 / 次月首日开盘 - 1
    ret_exec = close_me.shift(-1) / open_next1 - 1

    # EP 因子 + 市值
    ep = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    mcap = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    bad = pd.DataFrame(index=month_end, columns=codes, dtype=bool).fillna(False)
    for tc in codes:
        fd = fi.fin_factors(fin.get(tc))
        if fd is None:
            continue
        avails = fd['avail_ms'].values
        for dt in month_end:
            j = np.searchsorted(avails, int(pd.Timestamp(dt).timestamp() * 1000), side='right') - 1
            if j < 0:
                continue
            row = fd.iloc[j]
            cv = close_me.loc[dt, tc]
            if cv and cv == cv and cv > 0 and row['EPS'] and row['EPS'] == row['EPS'] and row['EPS'] > 0:
                ep.loc[dt, tc] = row['EPS'] / cv
            # 市值: 股本≈归母净利/EPS
            sh = row.get('SHARES')
            if sh and sh == sh and sh > 0 and cv and cv == cv:
                mcap.loc[dt, tc] = sh * cv
            # 价值陷阱: 净利润<0 或 净资产<0
            bad.loc[dt, tc] = bool(row.get('LOSS')) or bool(row.get('NEG_EQ'))
    return ep, mcap, bad, ret_exec, close_me, month_end, codes, fin


def fin_factors_ext(fin_tc):
    """扩展版: 含股本(反推)与亏损标记"""
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
        npf = i.get('parent_holder_net_profit') or i.get('net_profit')
        eps = i.get('basic_eps')
        eq = b.get('holder_equity_total')
        shares = (npf / eps) if (npf and eps and eps > 0) else None
        recs.append({'avail_ms': avail, 'EPS': eps, 'SHARES': shares,
                     'LOSS': (npf is not None and npf < 0),
                     'NEG_EQ': (eq is not None and eq < 0)})
    return pd.DataFrame(recs).sort_values('avail_ms') if recs else None


def build_better(pool):
    """用扩展财务重算 EP/市值/陷阱"""
    mem, px, fin = fi.load_pool(pool)
    arr = fi.build_arrays(px)
    codes = list(arr.keys())
    all_dates = sorted(set().union(*[set(a[0]) for a in arr.values()]))
    dts = pd.Series(pd.to_datetime(all_dates))
    month_end = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
    close_me = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    open_next1 = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        dates, c, v = arr[tc]
        me = month_end.values.astype('datetime64[ns]')
        i_me = np.searchsorted(dates, me, side='right') - 1
        close_me[tc] = np.where(i_me >= 0, c[np.clip(i_me, 0, len(c) - 1)], np.nan)
        opens = np.array([r.get('open_price') for r in px[tc]], dtype=float)
        i_nx = np.searchsorted(dates, me, side='right')
        open_next1[tc] = np.where(i_nx < len(opens), opens[np.clip(i_nx, 0, len(opens) - 1)], np.nan)
    ret_exec = close_me.shift(-1) / open_next1 - 1

    ep = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    lnm = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    bad = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for tc in codes:
        fd = fin_factors_ext(fin.get(tc))
        if fd is None:
            continue
        avails = fd['avail_ms'].values
        for dt in month_end:
            j = np.searchsorted(avails, int(pd.Timestamp(dt).timestamp() * 1000), side='right') - 1
            if j < 0:
                continue
            row = fd.iloc[j]
            cv = close_me.loc[dt, tc]
            if cv and cv == cv and cv > 0 and row['EPS'] and row['EPS'] == row['EPS'] and row['EPS'] > 0:
                ep.loc[dt, tc] = row['EPS'] / cv
            if row['SHARES'] and row['SHARES'] == row['SHARES'] and row['SHARES'] > 0 and cv and cv == cv:
                lnm.loc[dt, tc] = np.log(row['SHARES'] * cv)
            bad.loc[dt, tc] = 1.0 if (row['LOSS'] or row['NEG_EQ']) else 0.0
    return ep, lnm, bad, ret_exec, month_end, codes


def combo(sel_fn, ret, month_end, cost=0.001):
    """sel_fn(dt)->选中的代码列表"""
    rets, prev = [], set()
    for dt in month_end[:-1]:
        sel = sel_fn(dt)
        if not sel:
            continue
        y = ret.loc[dt]
        s = y[[c for c in sel if c in y.index]].dropna()
        if s.empty:
            continue
        to = 1 - len(set(s.index) & prev) / len(s) if prev else 1.0
        rets.append(s.mean() - to * 2 * cost)
        prev = set(s.index)
    return np.array(rets)


def stats(r, label):
    r = np.array([x for x in r if x == x])
    if len(r) < 12:
        print(f'{label}: 样本不足({len(r)})')
        return None
    cum = np.cumprod(1 + r); yrs = len(r) / 12
    ann = cum[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ann - 0.02) / vol if vol > 0 else 0
    dd = ((np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)).max()
    print(f'{label:<34} 年化{ann:+.2%} 波动{vol:.2%} 夏普{sh:+.2f} 回撤{dd:.2%}')
    return ann, sh, dd, r


def main(pool='csi1000'):
    ep, lnm, bad, ret_exec, month_end, codes = build_better(pool)
    print(f'池={pool} 标的={len(codes)} 月份={len(month_end)}')
    print('执行时点: 月末收盘算因子 → 次月首日开盘买入 → 下月末收盘卖出(无前视)\n')

    # 基准(全池等权, 同一执行口径)
    def bench(dt):
        y = ret_exec.loc[dt].dropna()
        return list(y.index)
    stats(combo(bench, ret_exec, month_end, cost=0.0), '基准:全池等权(执行修正)')

    # 1) 原始EP
    def ep_sel(dt):
        x = ep.loc[dt].dropna()
        return list(x.sort_values(ascending=False).index[:TOPN])
    stats(combo(ep_sel, ret_exec, month_end), 'EP原始(净0.1%)')

    # 2) 价值陷阱过滤
    def ep_clean(dt):
        x = ep.loc[dt].dropna()
        b = bad.loc[dt]
        x = x[[c for c in x.index if b.get(c, 0) != 1.0]]
        return list(x.sort_values(ascending=False).index[:TOPN])
    stats(combo(ep_clean, ret_exec, month_end), 'EP+剔除亏损/负净资产(净0.1%)')

    # 3) 市值中性: EP 对 log(市值) 回归取残差
    resid = pd.DataFrame(index=month_end, columns=codes, dtype=float)
    for dt in month_end:
        x = ep.loc[dt].dropna()
        m = lnm.loc[dt]
        common = x.index.intersection(m.dropna().index)
        if len(common) < 30:
            continue
        X = np.column_stack([np.ones(len(common)), m[common].values])
        y = x[common].values
        try:
            beta, *_ = np.linalg.lstsq(X, y, rcond=None)
            r = y - X @ beta
            resid.loc[dt, common] = r
        except Exception:
            pass

    def ep_neutral(dt):
        x = resid.loc[dt].dropna()
        b = bad.loc[dt]
        x = x[[c for c in x.index if b.get(c, 0) != 1.0]]
        return list(x.sort_values(ascending=False).index[:TOPN])
    stats(combo(ep_neutral, ret_exec, month_end), 'EP+市值中性+剔陷阱(净0.1%)')

    # 4) 逐年(EP清洗版)
    r = combo(ep_clean, ret_exec, month_end)
    rb = combo(bench, ret_exec, month_end, cost=0.0)
    n = min(len(r), len(rb))
    dates = month_end[1:1 + n]
    print('\n逐年超额 (EP清洗版 vs 基准):')
    df = pd.DataFrame({'date': dates[:n], 'ep': r[:n], 'bm': rb[:n]})
    df['year'] = pd.to_datetime(df['date']).dt.year
    win = 0
    for y, g in df.groupby('year'):
        e = np.prod(1 + g['ep']) - 1
        b = np.prod(1 + g['bm']) - 1
        if e > b:
            win += 1
        print(f'  {y}: EP{e:+.2%} 基准{b:+.2%} 超额{e-b:+.2%}')
    print(f'  跑赢年份: {win}/{df["year"].nunique()}')

    # 5) 滚动12月超额
    roll = pd.Series(r[:n] - rb[:n]).rolling(12).sum()
    print(f'\n滚动12月超额: 均值{roll.mean():+.2%} 中位{roll.median():+.2%} '
          f'正占比{(roll.dropna()>0).mean():.0%} 最差{roll.min():+.2%}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else 'csi1000')
