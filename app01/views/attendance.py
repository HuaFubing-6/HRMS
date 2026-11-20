"""
考勤管理（T6）
===============

三个视图：列表、录入、删除。

★ 这个模块的关键设计：**考勤状态不在视图里判断，而在模型 save() 里算。**
  视图只负责「收数据 → 校验格式 → 落库」，
  至于这条记录算正常、迟到、早退还是缺勤，统一由 models.Attendance.save() 推导。
  好处是：不管以后从哪个入口写考勤（页面、脚本、后台），判定规则只有一份。

为什么不用 ModelForm？
  考勤表的 status 是"算出来的"字段（由上下班时间推导），不是用户填的；
  两个时间字段又允许为空（表示没打卡，算缺勤）。
  这种"字段能空 + 结果靠计算"的表，用 ModelForm 反而要写一堆 exclude/clean 去绕，
  不如视图里显式校验两条规则（必填 + 格式）来得清楚。

答辩可讲点（这个模块修过一个真实 500）：
  1. 状态不在视图里判 —— 统一由 save() 按上下班时间推导，哪个入口写都一样
  2. to_time —— 修掉 "09:07" 与 time 对象比较的 TypeError（兼容带秒与不带秒）
  3. 视图只校验"填了能不能解析" —— 直接复用 to_time，不另写一套 strptime
  4. 空串必须转 None —— 否则库里留下"看着有时间"的脏数据
"""
# render 渲染模板；redirect 返回 302 跳转
from django.shortcuts import render, redirect
# models：考勤记录直接用 ORM 操作，另外还借用 Attendance.to_time() 校验时间格式
from app01 import models
# Pagination：全站公共分页组件
from app01.utils.pagination import Pagination
# is_dept_admin：部门管理员只能管本部门的考勤
# is_plain_employee / plain_employee_scope：普通员工只能看自己的考勤
from app01.utils.scope import (
    is_dept_admin,
    is_plain_employee,
    plain_employee_scope,
)


def _emp_list_for(user):
    """
    这个账号"能选的员工"范围。

    部门管理员只能选自己部门的人：下拉框里只列这些，
    否则他能在下拉框直接选到别的部门员工，绕开"不能跨部门"这条规则。
    超管和其他角色给全量。
    """
    qs = models.Employee.objects.all()
    if is_dept_admin(user):
        qs = qs.filter(depart_id=user.depart_id)
    return qs


def attendance_list(request):
    """
    考勤列表：全部记录 + 分页。

    select_related("employee")：表格里要显示每一行的员工姓名。
    不加的话，ORM 会先查 1 条记录列表，再为每行单独发一条 SQL 查员工——
    10 行就是 11 条查询（N+1）。加了之后合并成一条 JOIN。
    """
    # select_related("employee")：表格每行都要显示员工姓名，
    # 不加就是 1 条查考勤 + 每行 1 条查员工（10 行 = 11 条 SQL）；
    # 加了合并成一条 INNER JOIN
    queryset = models.Attendance.objects.all().select_related("employee")

    # 数据范围：部门管理员只看本部门员工的考勤。
    # 跨表过滤用 employee__depart_id（走过一层外键），Django 会自动 JOIN。
    # 必须放在分页之前：否则分页会按全量数据算总页数，部门管理员看到的是别人的条数。
    if is_dept_admin(request.user):
        queryset = queryset.filter(employee__depart_id=request.user.depart_id)

    # 数据范围：普通员工只看自己的考勤。
    # 和"只能看自己工资"是同一套逻辑（同一个函数），区别只在传进来的表不同。
    # 没绑员工档案时返回空集 + 页面提示，绝不退回全量。
    if is_plain_employee(request.user):
        queryset = plain_employee_scope(queryset, request.user)

    # per_page=10：一页 10 条，和其他列表页保持一致
    page = Pagination(request, queryset, per_page=10)

    # 模板里用两个变量：data_list 循环出表格行，page_html 输出分页条
    # no_binding：普通员工没绑员工档案时，模板据此显示一行说明，
    # 否则只看到空表格会以为系统坏了
    return render(
        request,
        "app01/attendance/list.html",
        {
            "data_list": page.current_queryset,
            "page_html": page.page_html(),
            "no_binding": is_plain_employee(request.user) and not request.user.employee_id,
        },
    )


def attendance_add(request):
    """
    录入考勤。

    GET  渲染空表单（需要先把员工下拉列表传过去，否则下拉是空的）
    POST 取值 → 校验 → 落库 → 跳回列表

    校验只有四条：员工必选、日期必填、上下班时间"填了就必须能被解析"。
    时间字段可以为空（表示这条记录是缺勤），所以只在"有值"时才校验格式。
    """
    # ---- GET：空表单 ----
    # 必须先把员工列表传过去，否则模板里那个 <select name="employee"> 是空的，
    # 用户根本选不了人（这是"下拉框空白"最常见的原因）
    if request.method == "GET":
        # _emp_list_for 会按当前账号缩小范围（部门管理员只列本部门员工）
        emp_list = _emp_list_for(request.user)
        return render(request, "app01/attendance/form.html", {"emp_list": emp_list})

    # ---- POST 第 1 步：取值 + 逐个 strip ----
    # 每个值都 strip：用户手输时间很容易带尾随空格，
    # "09:07 " 直接交给 strptime 会解析失败，被误判成"格式不正确"
    # (request.POST.get("x") or "")：x 不存在时 get 返回 None，or "" 兜成空串，
    # 后面统一按字符串处理，不用到处判 None
    emp_id = request.POST.get("employee")
    date = (request.POST.get("date") or "").strip()
    on_raw = (request.POST.get("on_time") or "").strip()
    off_raw = (request.POST.get("off_time") or "").strip()

    # ---- POST 第 2 步：四项校验，错误先收集再统一回显 ----
    # 不在这里写"错一条就 return"，而是一次把所有问题都收集齐，
    # 用户能一次改完，不用"改一个 → 提交 → 又冒出一个"来回折腾
    errors = []

    # 校验 a：员工不仅要"填了"，还必须真的存在。
    # 手改请求可以把 employee 传成 999 或 "abc"：
    #   直接 create(employee_id="abc") → Django 转 int 失败抛 ValueError → 500
    #   传一个不存在的 id    → 外键约束报 IntegrityError → 500
    # 所以先按主键查一次，查不到就当作"没选"。
    # str(emp_id).isdigit() 先挡住"非数字"，避免 filter(pk="abc") 自己就抛异常。
    emp_obj = None
    if emp_id and str(emp_id).isdigit():
        emp_obj = models.Employee.objects.filter(pk=emp_id).first()

    if emp_obj is None:
        errors.append("请选择员工")
    elif is_dept_admin(request.user) and emp_obj.depart_id != request.user.depart_id:
        # 部门管理员只能给本部门员工录考勤：
        # 下拉框已经过滤过一次，但请求可以手工构造，这里必须再验一道
        errors.append("不能给其他部门的员工录入考勤")

    # 校验 b：日期必填
    if not date:
        errors.append("请选择日期")

    # 校验 c / d：时间"填了就必须能解析"
    # 注意这里是 on_raw and ...：只有填了才校验格式；
    # 留空是合法的（表示没打卡，最终会被判成缺勤）
    # 判断"能不能解析"直接复用模型的 Attendance.to_time()，
    # 而不是在视图里再写一套 strptime —— 两处写两套，格式规则迟早会不一致
    if on_raw and models.Attendance.to_time(on_raw) is None:
        errors.append("上班时间格式不正确")
    if off_raw and models.Attendance.to_time(off_raw) is None:
        errors.append("下班时间格式不正确")

    # ---- POST 第 3 步：有错就带着原值回页面 ----
    if errors:
        # form_data 把用户刚填的值原样带回，模板里回填到输入框；
        # emp_list 要重新查一次，否则下拉框没选项，用户没法改员工
        return render(
            request,
            "app01/attendance/form.html",
            {
                "emp_list": _emp_list_for(request.user),
                "errors": errors,
                "form_data": {
                    "employee": emp_id,
                    "date": date,
                    "on_time": on_raw,
                    "off_time": off_raw,
                },
            },
        )

    # ---- POST 第 4 步：落库 ----
    # 只把原始字符串交给模型，由 save() 自己调 to_time() 归一化、再判定状态：
    # 视图不重复实现判定逻辑，否则两处规则迟早不一致
    # 空串必须转成 None（on_raw or None）：
    # 空字符串存进 TimeField 再取出来，会变成一条"看着有时间"的脏数据，
    # 也会让"两头都没打卡 = 缺勤"的判断失效
    models.Attendance.objects.create(
        employee_id=emp_obj.id,   # 用上面已经查到的对象取主键，不再信任原始字符串
        date=date,
        on_time=on_raw or None,
        off_time=off_raw or None,
    )
    return redirect("/attendance/list/")


def attendance_delete(request, pk):
    """
    删除一条考勤记录，然后回列表。

    考勤表没有外键指向它，删掉不会连带影响别的表，
    所以这里不做二次确认弹窗，直接在列表页提供按钮。
    """
    # filter(pk=pk).delete()：只发一条 DELETE，主键不存在也影响 0 行、不抛异常
    # 考勤表没有被任何表引用（它是链尾），删一条不会连带删别的数据，
    # 所以这里不需要二次确认，列表页给个普通按钮就够
    models.Attendance.objects.filter(pk=pk).delete()
    return redirect("/attendance/list/")
