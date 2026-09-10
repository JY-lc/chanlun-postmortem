# -*- coding: utf-8 -*-
"""
实验: 缠论结构作为"当下可得"特征 (strict_open 思想)
====================================================
对每个交易月末 t: 用「截至 t 的K线」重新 analyze → 提取当下特征(无未来信息)
标签: 次月首日开盘买入 → 下月末收盘 的收益 (执行修正)
用法: python chan_feat.py <pool> <start> <count>   # 分批按股票
     python chan_feat.py <pool> analyze           # 汇总分析
"""
import sys, os, pickle
import numpy as np
import pandas as pd
sys.path.insert(0, 'work')
from chanlun.core import ChanLunAnalyzer, RawKline, calculate_macd, calc_macd_area
import factor_ic2 as fi

CACHE = 'data_cache'


def df_to_klines(df):
    ks = []
    for i, row in df.iterrows():
        ks.append(RawKline(date=str(row['日期'])[:10], open=float(row['开盘']), high=float(row['最高']),
                           low=float(row['最低']), close=float(row['收盘']),
                           volume=float(row.get('成交量', 0)), index=len(ks)))
    return ks


def month_ends(dates_np):
    dts = pd.Series(pd.to_datetime(dates_np))
    me = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
    return me


def extract_feat(klines, an, i_last, close_px):
    """i_last: 截至的最后一个K线索引; 只用 klines[:i_last+1] 的信息"""
    f = {}
    if not an.strokes:
        return None
    st = an.strokes
    last = st[-1]
    f['bi_dir'] = float(last.direction)
    # 当前笔已走交易日数
    dmap = {k.date: j for j, k in enumerate(klines)}
    s_idx = dmap.get(last.start_date)
    e_idx = dmap.get(last.end_date)
    f['bi_bars'] = float(i_last - s_idx) if s_idx is not None else np.nan
    # 当前笔起点至今日涨跌幅
    if s_idx is not None and klines[s_idx].close > 0:
        f['bi_ret'] = close_px / klines[s_idx].close - 1
    else:
        f['bi_ret'] = np.nan
    # 最近中枢位置
    zs = [p for p in an.pivots if p.is_valid]
    if zs:
        p = zs[-1]
        rng = (p.zg - p.zd)
        if rng > 0:
            f['zs_pos'] = (close_px - p.zd) / rng
            f['in_zs'] = 1.0 if p.zd <= close_px <= p.zg else 0.0
            f['above_zs'] = 1.0 if close_px > p.zg else 0.0
        else:
            f['zs_pos'] = np.nan; f['in_zs'] = np.nan; f['above_zs'] = np.nan
    else:
        f['zs_pos'] = np.nan; f['in_zs'] = np.nan; f['above_zs'] = np.nan
    # 背驰度: 当前笔 vs 上一笔 MACD面积比
    if len(st) >= 2:
        closes = [k.close for k in klines[:i_last + 1]]
        dif, dea, hist = calculate_macd(closes, 12, 26, 9)
        dd = {k.date: j for j, k in enumerate(klines[:i_last + 1])}
        def area(s):
            a, b = dd.get(s.start_date), dd.get(s.end_date)
            if a is None or b is None or b <= a:
                return None
            return abs(calc_macd_area(hist, a, b))
        a1, a2 = area(st[-1]), area(st[-2])
        f['div_ratio'] = (a1 / a2) if (a1 and a2 and a2 > 0) else np.nan
    else:
        f['div_ratio'] = np.nan
    # 均线状态
    if i_last >= 60:
        cl = np.array([k.close for k in klines[:i_last + 1]])
        ma20, ma60 = cl[-20:].mean(), cl[-60:].mean()
        f['ma_bull'] = 1.0 if (cl[-1] > ma20 > ma60) else 0.0
        f['ma_bear'] = 1.0 if (cl[-1] < ma20 < ma60) else 0.0
    else:
        f['ma_bull'] = np.nan; f['ma_bear'] = np.nan
    # 距最后分型天数
    if an.fractals:
        d = an.fractals[-1].date
        f['days_fx'] = float(i_last - dmap.get(d, i_last))
    else:
        f['days_fx'] = np.nan
    return f


def batch(pool, start, cnt):
    mem, px, fin = fi.load_pool(pool)
    codes = list(px.keys())[start:start + cnt]
    fp = f'{CACHE}/chan_feat_{pool}.pkl'
    data = pickle.load(open(fp, 'rb')) if os.path.exists(fp) else {}
    for tc in codes:
        if tc in data:
            continue
        rows = px[tc]
        df = pd.DataFrame(rows)
        df['日期'] = pd.to_datetime(df['date_ms'], unit='ms', utc=True).dt.tz_convert('Asia/Shanghai').dt.tz_localize(None)
        for c in ['open_price', 'high_price', 'low_price', 'close_price', 'volume', 'turnover']:
            df[c] = pd.to_numeric(df[c], errors='coerce')
        df = df.sort_values('日期').reset_index(drop=True)
        df = df.drop_duplicates('日期')
        df = df.rename(columns={'open_price': '开盘', 'high_price': '最高', 'low_price': '最低',
                                'close_price': '收盘', 'volume': '成交量'})
        if len(df) < 300:
            data[tc] = []
            continue
        klines = df_to_klines(df)
        dates_np = df['日期'].values
        me = month_ends(dates_np)
        dmap = {k.date: j for j, k in enumerate(klines)}
        recs = []
        for t in me:
            ts = pd.Timestamp(t)
            j = np.searchsorted(dates_np, ts.to_datetime64(), side='right') - 1
            if j < 120:
                continue
            an = ChanLunAnalyzer()
            an.analyze(klines[:j + 1])
            f = extract_feat(klines, an, j, klines[j].close)
            if f is None:
                continue
            f['date'] = str(ts.date())
            recs.append(f)
        data[tc] = recs
    pickle.dump(data, open(fp, 'wb'))
    print(f'{pool} 特征: 本批{len(codes)}只, 累计{len(data)}/{len(mem)}, 记录{sum(len(v) for v in data.values())}')


def analyze(pool):
    mem, px, fin = fi.load_pool(pool)
    fp = f'{CACHE}/chan_feat_{pool}.pkl'
    data = pickle.load(open(fp, 'rb'))
    # 下月收益(执行修正)
    arr = fi.build_arrays(px)
    all_dates = sorted(set().union(*[set(a[0]) for a in arr.values()]))
    dts = pd.Series(pd.to_datetime(all_dates))
    me_all = pd.to_datetime(dts.groupby([dts.dt.year, dts.dt.month]).max().values)
    close_me = pd.DataFrame(index=me_all, columns=list(arr.keys()), dtype=float)
    open_next = pd.DataFrame(index=me_all, columns=list(arr.keys()), dtype=float)
    for tc, (dn, c, v) in arr.items():
        idx = np.searchsorted(dn, me_all.values.astype('datetime64[ns]'), side='right') - 1
        close_me[tc] = np.where(idx >= 0, c[np.clip(idx, 0, len(c) - 1)], np.nan)
        rows = px[tc]
        opens = np.array([r.get('open_price') for r in rows], dtype=float)
        i_nx = np.searchsorted(dn, me_all.values.astype('datetime64[ns]'), side='right')
        open_next[tc] = np.where(i_nx < len(opens), opens[np.clip(i_nx, 0, len(opens) - 1)], np.nan)
    ret_exec = close_me.shift(-1) / open_next - 1

    # 组装样本
    rows = []
    for tc, recs in data.items():
        for r in recs:
            d = pd.Timestamp(r['date'])
            # 该月末在 me_all 中的下一个索引
            k = np.searchsorted(me_all.values, d.to_datetime64(), side='right') - 1
            if k < 0 or k >= len(me_all):
                continue
            y = ret_exec.iloc[k].get(tc, np.nan)
            if y != y:
                continue
            r2 = dict(r); r2['symbol'] = tc; r2['fwd'] = y
            rows.append(r2)
    S = pd.DataFrame(rows)
    S['year'] = pd.to_datetime(S['date']).dt.year
    print(f'样本: {len(S)} 条, {S["symbol"].nunique()} 只, {S["date"].min()} ~ {S["date"].max()}')

    feats = ['bi_dir', 'bi_bars', 'bi_ret', 'zs_pos', 'in_zs', 'above_zs', 'div_ratio', 'ma_bull', 'ma_bear', 'days_fx']
    print(f'\n{"特征":<12}{"IC":>9}{"t值":>8}{"样本":>8}  分层(五档未来收益均值,%)')
    print('-' * 92)
    for f in feats:
        sub = S[['date', f, 'fwd']].dropna()
        if len(sub) < 500:
            print(f'{f:<12} 样本不足({len(sub)})')
            continue
        ics = []
        for d, g in sub.groupby('date'):
            if len(g) < 50:
                continue
            ic = g[f].rank().corr(g['fwd'].rank())
            if ic == ic:
                ics.append(ic)
        ics = np.array(ics)
        mean = ics.mean() if len(ics) else np.nan
        t = mean / (ics.std(ddof=1) / np.sqrt(len(ics))) if len(ics) > 1 and ics.std() > 0 else np.nan
        # 分层
        try:
            sub = sub.copy()
            sub['q'] = sub.groupby('date')[f].transform(lambda x: pd.qcut(x.rank(method='first'), 5, labels=False))
            layer = sub.groupby('q')['fwd'].mean() * 100
            ls = ' '.join(f'{v:+6.2f}' for v in layer.values)
        except Exception:
            ls = '(分层失败)'
        print(f'{f:<12}{mean:>+9.4f}{t:>+8.2f}{len(sub):>8}  {ls}')
    S.to_pickle(f'{CACHE}/chan_feat_samples_{pool}.pkl')
    return S


if __name__ == '__main__':
    pool = sys.argv[1]
    if sys.argv[2] == 'analyze':
        analyze(pool)
    else:
        batch(pool, int(sys.argv[2]), int(sys.argv[3]))
