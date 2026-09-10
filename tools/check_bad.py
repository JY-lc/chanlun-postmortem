# -*- coding: utf-8 -*-
"""检查价值陷阱标记是否生效"""
import pickle, numpy as np, pandas as pd
import factor_ic2 as fi
import ep_p3

mem, px, fin = fi.load_pool('csi1000')
codes = list(px.keys())
# 统计财务里的亏损标记
n_loss = n_neg = n_valid = 0
for tc in codes[:200]:
    fd = ep_p3.fin_factors_ext(fin.get(tc))
    if fd is None:
        continue
    n_valid += 1
    if fd['LOSS'].any():
        n_loss += 1
    if fd['NEG_EQ'].any():
        n_neg += 1
print(f'抽样200只: 有财务{n_valid} | 历史上出现亏损{n_loss} | 出现负净资产{n_neg}')
# bad 矩阵统计
ep, lnm, bad, ret_exec, month_end, codes2 = ep_p3.build_better('csi1000')
print(f'bad矩阵: 非零占比 {float((bad == 1.0).sum().sum())/bad.notna().sum().sum():.2%}')
print(f'bad矩阵样例(最后一行非零数): {int((bad.iloc[-1] == 1.0).sum())} / {int(bad.iloc[-1].notna().sum())}')
print(f'lnm(市值对数)有效占比: {float(lnm.notna().sum().sum())/lnm.size:.1%}')
print(f'ep有效占比: {float(ep.notna().sum().sum())/ep.size:.1%}')
