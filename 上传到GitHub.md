# 上传到 GitHub（避开"一次 100 个文件"限制）

## 一、为什么会报 "fewer than 100 files"

GitHub **网页拖拽上传**单次上限 100 个文件。Django 项目连同 `.venv` 有两千多个文件，
网页上传必然失败 —— 这不是你仓库的问题，是上传方式选错了。

正确方式：**用 Git 命令行推送**，没有文件数量限制
（限制只有：单文件 ≤ 100MB、仓库建议 ≤ 1GB）。

## 二、本项目已经做好的准备

已在 `D:\pycham-studyproject\HRMS\hrms` 初始化并完成了第一次提交：

- 共 **91 个文件**（只含源码、模板、静态资源、迁移、文档）
- 已通过 `.gitignore` 排除：
  - `.env`（**里面有真实 API Key，绝对不能传**）
  - `.venv/`（虚拟环境，两千多个文件，别人 `pip install -r requirements.txt` 就行）
  - `__pycache__/`、`*.log`、`media/`、`.idea/`
- 已确认 `git ls-files` 里没有 `.env`、没有 `.venv`、没有日志

## 三、你需要做的一步：建一个空仓库

在 GitHub 上点 **New repository**：

- Repository name：随意，例如 `HRMS`
- **不要勾** Add a README / .gitignore / license（勾了会产生一次提交，push 时冲突）
- 建好后复制仓库地址，形如 `https://github.com/你的用户名/HRMS.git`

> 如果你之前那个"人力资源管理系统"仓库里已经用网页传过文件，
> 直接往里 push 会提示 `non-fast-forward`。
> 两种处理：① 换新建的空仓库（最省事）；② 我帮你把远端内容拉下来合并后再推，或覆盖推送。

## 四、推送命令

```powershell
cd D:\pycham-studyproject\HRMS\hrms

git remote add origin https://github.com/你的用户名/HRMS.git
git push -u origin main
```

第一次 push 会弹 GitHub 登录窗口（浏览器授权），登录后即完成。

以后每次改完代码：

```powershell
git add -A
git commit -m "说明这次改了什么"
git push
```

## 五、常见问题

**1. 推送时提示 `Authentication failed`**
用 HTTPS 地址时，Windows 会弹 Git Credential Manager 登录窗；
若一直失败，可改用 SSH（需先在 GitHub 配 SSH Key），或改用 Personal Access Token。

**2. 提示某个文件 `exceeds GitHub's file size limit of 100.00 MB`**
不要把 `media/`、`.venv/`、压缩包提交进去；
已提交过的话需要 `git rm --cached` 后重新提交（历史里仍会留，要彻底清需改写历史）。

**3. 别人 clone 下来跑不起来**
正常，因为 `.env` 和 `.venv` 没上传。让对方：

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt
copy .env.example .env      # 然后填自己的 AI_API_KEY
python manage.py migrate
python manage.py init_data
python manage.py seed_knowledge
python manage.py runserver
```

## 六、安全提醒

`.env` 里的 Key 曾经在聊天截图里出现过，上传前确认它没被跟踪（已确认）；
如果仍有顾虑，答辩后去硅基流动后台把 Key 删掉重建，只改本地 `.env` 一行。
