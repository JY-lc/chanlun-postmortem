# 发布前检查清单

推送 GitHub 之前，请逐项确认。

## 1. 敏感信息（必须）

- [ ] 全文搜索 `sk-`、`api_key`、`token`、`password`：应只出现**变量名/占位符**，无真实值
- [ ] 搜索个人路径（如 `C:\\Users\\<YOUR_USERNAME>`）与用户名
- [ ] 确认 `release/` 内无 `data_cache/`、`data_collect/`、`*.pkl`（行情数据）
- [ ] 确认无 `.cred_tmp`、`credentials.env` 等凭据文件
- [ ] 本地命令验证：
  ```bash
  # 建议用 gitleaks / trufflehog 或简单扫描
  grep -rn "sk-\|api_key\|password" . --include="*.py" --include="*.md"
  ```

## 2. 版权与第三方内容

- [ ] 确认策略代码为原创（本仓库已确认：由作者从 0 迭代）
- [ ] 确认仓库内**不含**第三方项目的源代码或 README（czsc / chan.py 等仅作思路参考）
- [ ] 确认不打包任何行情数据（数据源版权约束）

## 3. 文档

- [ ] README 首段即为**结论与免责声明**（避免被误当策略使用）
- [ ] `docs/INDEX.md` 索引与文件对应
- [ ] 历史阶段性文档（如 `docs/16_V5.3.2_变更说明.md`）已标注"阶段性成果，最终结论见 01/02"

## 4. 元信息

- [ ] LICENSE 中的版权人已填写（或选择匿名）
- [ ] 是否使用匿名账号 / 匿名邮箱提交（如需隐藏身份）
- [ ] 仓库名与描述符合"复盘/方法论"定位（**不要**用"缠论策略"作为卖点）
- [ ] 建议话题标签：`quantitative-finance` `backtesting` `look-ahead-bias` `methodology` `negative-results`

## 5. 推送

```bash
git init
git add .
git commit -m "缠论策略复盘：严格验证与验收方法论"
git branch -M main
git remote add origin <你的仓库地址>
git push -u origin main
```
