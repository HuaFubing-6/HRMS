# 企业员工管理系统（HRMS）

> 课程设计项目：一套完整的员工管理后台 + 一个基于大模型的「智能员工助手」模块。
> 技术栈：**Django 5.2 · MySQL 8 · Bootstrap 3.4 · jQuery 3.6 · ECharts 5 · OpenAI 兼容 SDK（硅基流动）**

---

## 一、项目简介

系统采用 **Django + 自研 RBAC 中间件** 的经典分层结构：

- 认证与权限：用户 → 角色 → 权限（URL 级），再由 `scope.py` 做第二层「数据范围」控制
- 业务模块：部门 / 员工 / 考勤 / 薪资 / 公告 / 任务 / 统计图表
- 智能模块：招聘 JD 生成、制度知识问答、数据智能点评、多轮对话、流式输出

界面沿用 EMS 模板风格：`views/` 按业务拆包、公共能力进 `utils/`、模板统一继承 `layout.html`、
表单页复用 `change.html`，全站右下角还有一个常驻的悬浮 AI 助手。

---

## 二、功能清单

### 2.1 基础业务（课程设计 T1–T10）

| 模块 | 功能 |
|---|---|
| 登录认证 | 图形验证码、密码 PBKDF2 哈希存储、注销、演示用「切换账号」 |
| RBAC | 用户-角色-权限三级模型；中间件逐请求校验 URL 权限；导航与按钮按权限显隐 |
| 数据范围 | 部门管理员只看本部门；普通员工只看自己的薪资与考勤；接口内二次校验防越权 |
| 部门 | 增删改查 + 分页 |
| 员工 | CRUD + ModelForm 校验（年龄/手机号正则+唯一）+ 姓名模糊搜索 + 部门筛选 + 头像上传 |
| 考勤 | 上下班时间自动判定按时/迟到/早退/缺勤，罚款按制度常量自动计算 |
| 薪资 | 基本工资 + 奖金 - 扣款 → 实发自动计算；按月份/员工筛选；月度汇总 |
| 公告 | 发布、置顶、标题搜索、分页 |
| 任务 | AJAX 异步提交 + JSON 返回，校验失败不刷新页面也能回显 |
| 数据可视化 | ECharts 部门人数饼图、各月薪资趋势折线（AJAX 取 JSON） |
| 性能 | `select_related` 消除列表页 N+1 查询 |

### 2.2 智能助手（大模型课程设计 T1–T7）

| 编号 | 能力 | 实现要点 | 状态 |
|---|---|---|---|
| T1 | 环境与 LLMClient 封装 | `.env` 配置、懒加载单例、异常统一翻译为中文 | ✅ |
| T2 | 招聘 JD 生成 | 三段式提示词，固定输出【岗位职责】【任职要求】【薪资范围】 | ✅ |
| T3 | 制度知识库问答 | 关键词检索 + 命中加权排序；**检索不到就不调模型，直接回答「不知道」** | ✅ |
| T4 | 数据智能点评 | 考勤/薪资先转成一句人话再喂模型；按数据范围过滤 + 接口内二次鉴权 | ✅ |
| T5 | 多轮对话 | 历史存 session，保留最近 6 轮；对话同时挂制度检索 | ✅ |
| T6 | 安全与健壮性 | 输入清洗、3 秒间隔 + 每日 50 次限流、全站 CSRF 保留、错误不 500 | ✅ |
| T7 | SSE 流式输出 | `StreamingHttpResponse`，`data:{json}\n\n` 帧，前端 `fetch + ReadableStream` 逐字渲染 | ✅ |

---

## 三、快速开始

### 3.1 环境要求

| 项目 | 版本 |
|---|---|
| Python | 3.10+（本项目在 3.12.5 上开发） |
| MySQL | 8.0+ |
| 依赖 | 见 `requirements.txt`（Django 5.2 / PyMySQL / Pillow / openai / python-dotenv） |

### 3.2 建库

```sql
CREATE DATABASE qiyerenwu DEFAULT CHARSET utf8mb4;
```

库名与账号在 `hrms/settings.py` 的 `DATABASES` 中，默认：

```python
"NAME": "qiyerenwu",  "USER": "root",  "PASSWORD": "123456",  "HOST": "127.0.0.1", "PORT": "3306"
```

> 驱动用纯 Python 的 **PyMySQL**（已在 `hrms/__init__.py` 注册），不需要编译 `mysqlclient`。

### 3.3 安装依赖

```powershell
cd D:\pycham-studyproject\HRMS\hrms

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

> 也可以直接用本机已有的 Python 环境安装依赖，只要能 `import django` 即可。

### 3.4 配置大模型（AI 模块必需）

复制模板并填入自己的 Key：

```powershell
copy .env.example .env
```

`.env` 内容：

```ini
AI_API_KEY=sk-你的硅基流动Key
AI_BASE_URL=https://api.siliconflow.cn/v1
AI_MODEL=Qwen/Qwen2.5-7B-Instruct
```

> `.env` 已被 `.gitignore` 排除，**不要提交到仓库**。
> 免费模型可在 [硅基流动](https://cloud.siliconflow.cn) 申请；换服务商只需改 `AI_BASE_URL` 与 `AI_MODEL`。

### 3.5 迁移与初始化

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py init_data        # 建权限(43条)/角色/超管账号
.\.venv\Scripts\python.exe manage.py demo_data        # 演示数据：6部门/18员工/54薪资/5公告
.\.venv\Scripts\python.exe manage.py seed_knowledge    # 8 条制度，供问答检索
```

### 3.6 验证模型连通

```powershell
.\.venv\Scripts\python.exe manage.py ai_check
# 输出 BASE_URL / MODEL / 打码后的 KEY，再打印模型回答与耗时
```

### 3.7 启动

```powershell
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

浏览器打开 <http://127.0.0.1:8001/login/>

> 默认端口 8000；若本机 8000 已被占用（例如同时装着另一个 HRMS），用 8001。

---

## 四、默认账号

| 账号 | 密码 | 角色 |
|---|---|---|
| 盖亚 | 123 | 超级管理员（全部权限） |

```powershell
# 重置已有账号密码
python manage.py init_data --reset
# 自定义账号密码
python manage.py init_data --username 你的名字 --password 你的密码 --reset
```

部门管理员 / 普通员工可在「用户管理」中新建并分配角色；
普通员工的 AI 权限只开放「制度问答」和「对话助手」，招聘 JD 与数据点评属 HR 工作，不下放。

---

## 五、AI 模块接口

统一约定：成功 `{"status": true, "data": ...}`，失败 `{"status": false, "msg": "中文提示"}`。

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/ai/jd/` | 招聘 JD 页面 |
| POST | `/ai/jd/generate/` | 生成 JD（参数 `title` / `depart` / `years`） |
| GET | `/ai/qa/` | 制度问答页面 |
| POST | `/ai/qa/ask/` | 提问（参数 `question`），返回 `data` 与 `sources`（依据制度标题） |
| GET | `/ai/comment/` | 数据点评页面 |
| POST | `/ai/comment/generate/` | 生成点评（参数 `employee_id` / `month`），返回 `data` 与 `raw`（喂给模型的原始数据） |
| GET | `/ai/chat/` | 对话助手页面（带历史） |
| POST | `/ai/chat/ask/` | 多轮对话（非流式） |
| POST | `/ai/chat/clear/` | 清空对话历史 |
| POST | `/ai/chat/stream/` | 流式对话（SSE，帧格式 `data:{json}\n\n`，结束 `data:[DONE]`） |

**前端可用的三处入口**：导航「智能助手」下拉、`/ai/chat/` 页面、全站右下角悬浮窗（`ai/float.html`）。

**配置项**（`hrms/settings.py` 末尾，可由 `.env` 覆盖）：

| 配置 | 默认 | 说明 |
|---|---|---|
| `AI_TIMEOUT` | 20 | 单次请求超时（秒） |
| `AI_MAX_INPUT` | 500 | 输入字数上限 |
| `AI_MIN_INTERVAL` | 3 | 同一会话两次调用最小间隔（秒） |
| `AI_DAILY_LIMIT` | 50 | 单会话每日调用上限 |
| `AI_OFFLINE_DEMO` | False | 置 True 时返回预置文本，仅用于断网演示 |

---

## 六、目录结构

```
hrms/
├── manage.py
├── requirements.txt
├── .env.example                # AI 配置模板（.env 自己填，不上传）
├── AI模块说明.md                # AI 模块功能、验收记录、答辩要点
├── AI模块实施计划.md            # 分阶段实施计划
├── 上传到GitHub.md              # 如何避开网页上传 100 文件限制
├── 本机运行说明.md              # 本机环境与踩坑记录
├── 答辩讲解手册.md              # 代码讲解顺序
├── hrms/                       # 项目配置层
│   ├── settings.py             # 数据库 / 中间件 / 模板 / AI_* 配置
│   ├── urls.py                 # 总路由（include app01.urls）
│   └── __init__.py             # 注册 PyMySQL
└── app01/                      # 业务应用层
    ├── models.py               # 部门/员工/考勤/薪资/公告/任务/用户/角色/权限/制度(Knowledge)
    ├── urls.py                 # 业务路由（含 10 条 /ai/ 路由）
    ├── views/                  # 视图按业务拆包
    │   ├── account.py          # 登录 / 注销 / 切换账号
    │   ├── dashboard.py        # 首页统计
    │   ├── department.py       # 部门 CRUD
    │   ├── employee.py         # 员工 CRUD（头像上传）
    │   ├── attendance.py       # 考勤（状态自动判定）
    │   ├── salary.py           # 薪资（实发自动计算）
    │   ├── notice.py           # 公告
    │   ├── task.py             # 任务（AJAX）
    │   ├── chart.py            # ECharts 数据接口
    │   ├── rbac.py             # 用户 / 角色 / 权限
    │   └── ai.py               # 4 页面 + 5 JSON 接口 + 1 SSE 接口 ★
    ├── utils/                  # 公共能力包
    │   ├── ai.py               # LLMClient / 异常翻译 / 输入清洗 / 限流 ★
    │   ├── prompts.py          # 四套提示词（JD / 问答 / 点评 / 对话） ★
    │   ├── retrieval.py        # 制度关键词检索 + 上下文拼接 ★
    │   ├── scope.py            # 数据范围：部门管理员 / 普通员工
    │   ├── bootstrap.py        # 表单统一样式基类
    │   ├── form.py             # 所有 ModelForm
    │   ├── pagination.py       # 分页组件（保留搜索条件）
    │   ├── encrypt.py          # 密码哈希
    │   ├── check_code.py       # 验证码入口
    │   └── captcha.py          # 验证码绘制
    ├── middleware/
    │   └── rbac.py             # URL 级权限中间件
    ├── templates/app01/
    │   ├── layout.html         # 全局布局（导航按权限显隐 + 悬浮助手入口）
    │   ├── change.html         # 通用表单页（新建/编辑共用）
    │   ├── login.html  index.html
    │   ├── ai/                 # jd / qa / comment / chat / float ★
    │   └── department/ employee/ attendance/ salary/ notice/ task/ role/ user/ chart/
    ├── templatetags/
    │   └── filters.py          # has_perm 等模板过滤器
    ├── management/commands/
    │   ├── init_data.py        # 权限 43 条 + 三个角色 + 超管
    │   ├── demo_data.py        # 演示数据
    │   ├── seed_knowledge.py   # 8 条制度种子 ★
    │   └── ai_check.py         # T1 验收命令 ★
    ├── migrations/             # 含 0005_knowledge
    ├── tests.py                # 基础业务测试
    └── tests_ai.py             # AI 模块 26 个单元测试（不联网） ★
```

> 模板查找依赖 `TEMPLATES["APP_DIRS"] = True`（`DIRS` 留空）：
> 视图写 `render(request, "app01/xxx.html")`，模板写 `{% extends "app01/layout.html" %}`。

---

## 七、设计要点（答辩可讲）

1. **权限三层**：中间件按 URL 校验 → 模板 `has_perm` 控制按钮 → 视图用 `scope.py` 收敛数据行。
   三层各司其职：中间件防"直接敲 URL"，模板防"按钮摆着却点不动"，视图防"接口改参数越权"。
2. **ORM 的实际用法**：`select_related` 消除 N+1；`filter(...)` + `Q()` 组合检索；
   DecimalField 存金额避免浮点误差；`save()` 里根据上下班时间自动判定考勤状态。
3. **AJAX**：任务模块与 AI 全部走 JSON 接口，前端只判断 `status`，失败只弹提示不刷新页面。
4. **提示词三段式**：`system` 定角色与边界，`user` 定任务与输出格式，格式写死便于前端渲染。
5. **最小可用 RAG**：8 条制度用"抽词 + icontains + 命中加权"，不引入向量库——
   数据规模决定技术选型，属于可解释的取舍。
6. **检索不到不调模型**：直接返回「不知道」，既省额度，又从机制上杜绝编造制度条款。
7. **数据点评的两次过滤**：页面按数据范围筛选员工，接口里再校验一次 `_can_comment`；
   喂模型前把考勤/薪资拼成一句人话，并把原料回传前端供核对。
8. **SSE 的错误处理**：响应头发出后无法改状态码，所以在生成器内部捕获异常，
   发 `{"error": ...}` 帧由前端渲染；断流自动退回普通接口。
9. **不写 `@csrf_exempt`**：全站 CSRF 保持开启，前端带 `X-CSRFToken`，
   比"图省事关掉 CSRF"更安全，也是一处可讲的取舍。

---

## 八、测试与验收

```powershell
# AI 单元测试（26 项，不联网、不消耗额度）
.\.venv\Scripts\python.exe manage.py test app01.tests_ai

# 基础业务测试
.\.venv\Scripts\python.exe manage.py test app01

# T1 连通性验收（会真实调一次模型）
.\.venv\Scripts\python.exe manage.py ai_check "用一句话介绍你自己"
```

已实测通过的场景：

- 招聘 JD：输入「后端开发工程师」→ 输出三段式文案
- 制度问答：「迟到一次扣多少钱」→「迟到一次罚款 50 元。依据：《考勤管理办法》」
- 制度问答（负向）：「公司的股票代码是多少」→「不知道」（未调用模型）
- 数据点评：按员工+月份生成一句点评 + 一条建议，并回显喂给模型的数据
- 多轮对话：保留上下文，可清空；对话同样挂制度检索
- 流式输出：`text/event-stream`，单次 16–25 帧逐块到达，`[DONE]` 正常结束

---

## 九、常见问题

**1. 启动报 `No module named 'django'`**
说明用错了 Python 解释器。请用项目虚拟环境：
`.\.venv\Scripts\python.exe manage.py runserver`。

**2. 8000 端口被占用**
改 8001：`manage.py runserver 127.0.0.1:8001`。

**3. 页面改了但浏览器没变化**
先 `Ctrl+F5` 强刷；若服务是 `--noreload` 启动且改的是 Python 代码，需重启服务。

**4. AI 页面提示「AI 未配置」**
`.env` 没读到。确认文件在 `manage.py` 同目录、名为 `.env`、内容有 `AI_API_KEY=`。

**5. AI 提示「Key 无效 / 请 10 秒后重试」**
前者是 Key 错或过期；后者是免费模型限流，属正常现象，稍等重试即可。

**6. 制度问答总是「不知道」**
检查是否执行过 `seed_knowledge`；检索依赖标题/正文/`keywords` 三个字段，可在后台补充同义词。

**7. clone 下来跑不起来**
正常。`.env` 与 `.venv` 不会上传，按「3.3–3.7」重新安装、建库、迁移、初始化即可。

**8. GitHub 网页上传提示「fewer than 100 files」**
网页上传有 100 文件上限，用 Git 命令行推送，详见 `上传到GitHub.md`。

---

## 十、文档索引

| 文档 | 内容 |
|---|---|
| `AI模块说明.md` | AI 模块完成情况、文件清单、接口、实测记录、已知限制 |
| `AI模块实施计划.md` | 分阶段实施计划与验收清单 |
| `本机运行说明.md` | 本机环境、端口、踩坑与版本更新记录 |
| `答辩讲解手册.md` | 按文件顺序的代码讲解提纲 |
| `上传到GitHub.md` | 推送流程、认证问题、安全提醒 |

---

## 十一、安全说明

- `.env`、`.venv`、`media/`、日志均被 `.gitignore` 排除，仓库不含任何密钥或用户数据；
- 模型异常统一翻译为中文提示，不向页面回显堆栈、URL 或 Key 片段；
- 输入统一做长度、控制字符、纯符号校验，并有会话级限流；
- 数据范围与权限在**视图层二次校验**，不信任前端传参。

> 演示用 Key 请勿硬编码进代码；如曾在公开场合暴露，建议到服务商后台重置后只更新本地 `.env`。
