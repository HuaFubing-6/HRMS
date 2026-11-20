# AI 智能助手模块 · 说明与验收

> 对应任务书《基于大模型的智能助手课程设计任务书》T1–T7。
> 项目：`D:\pycham-studyproject\qiyerenwu\hrms`（应用 `app01`）

---

## 一、七项任务完成情况

| 编号 | 要求 | 实现位置 | 状态 |
|---|---|---|---|
| T1 | 环境配置 + LLMClient 封装 | `.env`、`hrms/settings.py`、`app01/utils/ai.py`、`manage.py ai_check` | ✅ 真实调用通过 |
| T2 | 招聘 JD 生成 | `app01/views/ai.py::jd_generate`、`utils/prompts.py::build_jd_prompt`、`templates/app01/ai/jd.html` | ✅ |
| T3 | 制度知识库问答 | `models.Knowledge`、`utils/retrieval.py`、`qa_ask`、`qa.html` | ✅ 8 条制度，支持"不知道" |
| T4 | 数据智能点评 | `comment_generate`、`_build_data_text`、`comment.html` | ✅ 按数据范围过滤 |
| T5 | 多轮对话 | `chat_ask` / `chat_stream`、session `ai_chat`、`chat.html` | ✅ 保留 6 轮 |
| T6 | 安全与健壮性 | `clean_input`、`check_rate_limit`、`LLMError` 中文翻译、CSRF 全站开启 | ✅ |
| T7 | 流式输出 | `chat_stream`（SSE）、前端 `fetch + ReadableStream` | ✅ 实测 25 帧逐块到达 |

---

## 二、新增 / 修改文件清单

新增：

```
app01/utils/ai.py                  LLMClient + LLMError + 输入清洗 + 会话限流
app01/utils/prompts.py             四套提示词（JD / 问答 / 点评 / 对话）
app01/utils/retrieval.py           关键词检索（抽词 + 加权排序 + 上下文拼接）
app01/views/ai.py                  4 个页面 + 5 个 JSON 接口 + 1 个 SSE 接口
app01/templates/app01/ai/jd.html     招聘 JD 生成页
app01/templates/app01/ai/qa.html     制度问答页
app01/templates/app01/ai/comment.html 数据点评页
app01/templates/app01/ai/chat.html   对话助手页（含流式渲染）
app01/templates/app01/ai/float.html  全局悬浮助手（右下角浮窗，随 layout 出现在所有页面）
app01/management/commands/ai_check.py      T1 验收命令
app01/management/commands/seed_knowledge.py 8 条制度种子数据
app01/tests_ai.py                  26 个单元测试（不联网）
app01/migrations/0005_knowledge.py Knowledge 表迁移
.env                               本机真实 Key（已被 .gitignore 忽略）
.env.example                       配置模板（可提交）
.gitignore                         忽略 .env / .venv / 日志
```

修改：

```
app01/models.py                    追加 Knowledge 模型
hrms/settings.py                   读取 .env；新增 AI_* 配置
app01/urls.py                      import ai；追加 10 条 AI 路由
app01/management/commands/init_data.py  追加 10 条 AI 权限及角色分配
app01/templates/app01/layout.html   导航新增"智能助手"下拉（按权限逐条显隐）；底部引入悬浮助手
requirements.txt                   追加 openai、python-dotenv
```

---

## 三、如何运行

```powershell
cd D:\pycham-studyproject\qiyerenwu\hrms

# 1) 装依赖（首次）
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# 2) 建表 + 初始化权限 + 写入制度
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py init_data
.\.venv\Scripts\python.exe manage.py seed_knowledge

# 3) 验证模型连通（T1 验收）
.\.venv\Scripts\python.exe manage.py ai_check
#   预期：打印 BASE_URL / MODEL / 打码后的 KEY，然后输出模型回答与耗时

# 4) 跑单元测试
.\.venv\Scripts\python.exe manage.py test app01.tests_ai

# 5) 启动（8000 被另一个 HRMS 占用，故用 8001）
.\.venv\Scripts\python.exe manage.py runserver 127.0.0.1:8001
```

登录 `盖亚 / 123`，导航栏"智能助手"下四个入口。

---

## 四、接口一览

| 方法 | 路径 | 作用 | 返回 |
|---|---|---|---|
| GET | `/ai/jd/` | 招聘 JD 页面 | HTML |
| POST | `/ai/jd/generate/` | 生成 JD | `{status,data,elapsed}` |
| GET | `/ai/qa/` | 制度问答页面 | HTML |
| POST | `/ai/qa/ask/` | 提问 | `{status,data,sources,terms}` |
| GET | `/ai/comment/` | 数据点评页面 | HTML |
| POST | `/ai/comment/generate/` | 生成点评 | `{status,data,raw}` |
| GET | `/ai/chat/` | 对话页面（带历史） | HTML |
| POST | `/ai/chat/ask/` | 多轮（非流式） | `{status,data,round}` |
| POST | `/ai/chat/clear/` | 清空历史 | `{status}` |
| POST | `/ai/chat/stream/` | 多轮（SSE） | `data:{json}\n\n` … `data:[DONE]` |

统一失败结构：`{"status": false, "msg": "中文提示"}`，前端只需判断 `status`。

---

## 五、关键设计（答辩可用）

1. **三段式提示词**：`system` 定角色与边界，`user` 定任务与输出格式。
   JD 写成"严格按【岗位职责】【任职要求】【薪资范围】三段"，前端才好渲染。
2. **检索增强（最小 RAG）**：8 条制度上用"抽词 + icontains + 命中加权"，
   不引入向量库 —— 数据规模决定技术选型。
3. **无命中不调模型**：资料里没有就直接回"不知道"，
   既省额度，又从机制上杜绝编造制度。
4. **数据先转人话**：把考勤/薪资拼成一句完整描述再喂模型；
   没有考勤记录时明确写"没有记录"，而不是"出勤 0 天"（后者会诱导模型猜原因）。
5. **越权二次校验**：页面按 `scope.py` 过滤员工，接口里再查一次 `_can_comment`，
   前端改 `employee_id` 也进不去。
6. **异常统一翻译**：`LLMClient._translate` 把 401/429/超时/断网翻成中文，
   视图层只 `except LLMError`，不会 500，也不会把 Key 片段回显给用户。
7. **流式的错误处理**：响应头发出后改不了状态码，所以生成器内部捕获
   `LLMError` 并发 `{"error": ...}` 帧，前端把它拼进气泡；断流还会自动退回普通接口。
8. **不用 `@csrf_exempt`**：全站 CSRF 保留，前端带 `X-CSRFToken` —— 与参考代码的差异，
   也是答辩可讲的"安全取舍"。

---

## 五·附、全局悬浮助手（每个页面右下角）

**位置**：`app01/templates/app01/ai/float.html`，由 `layout.html` 在 bootstrap 脚本之后 include。

**为什么放 layout 而不是逐页加**：浮窗只有一份代码，改一次全站生效；
且和导航一样属于"全局层"，不该出现在某个业务模板里。

**权限**：整份模板包在 `{% if request|has_perm:"/ai/chat/" %}` 里。
无权限账号收到的 HTML 里连按钮都没有，不是"显示了再 403"。
（注意：被 include 的子模板必须自己 `{% load filters %}`，
`{% load %}` 不会从父模板继承 —— 这是踩过的坑。）

**行为**：

- 点击右下角深色圆形按钮 → 面板以缩放动画展开，再点或 Esc 收起；
- 输入框回车发送，Shift+回车换行；
- 走 `/ai/chat/stream/` 逐字输出；断流自动退回 `/ai/chat/ask/`；
- 「清空」调用 `/ai/chat/clear/`；
- 与对话助手页共用同一份 session 历史，浮窗里说过的话，进页面能接着聊；
- 空状态给 3 个示例问题（迟到怎么罚款 / 请假提前几天 / 出差住宿标准），点一下就发。

**视觉取舍**（对应"简洁有设计感"的要求）：

- 按钮用深墨色 `#262b30`，全站只有一个浮层入口，不抢内容；
- 面板白底 + 1px 细边 + 14px 圆角 + 大范围柔阴影，靠留白分层，不加渐变和图标堆叠；
- 用户气泡浅绿灰 `#eef4f0`，助手气泡白底细边，信息密度靠行高 1.65 撑开；
- 小屏（<480px）面板改为 `calc(100vw - 24px)` 宽、62vh 高，避免遮住半屏。

---

## 六、实测记录（2026-11-16）

- `ai_check`：`Qwen/Qwen2.5-7B-Instruct`，回答正常，耗时约 2.4 s。
- 端到端 14 项（页面 4 + 接口成功 5 + 越权/校验 3 + 清空 1 + 流式 1）全部通过。
- 单元测试 26 项全部通过（`manage.py test app01.tests_ai`）。
- 真机 SSE：`Content-Type: text/event-stream`，单次回答 16–25 帧逐块到达，
  总耗时 0.4–0.6 s，收到 `[DONE]` 正常结束。
- 悬浮助手：`/index/`、`/employee/list/`、`/chart/`、`/ai/qa/`、`/notice/list/` 五个页面
  均渲染出浮窗；无角色账号访问 `/index/` 被中间件 403（符合预期）。
- 典型输出：
  - 问"迟到一次扣多少钱" → "迟到一次罚款 50 元。依据：《考勤管理办法》"，依据列表只有 1 条。
  - 问"公司的股票代码是多少" → "不知道"（未调用模型）。
  - 点评李明 2026-10 → "本月无考勤记录，影响薪资计算。建议核对并补录李明的考勤数据。"

---

## 七、已知限制

1. 免费模型有并发/频率限制，高峰期可能返回"请 10 秒后重试"，属预期行为。
2. 限流是 session 级（单浏览器），多标签页共享同一额度；换账号即重置。
3. 检索是关键词匹配，同义改写（如"打卡晚了"）依赖 `keywords` 字段覆盖。
4. `AI_OFFLINE_DEMO=1` 时返回预置文本，仅用于断网演示，正常答辩请保持 0。
5. `.env` 里有真实 Key：不要提交仓库；如果 Key 曾在聊天/截图里出现，建议在硅基流动后台重置。
