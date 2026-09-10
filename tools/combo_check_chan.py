# -*- coding: utf-8 -*-
"""缠论特征: 分层单调性 + 组合检验(含成本/样本外)"""
import numpy as np
import pandas as pd

S = pd.read_pickle('data_cache/chan_feat_samples_csi1000.pkl')
S['dt'] = pd.to_datetime(S['date'])
print(f'样本 {len(S)} 条 / {S["symbol"].nunique()} 只 / {S["date"].min()}~{S["date"].max()}')

FEATS = ['bi_dir', 'bi_bars', 'bi_ret', 'zs_pos', 'in_zs', 'above_zs', 'div_ratio', 'ma_bull', 'ma_bear', 'days_fx']

print('\n===== 分层: 每月按特征分5档, 各档未来月收益均值(%) =====')
print(f'{"特征":<12}{"Q1":>8}{"Q2":>8}{"Q3":>8}{"Q4":>8}{"Q5":>8}{"Q5-Q1":>9}  单调性')
print('-' * 74)
for f in FEATS:
    sub = S[['dt', f, 'fwd']].dropna().copy()
    if len(sub) < 500:
        continue
    def q(gr):
        r = gr.rank(method='first')
        return pd.qcut(r, 5, labels=False, duplicates='drop')
    try:
        sub['q'] = sub.groupby('dt')[f].transform(q)
    except Exception as e:
        print(f'{f:<12} 分层失败: {e}'); continue
    lay = sub.dropna(subset=['q']).groupby('q')['fwd'].mean() * 100
    vals = [lay.get(i, np.nan) for i in range(5)]
    diff = vals[4] - vals[0]
    mono = '单调↑' if all(vals[i] <= vals[i+1] for i in range(4)) else ('单调↓' if all(vals[i] >= vals[i+1] for i in range(4)) else '非单调')
    print(f'{f:<12}' + ''.join(f'{v:>+8.2f}' for v in vals) + f'{diff:>+9.2f}  {mono}')

print('\n===== 组合: 等权打分(bi_bars高 + bi_ret低), 选Top20% vs 基准 =====')
# 月度标准化打分
def zscore(gr):
    s = gr.std()
    return (gr - gr.mean()) / s if s and s > 0 else gr * 0
tmp = S[['dt', 'symbol', 'bi_bars', 'bi_ret', 'fwd']].dropna().copy()
tmp['z1'] = tmp.groupby('dt')['bi_bars'].transform(zscore)
tmp['z2'] = tmp.groupby('dt')['bi_ret'].transform(zscore)
tmp['score'] = tmp['z1'] - tmp['z2']

monthly = []
prev = set()
for d, g in tmp.groupby('dt'):
    if len(g) < 20:
        continue
    g = g.sort_values('score', ascending=False)
    top = g.head(max(int(len(g) * 0.2), 5))
    sel = set(top['symbol'])
    to = 1 - len(sel & prev) / len(sel) if prev else 1.0
    monthly.append({'dt': d, 'grp': top['fwd'].mean() - to * 2 * 0.001, 'bench': g['fwd'].mean(), 'n': len(g)})
    prev = sel
M = pd.DataFrame(monthly)
print(f'月份数 {len(M)}')


def perf(r, label):
    r = np.array(r, dtype=float)
    cum = np.cumprod(1 + r); yrs = len(r) / 12
    ann = cum[-1] ** (1 / yrs) - 1
    vol = r.std() * np.sqrt(12)
    sh = (ann - 0.02) / vol if vol > 0 else 0
    dd = ((np.maximum.accumulate(cum) - cum) / np.maximum.accumulate(cum)).max()
    print(f'{label:<30} 年化{ann:+8.2%} 波动{vol:7.2%} 夏普{sh:+5.2f} 回撤{dd:7.2%}')
    return ann, sh, dd


perf(M['grp'], '缠论特征组合(净0.1%)')
perf(M['bench'], '基准:全池等权')
perf(M['grp'] - M['bench'], '超额(未复利)')
print()
M['year'] = M['dt'].dt.year
win = 0
for y, g in M.groupby('year'):
    s = np.prod(1 + g['grp']) - 1
    b = np.prod(1 + g['bench']) - 1
    if s > b:
        win += 1
    print(f'  {y}: 组合{s:+.2%} 基准{b:+.2%} 超额{s-b:+.2%}')
print(f'  跑赢年份 {win}/{M["year"].nunique()}')

print('\n===== 样本外分段 =====')
for lab, (a, b) in [('开发 2016-2021', ('2016', '2021')), ('验证 2022-2026', ('2022', '2026'))]:
    sub = M[(M['year'] >= int(a)) & (M['year'] <= int(b))]
    if len(sub) < 12:
        print(f'{lab}: 样本不足'); continue
    perf(sub['grp'], f'{lab} 组合')
    perf(sub['bench'], f'{lab} 基准')
