"""
AI 智能助手视图（T2 / T3 / T4 / T5 / T6 / T7）
============================================

页面（GET，渲染模板）：
    jd_page         招聘 JD 生成
    qa_page         制度问答
    comment_page    数据点评
    chat_page       对话助手

接口（POST，返回 JSON 或 SSE）：
    jd_generate     /ai/jd/            生成 JD
    qa_ask          /ai/qa/            制度问答
    comment_generate/ai/comment/       数据点评
    chat_ask        /ai/chat/          多轮对话（非流式兜底）
    chat_stream     /ai/chat/stream/   多轮对话（SSE 逐字）

统一约定（前端只认这一种结构）：
    成功 {"status": true,  "data": "文本", ...}
    失败 {"status": false, "msg": "中文提示"}

安全约定：
    1. 不写 @csrf_exempt —— 全站 CSRF 中间件开着，前端带 X-CSRFToken；
    2. 所有入口先过 clean_input（长度/控制字符/纯符号）；
    3. 所有入口先过 check_rate_limit（间隔 3 秒、每日 50 次）；
    4. 模型异常统一被 LLMClient 翻译成 LLMError，这里只负责转 JSON，绝不 500。
"""
import json
import logging
import time
from datetime import date

from django.conf import settings
from django.http import JsonResponse, StreamingHttpResponse
from django.shortcuts import render

from app01 import models
from app01.utils.ai import (
    LLMClient,
    LLMError,
    check_rate_limit,
    clean_input,
    mark_rate_used,
)
from app01.utils.prompts import (
    COMMENT_SYSTEM,
    QA_SYSTEM,
    JD_SYSTEM,
    build_chat_messages,
    build_comment_prompt,
    build_jd_prompt,
    build_qa_prompt,
)
from app01.utils.retrieval import build_context, search
from app01.utils.scope import is_dept_admin, is_plain_employee

logger = logging.getLogger("ai")


# ------------------------------------------------------------------
# 公共小工具
# ------------------------------------------------------------------
def _fail(msg):
    """失败响应：字段名统一叫 msg，前端只需判断 status。"""
    return JsonResponse({"status": False, "msg": msg})


def _prepare(request, text, field, max_len=None):
    """
    接口入口的三道检查：限流 → 输入清洗 → 返回错误提示。

    返回 (clean_text, error_response)：
        error_response 不为 None 时，调用方直接 return 它。
    """
    limited = check_rate_limit(request)
    if limited:
        return "", _fail(limited)

    clean, err = clean_input(text, max_len=max_len, field=field)
    if err:
        return "", _fail(err)
    return clean, None


def _current_employee(user):
    """取当前账号绑定的员工档案（没有就返回 None）。"""
    return getattr(user, "employee", None)


def _visible_employees(user):
    """
    数据点评能选哪些员工（T4 + 数据范围）：

        普通员工     → 只有自己（防止看别人工资）
        部门管理员   → 本部门员工
        超管         → 全部
    """
    qs = models.Employee.objects.select_related("depart").order_by("id")
    if is_plain_employee(user):
        emp = _current_employee(user)
        return qs.filter(pk=emp.pk) if emp else qs.none()
    if is_dept_admin(user):
        return qs.filter(depart_id=user.depart_id)
    return qs


def _can_comment(user, employee):
    """校验"当前账号能不能点评这个员工"，防止前端改 employee_id 越权。"""
    if user.is_superuser:
        return True
    if is_dept_admin(user):
        return employee.depart_id == user.depart_id
    if is_plain_employee(user):
        emp = _current_employee(user)
        return emp is not None and emp.pk == employee.pk
    return False


def _build_data_text(employee, month):
    """
    把结构化数据转成"人话"，再交给模型点评（T4 的关键一步）。

    为什么要转文本：
      模型只认自然语言，不认 ORM 对象和 Decimal；
      把数字写成完整句子，模型的点评才不会跑偏。

    返回 (data_text, salary_obj)；没有该月薪资时 salary_obj 为 None。
    """
    year, mon = month.split("-")
    attendance = models.Attendance.objects.filter(
        employee=employee, date__year=int(year), date__month=int(mon)
    )

    stats = {
        "normal": attendance.filter(status="normal").count(),
        "late": attendance.filter(status="late").count(),
        "early": attendance.filter(status="early").count(),
        "absent": attendance.filter(status="absent").count(),
    }
    total_fine = sum((a.fine for a in attendance), start=models.Attendance.FINE_LATE * 0)
    days = attendance.count()

    # 没有考勤记录 ≠ 全勤，也 ≠ 缺勤。必须如实说"没有记录"，
    # 否则模型看到"出勤 0 天"会自作主张替员工找原因（实测会猜"健康问题"）。
    if days == 0:
        attend_text = "本月没有任何考勤记录（数据可能未录入）"
    else:
        attend_text = (
            f"出勤 {days} 天：按时 {stats['normal']} 天、迟到 {stats['late']} 次、"
            f"早退 {stats['early']} 次、缺勤 {stats['absent']} 天，"
            f"考勤罚款合计 {total_fine} 元"
        )

    salary = models.Salary.objects.filter(employee=employee, month=month).first()
    if salary is None:
        return (
            f"员工{employee.name}，{month}：{attend_text}。本月尚未录入薪资记录。",
            None,
        )

    return (
        f"员工{employee.name}，{month}：{attend_text}。"
        f"薪资：基本工资 {salary.base_pay} 元、奖金 {salary.bonus} 元、"
        f"其他扣款 {salary.deduction} 元、考勤罚款 {salary.attendance_fine} 元，"
        f"实发 {salary.total} 元。",
        salary,
    )


# ------------------------------------------------------------------
# 一、页面
# ------------------------------------------------------------------
def jd_page(request):
    """T2 页面：输入岗位名 → 点按钮 → 结果出现在下方，不刷新整页。"""
    return render(request, "app01/ai/jd.html")


def qa_page(request):
    """T3 页面：问题 + 回答 + 依据条目。"""
    return render(request, "app01/ai/qa.html", {
        "knowledge_count": models.Knowledge.objects.filter(is_active=True).count(),
    })


def comment_page(request):
    """T4 页面：员工下拉 + 月份下拉，按数据范围过滤员工。"""
    employees = _visible_employees(request.user)

    months = list(
        models.Salary.objects.values_list("month", flat=True).distinct().order_by("-month")
    )
    if date.today().strftime("%Y-%m") not in months:
        months.insert(0, date.today().strftime("%Y-%m"))

    return render(request, "app01/ai/comment.html", {
        "employees": employees,
        "months": months,
        "can_choose_employee": not is_plain_employee(request.user),
    })


def chat_page(request):
    """T5 页面：对话助手（前端持历史渲染，服务端 session 存权威历史）。"""
    history = request.session.get("ai_chat", [])
    return render(request, "app01/ai/chat.html", {
        "history": history,
        "stream_enabled": True,
    })


# ------------------------------------------------------------------
# 二、T2 招聘 JD
# ------------------------------------------------------------------
def jd_generate(request):
    if request.method != "POST":
        return _fail("请用 POST 提交")

    title, err = _prepare(request, request.POST.get("title"), "岗位名称", max_len=30)
    if err:
        return err

    depart = (request.POST.get("depart") or "").strip()[:20]
    years = (request.POST.get("years") or "").strip()[:10]

    started = time.time()
    try:
        text = LLMClient.chat(
            build_jd_prompt(title, depart=depart, years=years),
            system=JD_SYSTEM,
            temperature=0.8,          # JD 属于创作类，随机度高一点文案更自然
        )
    except LLMError as exc:
        return _fail(str(exc))

    mark_rate_used(request)
    return JsonResponse({
        "status": True,
        "data": text,
        "elapsed": round(time.time() - started, 1),
        "title": title,
    })


# ------------------------------------------------------------------
# 三、T3 制度问答
# ------------------------------------------------------------------
def qa_ask(request):
    if request.method != "POST":
        return _fail("请用 POST 提交")

    question, err = _prepare(request, request.POST.get("question"), "问题")
    if err:
        return err

    items, terms = search(question)
    if not items:
        # 关键设计：资料里没有，就不调模型，直接"不知道"。
        # 既省免费额度，又从机制上杜绝模型编造制度条款。
        mark_rate_used(request)
        return JsonResponse({
            "status": True,
            "data": "不知道",
            "sources": [],
            "terms": terms,
            "note": "知识库中没有检索到相关制度",
        })

    context = build_context(items)
    try:
        text = LLMClient.chat(
            build_qa_prompt(question, context),
            system=QA_SYSTEM,
            temperature=0.3,          # 问答要稳，别自由发挥
        )
    except LLMError as exc:
        return _fail(str(exc))

    mark_rate_used(request)
    return JsonResponse({
        "status": True,
        "data": text,
        "sources": [k.title for k in items],
        "terms": terms,
    })


# ------------------------------------------------------------------
# 四、T4 数据点评
# ------------------------------------------------------------------
def comment_generate(request):
    if request.method != "POST":
        return _fail("请用 POST 提交")

    month = (request.POST.get("month") or "").strip()
    if not month or len(month) != 7:
        return _fail("请选择正确的月份（格式 2026-10）")

    limited = check_rate_limit(request)
    if limited:
        return _fail(limited)

    try:
        employee = models.Employee.objects.select_related("depart").get(
            pk=request.POST.get("employee_id")
        )
    except (models.Employee.DoesNotExist, ValueError):
        return _fail("员工不存在")

    if not _can_comment(request.user, employee):
        return _fail("你没有权限查看该员工的数据")

    data_text, salary = _build_data_text(employee, month)
    if salary is None and not models.Attendance.objects.filter(
        employee=employee, date__year=int(month[:4]), date__month=int(month[5:])
    ).exists():
        return _fail(f"{employee.name} 在 {month} 既没有考勤也没有薪资记录，无法点评")

    try:
        text = LLMClient.chat(
            build_comment_prompt(data_text),
            system=COMMENT_SYSTEM,
            temperature=0.3,
            max_tokens=256,           # 点评只要一句话，给太多额度纯浪费
        )
    except LLMError as exc:
        return _fail(str(exc))

    mark_rate_used(request)
    return JsonResponse({
        "status": True,
        "data": text,
        "employee": employee.name,
        "month": month,
        "raw": data_text,             # 把"喂给模型的数据"也回给页面，方便核对
    })


# ------------------------------------------------------------------
# 五、T5 多轮对话
# ------------------------------------------------------------------
def _chat_context(question):
    """
    对话助手的"随身资料"：先检索一次制度库，命中了就把原文一起给模型。

    这一步是 T3 和 T5 的串联点：
      只靠多轮记忆，模型会答"一般公司都提前 1-2 天"这种空话；
      带上制度原文，它才能说出"事假提前 1 个工作日"这种可核对的答案。
    """
    items, _ = search(question)
    return build_context(items) if items else ""


def _chat_answer(request, question):
    """公共部分：取历史 → 拼 messages → 调模型 → 写回历史。"""
    history = request.session.get("ai_chat", [])
    messages = build_chat_messages(question, history, context=_chat_context(question))

    answer = LLMClient.chat_messages(messages, temperature=0.7, max_tokens=512)

    history = history + [
        {"role": "user", "content": question},
        {"role": "assistant", "content": answer},
    ]
    request.session["ai_chat"] = history[-12:]   # 只留最近 6 轮
    return answer, len(history) // 2


def chat_ask(request):
    if request.method != "POST":
        return _fail("请用 POST 提交")

    question, err = _prepare(request, request.POST.get("question"), "问题", max_len=200)
    if err:
        return err

    try:
        answer, rounds = _chat_answer(request, question)
    except LLMError as exc:
        return _fail(str(exc))

    mark_rate_used(request)
    return JsonResponse({"status": True, "data": answer, "round": rounds})


def chat_clear(request):
    """清空对话历史（T5 页面上的"清空对话"按钮）。"""
    request.session.pop("ai_chat", None)
    return JsonResponse({"status": True})


# ------------------------------------------------------------------
# 六、T7 流式输出（SSE）
# ------------------------------------------------------------------
def _sse(data):
    """把一段数据包装成 SSE 帧：`data: {...}\n\n`。"""
    return "data: " + json.dumps(data, ensure_ascii=False) + "\n\n"


def chat_stream(request):
    """
    流式对话：边生成边输出，前端逐字渲染。

    与普通接口的区别：
      1. 响应头是 text/event-stream，不是 application/json；
      2. 一旦开始输出，HTTP 状态码就定死了，后面的异常只能作为一帧 error 发出去；
      3. 所以错误处理必须在生成器内部完成，不能靠视图返回 500。
    """
    if request.method != "POST":
        return _fail("请用 POST 提交")

    question, err = _prepare(request, request.POST.get("question"), "问题", max_len=200)
    if err:
        return err

    history = request.session.get("ai_chat", [])
    messages = build_chat_messages(question, history, context=_chat_context(question))

    def gen():
        pieces = []
        try:
            for piece in LLMClient.stream(messages, temperature=0.7, max_tokens=512):
                pieces.append(piece)
                yield _sse({"delta": piece})
        except LLMError as exc:
            yield _sse({"error": str(exc)})
            return

        answer = "".join(pieces)
        # 生成器结束后再写 session：此时才能拼出完整回答
        new_history = history + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        request.session["ai_chat"] = new_history[-12:]
        mark_rate_used(request)

        yield _sse({"round": len(new_history) // 2})
        yield "data: [DONE]\n\n"

    resp = StreamingHttpResponse(gen(), content_type="text/event-stream")
    resp["Cache-Control"] = "no-cache"
    # Nginx 默认会缓冲代理响应，导致"流式"变成一次性输出；这个头让它别缓
    resp["X-Accel-Buffering"] = "no"
    return resp
