# AI 智能员工助手 —— 实施计划

> 依据：《基于大模型的智能员工助手 课程设计任务书》+《大模型功能核心代码参考.md》
> 落地项目：`D:\pycham-studyproject\qiyerenwu\hrms`（朋友新版，已跑通：19 张表 / 33 条权限 / 盖亚 123）
> 范围：必做 T1–T4 + 选做 T5–T7（全做）

---

## 一、目标与验收口径

把大模型当成"会写字的接口"：**封装调用 → 写提示词 → 注入资料 → 页面渲染**。全项目只维护一个 `LLMClient.chat()`，四个功能复用它。

| 任务 | 交付物 | 验收标准（可演示） |
|---|---|---|
| T1 环境与 LLMClient | `app01/utils/ai.py`、`management/commands/ai_check.py` | 一条命令打印模型回答；Key 不在代码里 |
| T2 招聘 JD | `/ai/jd/` 页面 + `POST /ai/jd/` | 输入"后端开发工程师"，页面不刷新出现"职责/要求/薪资"三段 |
| T3 制度问答 | `Knowledge` 表 + `/ai/qa/` + `POST /ai/qa/` | 问"迟到怎么扣钱"答得对且给出依据条目；问"公司股票代码"答"不知道" |
| T4 数据点评 | `/ai/comment/` + `POST /ai/comment/` | 选员工+月份，出一句 ≤50 字点评；普通员工只能点评自己 |
| T5 多轮对话 | `/ai/chat/` + `POST /ai/chat/` | 连问两轮，"那如果缺勤呢"能接上上文 |
| T6 安全健壮性 | 输入过滤 / 限流 / 超时 / 兜底 | 断网、错 Key、超长输入都不出 500，页面给中文提示 |
| T7 流式输出 | `POST /ai/chat/stream/`（SSE） | 回答逐字出现，不是等几秒一次性弹出 |

---

## 二、现状盘点（哪些能直接用）

| 现有资产 | 位置 | 复用方式 |
|---|---|---|
| RBAC 中间件（URL 级拦截） | `app01/middleware/rbac.py` | AI 页面只要在权限表里加 URL 就自动受控，不用写装饰器 |
| 数据范围 | `app01/utils/scope.py`（`is_dept_admin` / `is_plain_employee`） | T4 点评按角色过滤，防止普通员工看别人工资 |
| 表单基类 | `app01/utils/form.py`（`BootStrapModelForm`） | 若加"知识条目"录入页可直接套 |
| 模板继承 | `templates/app01/layout.html` | 新页面继承，导航加"智能助手"下拉 |
| 前端栈 | `static/vendor/{bootstrap,jquery}` | AJAX 用 jQuery，流式用原生 fetch |
| 权限初始化 | `management/commands/init_data.py` | 加 5 条权限，重跑幂等 |
| 演示数据 | `management/commands/demo_data.py` | 新增 `seed_knowledge` 造 8 条制度 |

**缺口（要新建）**：`utils/ai.py`、`utils/prompts.py`、`utils/retrieval.py`、`views/ai.py`、`Knowledge` 模型与迁移、4 个模板、5 条路由/权限、依赖 `openai`。

---

## 三、总体技术方案

### 3.1 模型与接口

| 项 | 值 |
|---|---|
| 服务 | 硅基流动 SiliconFlow（OpenAI 兼容） |
| `AI_BASE_URL` | `https://api.siliconflow.cn/v1` |
| `AI_MODEL` | `Qwen/Qwen2.5-7B-Instruct`（免费，32K 上下文） |
| `AI_API_KEY` | 环境变量，禁止入库/入 Git |
| SDK | `openai`（支持 stream） |
| 超时 | 20 s；失败不重试（避免页面卡住） |

### 3.2 配置读取（settings.py 末尾追加）

```python
import os
AI_API_KEY  = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.siliconflow.cn/v1")
AI_MODEL    = os.environ.get("AI_MODEL", "Qwen/Qwen2.5-7B-Instruct")
AI_TIMEOUT  = 20          # 秒
AI_MAX_INPUT = 500        # 单次输入字数上限
AI_MIN_INTERVAL = 3       # 同一会话两次调用最小间隔（秒）
AI_DAILY_LIMIT = 50       # 每会话每日调用上限（演示级）
```

本机开发用 PyCharm Run Configuration 的 Environment variables 填三个键值最省事；也可写 `.env` 并用 `python-dotenv` 读（`.env` 进 `.gitignore`，只提交 `.env.example`）。

### 3.3 一次请求链路（答辩要能画出来）

```
浏览器 → CSRF → RbacMiddleware（URL 权限）→ views/ai.py
       → 输入过滤（长度/字符）→ 限流（session 时间戳）
       → retrieval.py 查 Knowledge（仅 T3）
       → prompts.py 拼三段式提示词
       → LLMClient.chat() → 硅基流动 /chat/completions
       → 异常兜底 → JsonResponse / StreamingHttpResponse
```

---

## 四、数据模型与权限

### 4.1 Knowledge 表（T3 的依据来源）

| 字段 | 类型 | 说明 |
|---|---|---|
| `title` | CharField(128) | 制度名，如"考勤管理办法" |
| `content` | TextField | 正文，命中后整段注入提示词 |
| `category` | CharField(32) | 考勤/报销/请假/薪酬 |
| `keywords` | CharField(128) | 人工补充检索词，解决"迟到"命中"考勤"的缺口 |
| `is_active` | BooleanField=True | 停用条目不参与检索 |
| `create_time` | DateTimeField(auto_now_add) | 审计 |

迁移：`0005_knowledge.py`，不影响现有表，`migrate` 直接补。

### 4.2 权限与导航

`init_data.py` 追加 5 条权限（现有 `get_or_create(url=...)` 逻辑，重跑幂等）：

| 权限名 | URL | 给谁 |
|---|---|---|
| 招聘JD生成 | `/ai/jd/` | 超管、部门管理员 |
| 制度问答 | `/ai/qa/` | 三个角色全给 |
| 数据点评 | `/ai/comment/` | 超管、部门管理员 |
| 对话助手 | `/ai/chat/` | 三个角色全给 |
| 流式对话 | `/ai/chat/stream/` | 三个角色全给 |

`layout.html` 导航加下拉：

```
智能助手 ▾
  ├─ 招聘 JD 生成   /ai/jd/
  ├─ 制度问答       /ai/qa/
  ├─ 数据点评       /ai/comment/
  └─ 对话助手       /ai/chat/
```

模板里用现有 `{% if request|has_perm:"/ai/qa/" %}` 控制显隐，与其它模块一致。

---

## 五、分阶段实施（约 6 个半天）

### P0 环境准备（0.5 h）

- `pip install openai python-dotenv`，`requirements.txt` 追加。
- 环境变量：`AI_API_KEY` / `AI_BASE_URL` / `AI_MODEL`（PyCharm Run Configuration 或系统变量）。
- 网络探测：带 Key 请求 `https://api.siliconflow.cn/v1/models`，确认连通与额度。
- 产出 `.env.example`（只有变量名与占位值）。

**验收**：探测请求返回 200。

### P1 T1：LLMClient 封装（1 h）

`app01/utils/ai.py`：

| 方法 | 作用 |
|---|---|
| `LLMClient.chat(prompt, system=None, temperature=0.7)` | 单轮，返回纯文本 |
| `LLMClient.chat_messages(messages)` | 多轮（T5） |
| `LLMClient.stream(messages)` | 生成器，逐块 yield（T7） |
| `LLMClient.available()` | Key 是否配置，页面据此提示 |

要点：
- 懒加载单例客户端，同进程只建一次。
- 异常统一转 `LLMError`（中文 msg），视图层不写裸 `except`。
- 未配 Key 时不发请求，直接抛"AI 未配置，请设置 AI_API_KEY"。

`management/commands/ai_check.py`：`python manage.py ai_check "用一句话介绍你自己"` 打印回答与耗时，作为 T1 的"测试"证据。

**验收**：命令输出正常；断网时给中文提示而不是 traceback。

### P2 T2：招聘 JD（1 h）

- `utils/prompts.py`：`JD_SYSTEM` + `build_jd_prompt(title, dept="", years="")`。
- `views/ai.py`：`jd_page`（GET 渲染）、`jd_generate`（POST，**不 csrf_exempt**，前端带 `X-CSRFToken`）。
- 校验：岗位名 2–30 字，去空白，拒绝纯符号。
- 返回：`{"status": true, "data": "...", "elapsed": 3.2}`；失败 `{"status": false, "msg": "..."}`。
- 模板 `ai/jd.html`：输入框 + 按钮 + `<pre>` 结果区 + loading + "复制/重新生成"。
- JS：`$.ajax` POST，点击后禁用 3 秒防连点。

**验收**：输入"数据分析师"，3–8 秒出现三段文本；两个页面并行互不干扰。

### P3 T3：制度知识库问答（1.5 h）

- 模型 + 迁移（第四节）。
- `management/commands/seed_knowledge.py`：8 条制度（打卡、迟到早退、请假、加班调休、差旅报销、报销时限、薪资发放、保密），幂等。
- `utils/retrieval.py::search(question, limit=5)`：
  1. 去标点、切词、去停用词，取 2–4 个检索词；
  2. `Q(title__icontains=t) | Q(content__icontains=t) | Q(keywords__icontains=t)` 取并集；
  3. 按命中词数排序，取前 5；
  4. 无命中返回空 → 视图直接回"不知道"，**不调模型**（省额度、防编造）。
- `views/ai.py`：`qa_page`、`qa_ask`，拼 `【资料】…【问题】…`，system 限定"只依据资料"。
- 返回带 `sources`（命中条目标题），页面显示"依据：《考勤管理办法》"——答辩加分点。

**验收**：三类问题跑通：命中 / 跨条目综合 / 无关问题答"不知道"。

### P4 T4：数据智能点评（1 h）

- `views/ai.py`：`comment_page`、`comment_generate`。
- 取数：`Salary` 取基本/奖金/扣款/考勤扣款/实发；`Attendance` 当月按 `status` 计数（迟到/早退/缺勤）并汇总 `fine`。
- 用 `scope.py` 过滤：普通员工只能点评自己（`request.user.employee`）；部门管理员限本部门。
- 结构化 → 文本：`员工张三，2026-10：出勤18天，迟到2次，缺勤0次，基本工资8000，奖金1200，扣款300，实发8900。`
- 提示词要求"一句客观点评 + 一条改进建议，50 字内，不评价人品"。
- 前端：员工下拉 + 月份选择，AJAX 返回后渲染。

**验收**：张三 2026-10 能出点评；普通员工点评别人 → 403 或友好提示。

### P5 T5 + T6：多轮对话与安全（1 h）

**T5**
- 历史存 session：`request.session["ai_chat"]`，只留最近 6 轮（12 条 message），带"清空对话"。
- 页面气泡式渲染（用户右、助手左），自动滚到底。
- 每轮把 `history + 新问题` 一起发；超 6 轮丢弃最早一轮。

**T6 清单**

| 项 | 做法 |
|---|---|
| 长度 | 超 `AI_MAX_INPUT` 提示并拒绝，不静默截断 |
| 内容 | 去控制字符；拒绝空/纯符号；前端用 `text()` 渲染，不用 `innerHTML` |
| 限流 | session 记 `last_call`，间隔 <3 s 返回"操作过快" |
| 日限额 | session 计 `calls_today` + 日期，超 50 次提示"今日演示额度已用完" |
| 超时 | SDK `timeout=20`；`APITimeoutError` → "模型响应超时，请重试" |
| 鉴权失败 | `AuthenticationError` → "AI Key 无效，请联系管理员"（不回显 Key） |
| 限流错误 | `RateLimitError`/429 → "当前调用人数较多，稍后再试" |
| 兜底 | 视图最外层 `try/except LLMError`，统一 JSON `status:false`，**绝不 500** |
| 日志 | `logging.getLogger("ai")` 记场景/耗时/错误类型，不记 Key 与完整提问 |

**验收**：断网、清空 Key、连点 5 次、输入 600 字，四种都只出中文提示。

### P6 T7：SSE 流式输出（1 h）

- `chat_stream`：`StreamingHttpResponse(gen(), content_type="text/event-stream")`，每块 `data: {"delta": "..."}\n\n`，结束 `data: [DONE]`。
- 响应头 `Cache-Control: no-cache`、`X-Accel-Buffering: no`。
- 前端 `fetch` + `response.body.getReader()` + `TextDecoder` 逐块追加；失败回退非流式接口。
- 保留 `/ai/chat/` 作兜底。

**验收**：生成"一段 100 字的公司简介"，能看到逐字增长；控制台无报错。

### P7 收尾（0.5 h）

- `manage.py init_data` 重跑权限；导航、首页入口、`README` 更新。
- `tests_ai.py`：mock `LLMClient.chat`，测 6 用例（空输入、超长、无资料、正常、限流、异常兜底）。
- 文档 `AI模块说明.md`（架构图、接口契约、提示词全文、演示脚本）。
- 回归：把现有 28 项页面验证脚本再跑一遍，确认原功能未被破坏。

---

## 六、提示词设计（三段式：角色 + 任务 + 输出格式）

| 场景 | system（角色） | user（任务 + 格式） |
|---|---|---|
| JD | 你是资深 HR，写招聘文案，语言简洁 | 为「{岗位}」写 JD，含【岗位职责】【任职要求】【薪资范围】三段，150 字内，不写公司名 |
| 问答 | 你是企业制度助手，只依据【资料】回答，资料没有就说"不知道"，禁止推测 | 【资料】{context}【问题】{q} 3 句内回答，末尾标"依据：《标题》" |
| 点评 | 你是 HR 数据分析助手，只陈述数据与建议，不评价个人品格 | {数据文本} 一句点评 + 一条建议，50 字内，不用列表 |
| 对话 | 你是企业员工助手，回答简短，涉密问题拒答 | （多轮 messages，不带资料） |

约定：`temperature` 取 0.8（JD）/ 0.3（问答、点评）/ 0.7（对话）；回答不用 Markdown 表格，页面 `<pre>` 渲染。

---

## 七、接口契约（前端只认这四种返回）

| 接口 | 方法 | 入参 | 成功 | 失败 |
|---|---|---|---|---|
| `/ai/jd/` | POST | `title` | `{"status":true,"data":"...","elapsed":3.1}` | `{"status":false,"msg":"岗位名称至少 2 个字"}` |
| `/ai/qa/` | POST | `question` | `{"status":true,"data":"...","sources":["考勤管理办法"]}` | 同上 |
| `/ai/comment/` | POST | `employee_id`,`month` | `{"status":true,"data":"..."}` | 同上 |
| `/ai/chat/` | POST | `question` | `{"status":true,"data":"...","round":2}` | 同上 |
| `/ai/chat/stream/` | POST | `question` | `text/event-stream`：`data:{"delta":"..."}`…`[DONE]` | 首帧 `data:{"error":"..."}` |

全部要求登录 + 权限（走 RBAC，**不写 `@csrf_exempt`**）；前端从 `{% csrf_token %}` 取 token 放 `X-CSRFToken`。

---

## 八、测试计划（约 32 项）

| 组 | 用例 |
|---|---|
| 配置（4） | 未配 Key / Base URL 错 / 模型名错 / 正常连通 |
| T2（5） | 正常 / 空 / 1 字 / 超长 31 字 / 连点两次 |
| T3（7） | 考勤命中 / 报销命中 / 跨条目 / 无关问题 / 空问题 / 超长 / sources 正确 |
| T4（5） | 张三 2026-10 / 无记录月份 / 员工点评自己 / 点评别人被拒 / 跨部门被拒 |
| T5（4） | 两轮连贯 / 清空后重开 / 超 6 轮截断 / 历史不串会话 |
| T7（3） | 逐字输出 / 中途断网提示 / 非流式兜底 |
| 安全（4） | 未登录 302 / 无权限 403 / `<script>` 被转义 / 日限额触发 |

Mock 版（不烧额度）：`tests_ai.py` patch `LLMClient.chat` 返回固定文本，验证视图逻辑；真机版手工跑一遍并录屏。

---

## 九、风险与预案

| 风险 | 影响 | 预案 |
|---|---|---|
| 免费模型限流 429 | 演示卡住 | 3 秒间隔 + 页面"重试"按钮 + 答辩前 30 分钟预热 |
| 校园网不通 | 全部失效 | 预留 `AI_OFFLINE_DEMO` 开关返回预置文本作兜底（文档标注） |
| Key 泄露 | 额度被盗 | 只放环境变量；文档/截图打码；如已外传建议平台重置 |
| 模型编造制度 | T3 判错 | system 强限定 + 无命中不调模型 + 返回 sources |
| SSE 被缓冲 | 看着像一次性输出 | `X-Accel-Buffering:no`；本机 runserver 直连演示 |
| 上下文超长 | 400 | 输入截断 + 历史 6 轮 + 资料 top5 |

---

## 十、答辩要点

**5 个概念一句话**

- 大模型 API：HTTP 接口，发文字回文字，不是本地程序。
- API Key：调用凭证，等同账号密码，只放环境变量。
- Prompt：给模型的指令，三段式 = 角色 + 任务 + 输出格式。
- 上下文注入：把数据库查出的资料拼进 prompt，让模型"照着资料答"。
- temperature：随机度，0.3 稳定、0.8 发散。

**8 分钟演示顺序**

1. 登录 → 智能助手下拉（10 s）
2. JD：输入"后端开发工程师"，展示三段结果（60 s）
3. 问答：问"迟到怎么扣钱"看依据；问"公司股票代码"→"不知道"（90 s）
4. 点评：张三 2026-10（60 s）
5. 多轮：先"请假流程"，再"那病假呢"（60 s）
6. 流式：展示逐字输出（40 s）
7. 讲链路图 + 断网兜底演示（120 s）
8. 讲安全：环境变量、限长、限流、403（60 s）

**高频追问**

- 为什么不把 Key 写进 settings？→ 会进 Git；环境变量按机器配置。
- 怎么防止胡说？→ 无命中不调模型 + system 限定 + 页面显示依据。
- 为什么不用向量库？→ 8 条制度 `icontains` 足够，向量库要额外服务。
- 流式怎么实现？→ `StreamingHttpResponse` + 生成器 + `getReader()`。
- 调用失败会崩吗？→ 异常统一转 `LLMError`，只返回 JSON。

---

## 十一、交付物清单

| 类型 | 文件 |
|---|---|
| 新增代码 | `utils/{ai,prompts,retrieval}.py`、`views/ai.py`、`templates/app01/ai/{jd,qa,comment,chat}.html` |
| 新增命令 | `management/commands/{ai_check,seed_knowledge}.py` |
| 改动文件 | `models.py`（+Knowledge）、`urls.py`（+5 路由）、`init_data.py`（+5 权限）、`layout.html`（+导航）、`settings.py`（+AI 配置）、`requirements.txt`、`.gitignore` |
| 迁移 | `0005_knowledge.py` |
| 测试 | `tests_ai.py`（6 用例）+ 手工 32 项清单 |
| 文档 | 本计划、`AI模块说明.md`、`README.md` 增补 |

---

## 十二、开工前需要确认的三件事

1. Key 是否就用截图里那把（**别贴进聊天**，直接配进环境变量；若已外传建议在平台重置）。
2. 模型是否固定 `Qwen/Qwen2.5-7B-Instruct`（免费档，人多会 429）。
3. T4 演示月份是否用 `2026-10`（现有薪资数据覆盖 2026-08 / 09 / 10）。
