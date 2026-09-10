# 数据源与凭据配置

本仓库**不包含任何行情数据**，也不包含任何 API Key。所有数据需使用者自行获取。

## 默认数据源：新浪行情（免费，无需配置）

`data_fetcher.py` 默认使用新浪公开行情接口获取日 K 线，无需任何 Key：

```bash
python run_backtest.py
```

## 可选数据源：同花顺官方数据服务

用于**数据交叉校验**与特色数据（涨跌停池、龙虎榜等）。需自行申请 API Key。

配置方式（二选一，**环境变量优先**）：

1. 环境变量（跨平台、推荐）：
   ```bash
   # Linux/macOS
   export HITHINK_FINANCE_API_KEY=sk-REPLACE_WITH_YOUR_OWN_KEY
   # Windows PowerShell
   $env:HITHINK_FINANCE_API_KEY="sk-REPLACE_WITH_YOUR_OWN_KEY"
   ```

2. 凭据文件（用户级，仅本机可见）：
   ```
   Windows: %APPDATA%\\hithink-finance\\credentials.env
   Linux/macOS: ~/.config/hithink-finance/credentials.env
   内容: HITHINK_FINANCE_API_KEY=sk-REPLACE_WITH_YOUR_OWN_KEY
   ```

## ⚠️ 安全提醒

- **切勿将任何 API Key 提交到版本库**（`.gitignore` 已排除常见凭据文件）
- 推送前建议执行一次扫描（见 `RELEASE_CHECKLIST.md`）
