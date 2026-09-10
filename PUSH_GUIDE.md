# 推送到 GitHub · 完整指南（Windows）

> 目标：把本目录推送为一个公开仓库。
> 全程约 10 分钟。命令可直接复制（把尖括号内容替换成你自己的）。

---

## 0. 前置准备

1. **安装 Git for Windows**：https://git-scm.com/download/win （一路默认即可）
2. **GitHub 账号**：如不希望与本名关联，用一个新邮箱注册即可

装好后打开 **PowerShell**，输入 `git --version` 能看到版本号即成功。

---

## 1. 隐私设置（重要，先做）

GitHub 提交会把 **邮箱公开**在 commit 记录里。建议用 GitHub 的匿名邮箱：

```powershell
git config --global user.name "JY"
# 去 GitHub → Settings → Emails 找到形如 12345678+username@users.noreply.github.com 的地址
git config --global user.email "<你的noreply邮箱>@users.noreply.github.com"
```

（若不在意邮箱公开，也可以直接用常用邮箱。）

---

## 2. 在 GitHub 网页创建空仓库

1. 右上角 **+ → New repository**
2. **Repository name**：`chanlun-postmortem`
3. **Description**：粘贴 `PUBLISH_NOTES.md` 里的「仓库简介」
4. 选择 **Public**
5. ⚠️ **不要勾选** "Add a README file" / .gitignore / license（保持空仓库，避免首次推送冲突）
6. 点击 **Create repository**，记下页面给出的仓库地址

---

## 3. 本地初始化并提交

在本目录（解压后的根目录，能看到 `README.md`、`chanlun/`）打开 PowerShell：

```powershell
git init
git config core.quotepath false        # 让中文文件名正常显示
git add .
git status                             # ★检查一遍：确认没有 data_cache/、credentials.env、*.zip
git commit -m "缠论策略复盘：严格验证与验收方法论"
git branch -M main
```

**`git status` 这一步务必看一眼**：如果列表里出现了数据文件、密钥文件或大文件，说明 `.gitignore` 没生效，先解决再提交。

---

## 4. 关联远程仓库

```powershell
git remote add origin https://github.com/<你的用户名>/chanlun-postmortem.git
```

---

## 5. 推送

> GitHub 已**禁用密码推送**，必须用 Token 或 GitHub CLI。

### 方式 A：Personal Access Token（推荐）

1. GitHub → **Settings → Developer settings → Personal access tokens → Tokens (classic)**
2. **Generate new token (classic)** → 勾选 **`repo`** 权限 → 生成
3. **立刻复制** token（只显示一次）
4. 回到 PowerShell 推送：

```powershell
git push -u origin main
```
弹出登录框时：
- **Username**：你的 GitHub 用户名
- **Password**：粘贴上一步的 token（不是账号密码）

### 方式 B：GitHub CLI（最省事）

```powershell
winget install GitHub.cli
gh auth login                                    # 按提示用浏览器授权
gh repo create chanlun-postmortem --public --source=. --push
```

一条命令完成"建仓库 + 推送"，可跳过上面第 2、4、5 步。

---

## 6. 推送后完善仓库页面

| 位置 | 操作 |
|---|---|
| **About**（右上齿轮） | 粘贴 `PUBLISH_NOTES.md` 的简介；Topics 填 `quantitative-finance` `backtesting` `look-ahead-bias` `methodology` `negative-results` `chanlun` |
| **置顶说明** | 到 **Issues → New issue** 粘贴《关于本仓库》内容 → 发布后可**Pin** |
| **Release** | Releases → Draft a new release → tag `v1.0` → 粘贴 `PUBLISH_NOTES.md` 的 Release 说明 |

---

## 常见问题

| 现象 | 处理 |
|---|---|
| `remote origin already exists` | `git remote set-url origin <新地址>` |
| 推送被拒（non-fast-forward） | 远程有初始文件：`git pull --rebase origin main` 后再 `git push` |
| 中文文件名显示成 `\344\270\255` | `git config core.quotepath false` |
| 提示文件过大被拒 | 检查是否误提交了 `*.zip`/`*.pkl`：`git rm --cached <文件>` 后重新提交 |
| 想改用匿名账号推送 | `git config user.name/user.email` 改成本地（不加 `--global`），或换 token |

---

## 推送后的检查清单

- [ ] 仓库页面能看到 README（结论先行那段）
- [ ] `docs/` 下 18 个文档都在
- [ ] 没有 `data_cache/`、`credentials.env`、`*.zip`
- [ ] About 与 Topics 已填
- [ ] 置顶说明已 Pin
- [ ] 在 GitHub 上搜索自己的仓库名能搜到（Public 生效）
