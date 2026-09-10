# -*- coding: utf-8 -*-
"""检查P2数据字段结构"""
import pickle, time
fin = pickle.load(open('data_cache/hs300_financials.pkl', 'rb'))
px = pickle.load(open('data_cache/hs300_prices.pkl', 'rb'))
mem = pickle.load(open('data_cache/hs300_members.pkl', 'rb'))
print('成员', len(mem), '财务', len(fin), '价格', len(px))
k = list(fin.keys())[0]
e = fin[k]
print('\n样例标的:', k)
inc = e['income'] or []
bal = e['balance'] or []
print('利润表期数:', len(inc), '资产负债表期数:', len(bal))
if inc:
    print('\n利润表字段:', list(inc[0].keys()))
    print('样例值:', {kk: inc[0][kk] for kk in list(inc[0].keys())[:12]})
if bal:
    print('\n资产负债表字段:', list(bal[0].keys()))
    print('样例值:', {kk: bal[0][kk] for kk in list(bal[0].keys())[:12]})
kk = list(px.keys())[0]
print('\n价格样例:', kk, '条数', len(px[kk]))
if px[kk]:
    print('价格字段:', list(px[kk][0].keys()))
    print('首末:', time.strftime('%Y-%m-%d', time.localtime(px[kk][0]['date_ms'] / 1000)),
          time.strftime('%Y-%m-%d', time.localtime(px[kk][-1]['date_ms'] / 1000)))
