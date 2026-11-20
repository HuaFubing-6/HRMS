"""
app01 业务路由表
=================

所有路径都集中在这里，一是便于一眼看全站结构，
二是 RBAC 权限表里存的 URL 必须和这里的 path 完全一致（否则权限永远对不上）。

URL 设计约定：
    /模块/list/          列表
    /模块/add/           新增
    /模块/edit/<pk>/     编辑（pk 用 <int:pk> 限制只能是整数）
    /模块/delete/<pk>/   删除
模块化管理，看 URL 就知道进哪个功能。
"""
from django.urls import path

from app01.views import account, chart, dashboard, department, employee, attendance, salary, notice, task, rbac, ai

urlpatterns = [
    # ---------------- 入口 ----------------
    # 根地址 "/"：已登录去 /index/，未登录去 /login/
    # 不加这条的话，直接打开 127.0.0.1:8001/ 会被 RBAC 中间件判成"无权限"返回 403
    path("", account.home, name="home"),

    # ---------------- 认证 ----------------
    path("login/", account.login_view, name="login"),
    path("logout/", account.logout_view, name="logout"),
    path("captcha/", account.captcha, name="captcha"),   # 验证码图片
    # 账号快速切换（答辩演示用，仅超管可发起）
    path("account/switch/", account.switch_account, name="switch_account"),
    path("account/switch/back/", account.switch_back, name="switch_back"),
    path("account/switch/<int:pk>/", account.switch_to, name="switch_to"),

    # ---------------- 首页 ----------------
    path("index/", dashboard.index, name="index"),

    # ---------------- 部门（T2） ----------------
    path("department/list/", department.department_list, name="department_list"),
    path("department/add/", department.department_add, name="department_add"),
    path("department/edit/<int:pk>/", department.department_edit, name="department_edit"),
    path("department/delete/<int:pk>/", department.department_delete, name="department_delete"),

    # ---------------- 员工（T3） ----------------
    path("employee/list/", employee.employee_list, name="employee_list"),
    path("employee/add/", employee.employee_add, name="employee_add"),
    path("employee/edit/<int:pk>/", employee.employee_edit, name="employee_edit"),
    path("employee/delete/<int:pk>/", employee.employee_delete, name="employee_delete"),

    # ---------------- 考勤（T6） ----------------
    path("attendance/list/", attendance.attendance_list, name="attendance_list"),
    path("attendance/add/", attendance.attendance_add, name="attendance_add"),
    path("attendance/delete/<int:pk>/", attendance.attendance_delete, name="attendance_delete"),

    # ---------------- 薪资（T7） ----------------
    path("salary/list/", salary.salary_list, name="salary_list"),
    path("salary/add/", salary.salary_add, name="salary_add"),
    path("salary/delete/<int:pk>/", salary.salary_delete, name="salary_delete"),

    # ---------------- 公告（T8） ----------------
    path("notice/list/", notice.notice_list, name="notice_list"),
    path("notice/add/", notice.notice_add, name="notice_add"),
    path("notice/delete/<int:pk>/", notice.notice_delete, name="notice_delete"),
    path("notice/top/<int:pk>/", notice.notice_top, name="notice_top"),   # 置顶切换

    # ---------------- 任务（T9，AJAX） ----------------
    path("task/list/", task.task_list, name="task_list"),
    path("task/add/", task.task_add, name="task_add"),
    path("task/edit/<int:pk>/", task.task_edit, name="task_edit"),
    path("task/delete/<int:pk>/", task.task_delete, name="task_delete"),
    # 审核：pass 通过 / reject 驳回，动作写在 URL 里（只有超管能进）
    path("task/audit/<int:pk>/<str:action>/", task.task_audit, name="task_audit"),
    # 标记完成：超管、发布人、负责人本人可以点
    path("task/done/<int:pk>/", task.task_done, name="task_done"),

    # ---------------- 用户 / 角色（T5） ----------------
    path("user/list/", rbac.user_list, name="user_list"),
    path("user/add/", rbac.user_add, name="user_add"),
    path("user/delete/<int:pk>/", rbac.user_delete, name="user_delete"),
    path("role/list/", rbac.role_list, name="role_list"),
    path("role/add/", rbac.role_add, name="role_add"),
    path("role/edit/<int:pk>/", rbac.role_edit, name="role_edit"),
    path("role/delete/<int:pk>/", rbac.role_delete, name="role_delete"),

    # ---------------- 数据可视化（T10） ----------------
    path("chart/", chart.chart_index, name="chart_index"),
    path("chart/dept/pie/", chart.dept_pie, name="chart_dept_pie"),           # 饼图 JSON
    path("chart/salary/trend/", chart.salary_trend, name="chart_salary_trend"),  # 折线 JSON

    # ---------------- AI 智能助手（大模型） ----------------
    # 页面
    path("ai/jd/", ai.jd_page, name="ai_jd_page"),                 # 招聘 JD 生成
    path("ai/qa/", ai.qa_page, name="ai_qa_page"),                 # 制度问答
    path("ai/comment/", ai.comment_page, name="ai_comment_page"),  # 数据点评
    path("ai/chat/", ai.chat_page, name="ai_chat_page"),           # 对话助手
    # 接口（POST + 返回 JSON；走全站 CSRF，前端带 X-CSRFToken）
    path("ai/jd/generate/", ai.jd_generate, name="ai_jd_generate"),
    path("ai/qa/ask/", ai.qa_ask, name="ai_qa_ask"),
    path("ai/comment/generate/", ai.comment_generate, name="ai_comment_generate"),
    path("ai/chat/ask/", ai.chat_ask, name="ai_chat_ask"),
    path("ai/chat/clear/", ai.chat_clear, name="ai_chat_clear"),
    # 流式（SSE）：逐字输出
    path("ai/chat/stream/", ai.chat_stream, name="ai_chat_stream"),
]
