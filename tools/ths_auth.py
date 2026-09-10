# -*- coding: utf-8 -*-
"""同花顺数据服务凭据读取（可移植：环境变量优先，多平台文件回退）

用法:
    from ths_auth import get_api_key
    KEY = get_api_key()

凭据来源（按优先级）:
    1) 环境变量 HITHINK_FINANCE_API_KEY （跨平台，推荐）
    2) ~/.config/hithink-finance/credentials.env
    3) %APPDATA%/hithink-finance/credentials.env (Windows)
    4) ~/hithink-finance/credentials.env

注意: 请勿将任何 API Key 提交到版本库。详见仓库根目录 CREDENTIALS.md
"""
import os

ENV_VAR = "HITHINK_FINANCE_API_KEY"


def _candidate_paths():
    paths = []
    if os.environ.get("APPDATA"):
        paths.append(os.path.join(os.environ["APPDATA"], "hithink-finance", "credentials.env"))
    paths.append(os.path.expanduser(os.path.join("~", ".config", "hithink-finance", "credentials.env")))
    paths.append(os.path.expanduser(os.path.join("~", "hithink-finance", "credentials.env")))
    return paths


def get_api_key(required=False):
    """读取同花顺 API Key；未配置返回 None（required=True 时抛异常）"""
    env = os.environ.get(ENV_VAR)
    if env and env.strip():
        return env.strip()
    for p in _candidate_paths():
        try:
            with open(p, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith(ENV_VAR + "="):
                        v = line.split("=", 1)[1].strip()
                        if v:
                            return v
        except Exception:
            continue
    if required:
        raise RuntimeError(
            "未找到同花顺凭据：请设置环境变量 %s，或创建凭据文件（详见 CREDENTIALS.md）" % ENV_VAR)
    return None
