"""
薪资管理（T7）
================

三个视图：列表（含月份/员工筛选与总额统计）、录入、删除。

答辩重点：
1. 实发工资不在视图里算，而是交给模型 save()（单一数据源）；
2. 月度总额用 ORM 的 aggregate(Sum) 让数据库算，不把明细拉回 Python 再循环累加；
3. 金额输入必须先转成 Decimal 再落库，字符串直接做减法会报 TypeError。

答辩可讲点（这个模块修过一个真实 500）：
  1. save() 里算实发 —— 单一数据源，不用前端再算一遍
  2. to_decimal —— 修掉 "8000" - "300" 的 TypeError，并经 str() 避免浮点误差
  3. 视图三道校验 —— 必填 / 金额格式 / 实发不能为负，失败都回填不落库
  4. aggregate(Sum) —— 月度总额让 MySQL 算，不把明细拉回内存
"""
import re
# 算钱必须用 Decimal，float 会出现 0.30000000000000004 这种误差
from decimal import Decimal

# Sum 用于月度总额聚合：让 MySQL 做 SUM，不把明细拉回 Python
from django.db.models import Sum
# render 渲染模板；redirect 返回 302 跳转
from django.shortcuts import render, redirect

# models 直接用 ORM 建薪资记录（这里不用 ModelForm，原因见 salary_add 的 docstring）
from app01 import models
# Pagination 全站公共分页组件
from app01.utils.pagination import Pagination
# is_dept_admin / is_plain_employee：决定这个账号能看谁的工资
# plain_employee_scope：把查询收敛到"普通员工只能看自己"，没绑档案就返回空集
from app01.utils.scope import (
    is_dept_admin,
    is_plain_employee,
    plain_employee_scope,
)


def _emp_list_for(user):
    """
    "这个账号能看到的员工"范围，列表筛选下拉和录入下拉都用它。

    三种情况：
      - 部门管理员：只列本部门的人（否则下拉能选到别部门，等于绕过范围限制）
      - 普通员工  ：只列自己（连别人姓名都不该出现在下拉框里，
                   否则工资明细虽然过滤了，人员名单还是泄露了）
      - 超管/其他：全量
    """
    qs = models.Employee.objects.all()
    if is_dept_admin(user):
        qs = qs.filter(depart_id=user.depart_id)
    elif is_plain_employee(user):
        # 普通员工只列自己；没绑员工档案就给空集。
        # 不能写 `if user.employee_id` 才过滤、否则不管 ——
        # 那样没绑档案的普通员工会拿到全员下拉，等于把同事名单泄出去。
        qs = qs.filter(id=user.employee_id) if user.employee_id else qs.none()
    return qs

# 金额格式：允许整数或最多两位小数，且不能为负
MONEY_RE = re.compile(r"^\d+(\.\d{1,2})?$")


def salary_list(request):
    """
    薪资列表：按月份、员工筛选，并统计所选月份的总支出。
    """
    # ---- 取筛选条件 ----
    # month 形如 "2026-10"（前端 <input type="month"> 提交的格式刚好一致，不用转换）
    month = request.GET.get("month", "").strip()
    # 员工 id；空串表示"所有人"
    emp_id = request.GET.get("employee", "")

    # select_related("employee")：列表每行都要显示员工姓名，
    # 不加就是 1 条查薪资 + 每行 1 条查员工（N+1）；加了合并成一条 JOIN
    # 注意顺序：先 all() 再 select_related，两者都是往同一个 QuerySet 上加条件
    queryset = models.Salary.objects.all().select_related("employee")

    # 按月份精确筛（month 存的是 "2026-10" 这样的字符串，所以用等于而不是范围）
    if month:
        queryset = queryset.filter(month=month)
    # 按员工筛：employee_id= 直接比主键列，省得先查一次员工对象
    if emp_id:
        queryset = queryset.filter(employee_id=emp_id)

    # ---- 数据范围（权限之外的第二层）----
    # 部门管理员：只能看本部门员工的薪资；跨部门过滤走 employee__depart_id（自动 JOIN）
    if is_dept_admin(request.user):
        queryset = queryset.filter(employee__depart_id=request.user.depart_id)
    # 普通员工：只看自己那一条。user.employee 是登录账号绑定的员工档案，
    # 不按用户输入筛，所以前端就算改 employee 参数也看不到别人的。
    # 没绑档案时这里返回空集 —— 宁可让他看到"空列表 + 提示"，也不能退回全量。
    if is_plain_employee(request.user):
        queryset = plain_employee_scope(queryset, request.user)

    # ---- 月度薪资总额（注意：这里是重新查了一次表，不是从上面的 queryset 里算）----
    # aggregate(Sum("total")) 让 MySQL 做 SUM 聚合，只返回一个数字，
    # 而不是把几十条明细取回内存再 Python 循环累加
    # 为什么重新 filter(month=...) 而不是用上面那个 queryset：
    # 上面那个可能已经被"员工筛选"缩过范围，而这里要的是"该月总支出"这个口径，
    # 所以只按月份重新聚合、不带员工条件 —— 这是有意的业务取舍
    month_total = 0
    if month:
        # 总额也必须按权限范围算：
        #   部门管理员 → 本部门这个月的总支出
        #   普通员工   → 自己这个月的实发合计
        # 不能把全公司的数字露给普通员工，否则"只看自己工资"就没意义了。
        scope_qs = models.Salary.objects.all()
        if is_dept_admin(request.user):
            scope_qs = scope_qs.filter(employee__depart_id=request.user.depart_id)
        if is_plain_employee(request.user):
            scope_qs = plain_employee_scope(scope_qs, request.user)
        agg = scope_qs.filter(month=month).aggregate(Sum("total"))
        # 没有记录时 Sum 返回 None，`or 0` 兜底成 0，否则模板里会显示 "None"
        month_total = agg["total__sum"] or 0

    # 分页：一页 10 条
    page = Pagination(request, queryset, per_page=10)
    # 员工筛选下拉：在"这个账号能看的范围"里给全量。
    # 对超管就是不筛；对部门管理员只列本部门的人，他也就选不到别部门。
    emp_list = _emp_list_for(request.user)
    return render(
        request,
        "app01/salary/list.html",
        {
            "data_list": page.current_queryset,
            "page_html": page.page_html(),
            "emp_list": emp_list,
            "month": month,
            "emp_id": emp_id,
            "month_total": month_total,
            # 普通员工没绑员工档案 → 名单为空，模板会据此显示一行说明，
            # 否则用户只看到空表格会以为是系统坏了
            "no_binding": is_plain_employee(request.user) and not request.user.employee_id,
        },
    )


def salary_add(request):
    """
    录入薪资。

    ---- 这里修过一个真实的 bug ----
    原来直接把 request.POST 的值塞给 create()，而 POST 里拿到的是字符串 "8000"，
    模型 save() 里做 `"8000" - "300"` 会抛
    TypeError: unsupported operand type(s) for -: 'str' and 'str'，直接 500。

    现在的做法：
    1. 视图层先校验（员工、月份必填，金额必须是合法非负数字），
       不合法就把错误和用户已填内容一起回显，不落库；
    2. 模型层再兜一层 to_decimal 归一化，
       因为 admin、脚本等其它入口也可能传字符串。
    两道防线，任何入口都不会再崩。
    """
    # 员工下拉：按账号范围缩小（部门管理员只列本部门）
    emp_list = _emp_list_for(request.user)

    if request.method == "GET":
        return render(request, "app01/salary/form.html", {"emp_list": emp_list, "form_data": {}})

    # ---- 把用户输入原样留下来，校验失败时回填到表单，不用重填一遍 ----
    # 每个值都 strip：手输金额经常带空格，" 8000 " 会让后面的 Decimal 转换失败
    # 这里存的是"用户看到的原始字符串"（不是转换后的值），
    # 因为失败时要把它们原样塞回输入框
    form_data = {
        "employee": request.POST.get("employee", "").strip(),
        "month": request.POST.get("month", "").strip(),
        "base_pay": request.POST.get("base_pay", "").strip(),
        "bonus": request.POST.get("bonus", "").strip(),
        "deduction": request.POST.get("deduction", "").strip(),
    }

    # ---- 校验 1：员工必须真实存在，而且要在自己的管辖范围内 ----
    # 只判"填了没有"不够：手改请求可能传 999 或 "abc"，
    # 直接 create(employee_id="abc") 会抛 ValueError → 500。
    # isdigit() 先挡住非数字，再按主键查一次。
    emp_obj = None
    if form_data["employee"] and form_data["employee"].isdigit():
        emp_obj = models.Employee.objects.filter(pk=form_data["employee"]).first()

    errors = []
    if emp_obj is None:
        errors.append("请选择员工")
    elif is_dept_admin(request.user) and emp_obj.depart_id != request.user.depart_id:
        # 下拉框已过滤，但请求能手工构造，服务端必须再验一道
        errors.append("不能给其他部门的员工录入薪资")

    if not form_data["month"]:
        errors.append("请选择月份")

    # ---- 校验 2：金额格式 ----
    # 留空按 0 处理（奖金/扣款经常是 0），填了就必须是合法非负数字
    for label, key in (("基本工资", "base_pay"), ("奖金", "bonus"), ("扣款", "deduction")):
        value = form_data[key]
        if value and not MONEY_RE.match(value):
            errors.append(f"{label}必须是数字，最多两位小数，且不能为负")

    if errors:
        return render(
            request,
            "app01/salary/form.html",
            {"emp_list": emp_list, "form_data": form_data, "errors": errors},
        )

    # ---- 校验 3：实发不能为负 ----
    # 扣款大于"基本工资 + 奖金"在业务上不合理，提前拦住，
    # 否则列表里会出现负数实发，看起来像算错了。
    base_pay = Decimal(form_data["base_pay"] or "0")
    bonus = Decimal(form_data["bonus"] or "0")
    deduction = Decimal(form_data["deduction"] or "0")
    if base_pay + bonus - deduction < 0:
        return render(
            request,
            "app01/salary/form.html",
            {
                "emp_list": emp_list,
                "form_data": form_data,
                "errors": ["扣款不能超过「基本工资 + 奖金」，否则实发工资会变成负数"],
            },
        )

    # total 字段这里不传：由模型 save() 自动计算，
    # 避免"前端算一遍、后端再算一遍"导致两边不一致
    models.Salary.objects.create(
        employee_id=emp_obj.id,   # 用已校验过的对象取主键，不信任原始字符串
        month=form_data["month"],
        base_pay=base_pay,
        bonus=bonus,
        deduction=deduction,
    )
    return redirect("/salary/list/")


def salary_delete(request, pk):
    """删除一条薪资记录。"""
    # 只发一条 DELETE，主键不存在也不抛异常；
    # 薪资表是链尾（没有别的表引用它），删一条不会连带删数据
    models.Salary.objects.filter(pk=pk).delete()
    return redirect("/salary/list/")
