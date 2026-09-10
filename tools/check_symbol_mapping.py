# -*- coding: utf-8 -*-
"""
扩池前代码映射自查工具
======================
用法:
  python tools/check_symbol_mapping.py                  # 检查当前回测池(58只)全部代码映射
  python tools/check_symbol_mapping.py 430047 920xxx 600519 159915   # 自查拟扩池代码(传6位代码)

作用:
  1. 断言代码段归属(沪/深/北)与 _get_sina_symbol 解析一致, 防止 000001 类同码冲突
  2. 识别新浪不支持的北交所/未知代码段
  3. 输出代码段规则表, 扩池前对照

注意: 本工具只做本地规则检查(不联网)。需要网络确认数据可达性请配合:
      python tools/verify_data_sources.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from data_fetcher import _get_sina_symbol, _INDEX_SINA_MAP, _is_bse_symbol
import config

# 代码段归属表: (前缀, 交易所, 类型)
SEG_RULES = [
    (('600', '601', '603', '605'), '上交所', '主板A股'),
    (('688',), '上交所', '科创板'),
    (('900',), '上交所', 'B股'),
    (('510', '511', '512', '513', '515', '516', '517', '518', '560', '561', '562', '563', '588'), '上交所', 'ETF'),
    (('500',), '上交所', '封闭式基金'),
    (('000', '001', '002', '003'), '深交所', '主板A股'),
    (('300', '301'), '深交所', '创业板'),
    (('200',), '深交所', 'B股'),
    (('159',), '深交所', 'ETF'),
    (('160', '161', '162', '163', '164', '165', '166', '168', '169', '180', '181', '182', '183', '184'), '深交所', 'LOF/封基'),
    (('43', '83', '87', '88'), '北交所', '股票(新浪不支持)'),
    (('920',), '北交所', '股票-新代码段(新浪不支持)'),
]


def classify(symbol: str):
    """返回 (交易所, 类型, 是否北交所/未知)"""
    for prefixes, ex, typ in SEG_RULES:
        for p in prefixes:
            if symbol.startswith(p):
                return ex, typ
    return '未知', '无法识别的代码段'


def check_one(symbol: str):
    ex, typ = classify(symbol)
    if ex == '北交所':
        sina = f'[不支持] {symbol} 属北交所({typ})'
        ok = False
    elif ex == '未知':
        sina = f'[错误] {symbol} 无法识别'
        ok = False
    else:
        try:
            sina = _get_sina_symbol(symbol)
            ok = True
        except ValueError as e:
            sina = f'[错误] {e}'
            ok = False
    # 与指数映射冲突检查
    conflict = ''
    if symbol in _INDEX_SINA_MAP:
        conflict = f' ⚠️ 与指数代码同码! (指数映射:{_INDEX_SINA_MAP[symbol]})'
    return ex, typ, sina, ok, conflict


def main():
    args = [a for a in sys.argv[1:] if len(a) == 6 and a.isdigit()]
    pool = config.BACKTEST_STOCKS
    if args:
        targets = args
    else:
        targets = list(pool.keys())

    print(f'{"代码":8}{"交易所":6}{"类型":12}{"新浪映射":18}{"状态":6}备注')
    n_ok = 0
    for s in targets:
        ex, typ, sina, ok, conflict = check_one(s)
        name = pool.get(s, '(扩池候选)')
        if ok:
            n_ok += 1
            st = 'OK'
        else:
            st = '!!'
        print(f'{s:8}{ex:6}{typ:12}{sina:18}{st:6}{name}{conflict}')
    print(f'\n检查 {len(targets)} 个, 通过 {n_ok} 个')
    if n_ok < len(targets):
        print('存在不通过项：扩池前必须处理（北交所需换数据源或放弃；未知段需先补充规则）')


if __name__ == '__main__':
    main()
