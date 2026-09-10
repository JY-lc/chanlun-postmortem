# -*- coding: utf-8 -*-
"""聚合确认制口径蒙特卡洛结果"""
import json
import numpy as np
res = json.load(open('data_cache/mc_confirm_results.json'))
real = {'annual': 0.0205, 'dd': 0.0555, 'sharpe': -0.15}  # 确认制真实结果
ra = np.array([r['annual'] for r in res])
rd = np.array([r['dd'] for r in res])
rs = np.array([r['sharpe'] for r in res])
n = len(res)
pf = 1.0 / n
p_a = max(np.mean(ra >= real['annual']), pf)
p_s = max(np.mean(rs >= real['sharpe']), pf)
p_d = max(np.mean(rd <= real['dd']), pf)
joint = max(np.mean((ra >= real['annual']) & (rd <= real['dd']) & (rs >= real['sharpe'])), pf)
print(f'迭代数 {n}')
print(f'真实(确认制): 年化{real["annual"]:.2%} 回撤{real["dd"]:.2%} 夏普{real["sharpe"]:.2f}')
print(f'随机(打乱信号日期): 年化均值{ra.mean():.2%} 中位{np.median(ra):.2%} | 回撤均值{rd.mean():.2%} | 夏普均值{rs.mean():.2f} 中位{np.median(rs):.2f}')
print(f'p(年化)={p_a:.4f}  p(夏普)={p_s:.4f}  p(回撤)={p_d:.4f}  联合p={joint:.4f}')
print(f'真实年化超过随机样本比例: {np.mean(ra < real["annual"])*100:.0f}%')
print(f'真实夏普超过随机样本比例: {np.mean(rs < real["sharpe"])*100:.0f}%')
print()
print('随机分布明细(年化%, 回撤%, 夏普):')
for r in res:
    print(f"  iter{r['iter']:02d}: {r['annual']*100:+.2f}% {r['dd']*100:.2f}% {r['sharpe']:+.2f}")
