# -*- coding: utf-8 -*-
"""
一键验收脚本（6道门槛）
========================
用法:
    python tools/acceptance.py                # 用当前config+58只池跑可自动化的门槛
    python tools/acceptance.py --ratio 0.02   # 指定单笔目标风险(可选)

可自动化门槛: ①确认滞后状态 ②成本敏感(0/0.1/0.3%) ③β对照(池等权持有)
需外部脚本的门槛: ④样本外(run_walkforward.py) ⑤显著性(mc_confirm.py) ⑥多重检验(试验日志)
输出: acceptance_report.json + 控制台结论
"""
import os, sys, json, io, contextlib, importlib, pickle, time, argparse
from datetime import datetime

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)  # 项目根(config.py所在)


def _find_cache():
    """兼容部署布局(项目根/data_cache)与沙箱布局(上一级/data_cache)"""
    for root in (_ROOT, os.path.dirname(_ROOT)):
        p = os.path.join(root, 'data_cache')
        if os.path.exists(os.path.join(p, 'stock_data.pkl')):
            return p
    return os.path.join(_ROOT, 'data_cache')


CACHE = _find_cache()
LOG = os.path.join(os.path.dirname(CACHE) if not os.path.exists(os.path.join(_ROOT, 'data_cache')) else _ROOT,
                   'experiments_log.jsonl')


def record_experiment(name, note=''):
    """记录一次试验(防数据挖掘); 返回历史试验次数"""
    rec = {'ts': datetime.now().isoformat(), 'name': name, 'note': note}
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    n = sum(1 for _ in open(LOG, encoding='utf-8'))
    return n


def bh_threshold(p, n_tests, alpha=0.05):
    """Bonferroni 校正后的显著性阈值(保守)"""
    return alpha / max(n_tests, 1)


def load_pool():
    with open(os.path.join(CACHE, 'stock_data.pkl'), 'rb') as f:
        sd = pickle.load(f)
    with open(os.path.join(CACHE, 'index.pkl'), 'rb') as f:
        idx = pickle.load(f)
    return sd, idx


def run_engine(sd, idx, slippage=None, confirm=None):
    import config
    importlib.reload(config)
    if slippage is not None:
        config.USE_SLIPPAGE = True
        config.SLIPPAGE_RATE = slippage
    if confirm is not None:
        config.USE_CONFIRMATION_DELAY = confirm
    import chanlun.backtest as bt
    importlib.reload(bt)
    e = bt.BacktestEngine(use_market_env=True, execution_mode=config.DEFAULT_EXECUTION_MODE)
    e.set_market_env(idx)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        r = e.run(sd)[0]
    out = buf.getvalue()
    conf_line = next((l.strip() for l in out.split('\n') if '确认制' in l), '')
    return r, conf_line


def equal_weight_beta(sd):
    rets = []
    for s, (name, df) in sd.items():
        if df is None or len(df) < 100:
            continue
        r = df['收盘'].iloc[-1] / df['收盘'].iloc[0] - 1
        days = (pd.to_datetime(df['日期'].iloc[-1]) - pd.to_datetime(df['日期'].iloc[0])).days
        if days > 0:
            rets.append((1 + r) ** (365.25 / days) - 1)
    return float(np.mean(rets)) if rets else float('nan')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--name', default='unknown_strategy')
    ap.add_argument('--skip-log', action='store_true')
    a = ap.parse_args()
    report = {'strategy': a.name, 'ts': datetime.now().isoformat(), 'gates': {}}

    print('===== 验收报告: %s =====' % a.name)
    sd, idx = load_pool()

    # 门槛1: 确认制状态
    r_base, conf_line = run_engine(sd, idx)
    import config
    print(f"\n[① 确认滞后] USE_CONFIRMATION_DELAY={config.USE_CONFIRMATION_DELAY}")
    print(f"   {conf_line or '(未启用确认制)'}")
    gate1 = bool(config.USE_CONFIRMATION_DELAY)
    report['gates']['confirmation_delay'] = {'pass': gate1, 'detail': conf_line}

    # 门槛2: 成本敏感
    print('\n[② 成本敏感] 滑点 0% / 0.1% / 0.3%')
    cost = {}
    for lab, sp in [('0%', 0.0), ('0.1%', 0.001), ('0.3%', 0.003)]:
        r, _ = run_engine(sd, idx, slippage=sp)
        cost[lab] = {'annual': r.annual_return, 'sharpe': r.sharpe_ratio, 'dd': r.max_drawdown}
        print(f"   滑点{lab}: 年化{r.annual_return:+.2%} 夏普{r.sharpe_ratio:+.2f} 回撤{r.max_drawdown:.2%}")
    gate2 = cost['0.3%']['annual'] > 0
    report['gates']['cost_sensitivity'] = {'pass': gate2, 'detail': cost}

    # 门槛3: β对照
    beta = equal_weight_beta(sd)
    excess = r_base.annual_return - beta
    print(f'\n[③ β对照] 策略年化{r_base.annual_return:+.2%} vs 池等权持有{beta:+.2%} → 超额{excess:+.2%}')
    gate3 = excess > 0.02  # 要求至少超越β 2pp
    print(f"   判定: {'✅ 通过(超额>2pp)' if gate3 else '❌ 未通过(未显著超越β)'}")
    report['gates']['beta_benchmark'] = {'pass': gate3, 'strategy': r_base.annual_return,
                                         'beta': beta, 'excess': excess}

    # 门槛4/5/6: 提示
    print('\n[④ 样本外] 请运行: python run_walkforward.py')
    print('[⑤ 显著性] 请运行: python mc_confirm.py prepare && run <0> <30>')
    n_tests = 0 if a.skip_log else record_experiment(a.name, 'acceptance run')
    thr = bh_threshold(0.05, n_tests)
    print(f'[⑥ 多重检验] 累计试验次数={n_tests}; Bonferroni校正后显著性阈值 p<{thr:.5f}')
    report['gates']['multiple_testing'] = {'n_tests': n_tests, 'bh_alpha': thr}

    passed = sum(1 for g in report['gates'].values() if isinstance(g, dict) and g.get('pass'))
    print(f'\n===== 自动门槛通过 {passed}/3 ; 外部门槛(4/5/6)需按提示运行 =====')
    with open(os.path.join(CACHE, 'acceptance_report.json'), 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print('已保存 data_cache/acceptance_report.json')


if __name__ == '__main__':
    main()
