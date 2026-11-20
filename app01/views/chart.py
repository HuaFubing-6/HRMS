"""
数据统计可视化（T10，加分项）
==============================

架构：后端只提供 JSON 数据，前端 ECharts 负责画图。
为什么不在后端生成图片？
因为图表要能交互（悬浮提示、切换），ECharts 在前端渲染更灵活，也更省服务器资源。

两个接口：
    /chart/dept/pie/     部门人数分布（饼图）
    /chart/salary/trend/ 各月薪资总额（折线图）

答辩可讲点（T10 加分项）：
  1. 后端只出 JSON、前端画图 —— 图表能交互、也省服务器算力
  2. annotate + values —— 让 MySQL 分组聚合，只取两列，不把对象搬回内存
  3. Decimal 不能直接进 JsonResponse —— 逐个 float() 转换，否则序列化抛 TypeError
  4. `or 0` 不能省 —— Sum 空库返回 None，float(None) 直接崩
"""
from django.db.models import Count, Sum
from django.http import JsonResponse
from django.shortcuts import render

from app01 import models
# is_dept_admin / is_plain_employee：图表接口也要套范围，
# 否则列表过滤了、图表却把全公司数据吐出去，等于白过滤
# plain_employee_scope：普通员工没绑档案时返回空集，而不是全量
from app01.utils.scope import (
    is_dept_admin,
    is_plain_employee,
    plain_employee_scope,
)


def chart_index(request):
    """
    图表页：只渲染空容器，数据由页面里的 JS 用 AJAX 拉取。

    为什么不在视图里直接把数据塞进模板？
    因为图表要能刷新、能切换筛选，数据留到前端按需请求更灵活；
    后端只负责"按要求给 JSON"，职责更清楚。
    """
    # 这个模板里只有两个空 <div> 和一个本地 echarts.min.js 引用，
    # 具体数据在页面加载后由 $.get 分别请求下面两个接口
    return render(request, "app01/chart/index.html")


def dept_pie(request):
    """
    部门人数分布。

    annotate(count=Count("employee"))：
    对每个部门统计员工数，等价于 SQL：
        SELECT title, COUNT(employee_id) FROM department
        LEFT JOIN employee ... GROUP BY title
    values("title", "count") 决定最终取哪两列，减少数据传输。

    返回格式直接对齐 ECharts 饼图的 data 约定：[{name, value}, ...]
    """
    # ---- 分组统计：一条 SQL 出结果 ----
    # annotate(count=Count("employee")) 给每个部门临时挂一个 count 属性，
    # 等价于 SQL 的 GROUP BY department.title + COUNT(employee.id)
    # 注意 Count("employee") 用的是"反向关系名"：Department 里没有 employee 字段，
    # Django 默认用 小写模型名_set，但在查询里可以直接写 employee
    # ---- 数据范围：先按账号口径缩范围，再做分组聚合 ----
    # 这一步是必须的：列表页只给"自己的工资"，
    # 但趋势图如果不缩范围，普通员工打开就能看到全公司每月工资总额，
    # 部门管理员也能看到别的部门支出 —— 范围限制等于被图表绕开了。
    qs = models.Department.objects.all()
    if is_dept_admin(request.user):
        # 部门管理员只看到自己那一个部门的人数
        qs = qs.filter(id=request.user.depart_id)
    if is_plain_employee(request.user):
        # 普通员工跟"部门人数分布"没有关系，给空数组，
        # 不借机把公司组织结构和各部门人数暴露给他
        qs = qs.none()

    rows = (
        qs.annotate(count=Count("employee"))
        # values("title", "count") 决定最终只取这两列：
        # 不 values 的话会把整个部门对象（含所有字段）搬回内存，
        # 还得在 Python 里再数一遍员工 —— 等于把数据库该干的活挪到应用层做
        .values("title", "count")
    )

    # ---- 转成 ECharts 饼图约定格式 ----
    # 饼图的 series.data 要 [{name: 类别, value: 数值}]，
    # 而 ORM 给的是 [{"title": ..., "count": ...}]，字段名对不上，
    # 所以这里转一次；转完前端拿到直接赋值给 series[0].data，不用再加工
    data = [{"name": r["title"], "value": r["count"]} for r in rows]

    # 统一包一层 {status, data}：前端先看 status 再取 data，
    # 以后加错误提示时格式不用变
    return JsonResponse({"status": True, "data": data})


def salary_trend(request):
    """
    各月薪资总额折线图。

    values("month").annotate(total=Sum("total")) 实现按月份分组求和，
    order_by("month") 保证 x 轴按时间先后排列（否则折线会乱序）。

    金额是 Decimal，JsonResponse 不认识 Decimal，
    所以逐个 float() 转换，否则会抛 TypeError 序列化失败。
    """
    # ---- 按月份分组求和 ----
    # values("month") 先按月份分组（相当于 GROUP BY month），
    # annotate(total=Sum("total")) 在每组里对 total 求和
    # order_by("month") 必须有：不加的话 MySQL 不保证顺序，
    # x 轴的月份会乱跳，折线就交叉了
    # ---- 数据范围：和列表页同一套口径 ----
    # 普通员工只聚合"自己"那几条 → 折线图只有自己各月的实发；
    # 部门管理员只聚合本部门 → 看到的是本部门的月度支出趋势。
    # 不缩范围的话，这个接口就成了一扇后门：列表看一条，图表看全公司总额。
    qs = models.Salary.objects.all()
    if is_dept_admin(request.user):
        qs = qs.filter(employee__depart_id=request.user.depart_id)
    if is_plain_employee(request.user):
        # 没绑员工档案时给空集：折线图全 0，而不是把全公司总额画出来
        qs = plain_employee_scope(qs, request.user)

    rows = (
        qs.values("month")
        .annotate(total=Sum("total"))
        .order_by("month")
    )

    # ---- 拆成两条数组，正好对应 ECharts 的 xAxis.data 和 series.data ----
    # months 是 x 轴刻度，totals 是每个点的值
    months = [r["month"] for r in rows]

    # `or 0` 不能省：Sum 在没有可聚合数据时返回 None，float(None) 会直接抛 TypeError。
    # 这里既要处理 Decimal → float 的序列化问题（JsonResponse 不认识 Decimal），
    # 也要处理空库时的 None。
    totals = [float(r["total"] or 0) for r in rows]

    return JsonResponse({"status": True, "months": months, "totals": totals})
