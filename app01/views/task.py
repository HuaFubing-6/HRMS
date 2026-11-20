"""
任务管理（T9，AJAX 异步提交）
==============================

这是整个项目里唯一"不刷新页面"的模块，答辩时通常是老师最感兴趣的加分点。

传统同步提交 vs AJAX 提交：
    同步：点提交 → 整页 POST → 后端校验失败 → 重新渲染整页 → 用户重新填
    AJAX：点提交 → $.ajax POST → 后端返回 JSON → 只把错误填到对应输入框下方

关键约定（前后端接口契约）：
    成功：{"status": true,  "msg": "添加成功"}
    失败：{"status": false, "msg": "校验失败", "errors": {"title": "标题至少 2 个字符"}}
前端用 errors 的 key 去拼 DOM id（#err_title）回显。

答辩可讲点（全项目唯一的"不刷新页面"模块，加分点）：
  1. 接口契约 —— status / msg / errors 三段，前端按 errors 的 key 回显到对应输入框
  2. 为什么不用 @require_POST —— 手动判断可以顺便返回一条 JSON，而不是 405 的 HTML
  3. 为什么只有"新增"用 AJAX —— 编辑要先知道改哪一条、还要回填，同步表单更直白
  4. errors 只取第一条 —— 一个字段下面只显示一句提示
"""
# JsonResponse：把字典序列化成 JSON 返回，前端 $.ajax 直接拿到对象；
# 它不允许传字符串（必须给可序列化的 dict/list）
from django.http import JsonResponse, HttpResponseForbidden
# Q：构造 "或者" 条件（本部门 or 全公司 or 自己发的），filter 里用竖线做不到这种组合
from django.db.models import Q
# render 渲染列表页/表单页；redirect 用于编辑和删除后的跳转
from django.shortcuts import render, redirect

# models 查任务和员工；forms 里的 TaskForm 负责"标题至少 2 个字符"等校验
from app01 import models, forms
# Pagination 全站公共分页组件
from app01.utils.pagination import Pagination
# is_dept_admin / is_plain_employee：决定这个账号能看到哪些任务
from app01.utils.scope import is_dept_admin, is_plain_employee


def task_list(request):
    """
    任务列表页：渲染表单 + 已提交的任务表格。

    select_related("leader")：表格里要显示负责人姓名，避免 N+1。
    """
    # select_related("leader")：表格每行要显示负责人姓名，
    # 不加就是 N+1（1 条查任务 + 每行 1 条查员工）；加了合并成一条 JOIN
    # 注意字段名是 leader（负责人），不是 employee —— Task 模型里就叫这个
    queryset = models.Task.objects.all().select_related("leader")

    # ---- 可见范围（第三层：数据范围）----
    # 超管不进任何分支 → 直接看到全部，这是"超管能看见所有任务"的实现方式
    if is_dept_admin(request.user):
        # 部门管理员看三类：本部门的、全公司的、以及自己发出去的
        # 用 Q 拼"或"：filter 里逗号是"且"，竖线只能在 Q 对象之间用
        queryset = queryset.filter(
            Q(depart_id=request.user.depart_id)
            | Q(depart__isnull=True)
            | Q(publisher=request.user)
        ).distinct()   # 三个条件可能同时命中同一条，distinct 去重
    elif is_plain_employee(request.user):
        # 普通员工：只看到"自己负责、而且已经通过审核"的任务。
        # 待审核/被驳回的对他不可见 —— 还没批准的事不该先派到人头上。
        if request.user.employee_id:
            queryset = queryset.filter(
                leader_id=request.user.employee_id, status="approved"
            )
        else:
            # 没绑员工档案的普通员工，不知道"自己负责哪些"，给空集
            queryset = queryset.none()

    # 任务列表也要分页，和别的列表页共用同一个组件
    page = Pagination(request, queryset, per_page=10)

    # 这个页面一页两用：上半部分是"新增任务"的 AJAX 表单，
    # 所以要同时把员工列表传过去（负责人下拉框要用）
    # 部门管理员只能把任务派给本部门的人，下拉也只列本部门，
    # 否则他能在下拉里选到别的部门员工，绕开"不能跨部门"这条规则
    if is_dept_admin(request.user):
        emp_list = models.Employee.objects.filter(depart_id=request.user.depart_id)
    else:
        emp_list = models.Employee.objects.all()

    return render(
        request,
        "app01/task/list.html",
        {
            "data_list": page.current_queryset,   # 当前页任务
            "page_html": page.page_html(),        # 分页条
            "emp_list": emp_list,                 # 负责人下拉选项
            # can_audit：模板据此决定要不要渲染"通过/驳回"按钮。
            # 只有超管为 True；视图里的 task_audit 还会再验一次超管身份，
            # 模板隐藏只是"不给他看按钮"，真正拦请求的是视图和中间件
            "can_audit": request.user.is_superuser,
        },
    )


def task_add(request):
    """
    AJAX 提交入口：只接受 POST，永远返回 JSON，不返回 HTML。

    为什么不用 @require_POST？
    这里手动判断是为了顺便返回一条 JSON 提示；
    如果用装饰器，GET 访问会得到 405 的 HTML 页面，前端 $.ajax 拿到非 JSON 反而不好处理。
    """
    # ---- 只接受 POST ----
    # 非 POST（比如有人在地址栏直接打开 /task/add/）就返回一条 JSON 提示，
    # 而不是抛 405 的 HTML 错误页 —— 因为调用它的是 $.ajax，
    # 前端拿到 HTML 反而不知道怎么处理
    if request.method != "POST":
        return JsonResponse({"status": False, "msg": "仅支持 POST"})

    # ---- 用 TaskForm 做校验 ----
    # 校验规则（标题至少 2 个字符、负责人必须是已存在的员工、级别只能 1/2/3）
    # 全部写在 TaskForm 里，这里不重复写 if
    form = forms.TaskForm(data=request.POST)

    if form.is_valid():
        # 校验过了才落库：TaskForm 是 ModelForm，save() 直接 INSERT 一条
        # ---- 先 commit=False 拿到对象，补三个"表单里没有"的字段 ----
        # 发布人、归属部门、审核状态都不该由前端决定：
        #   发布人 → 谁登录谁发的，前端改了就能冒充别人发布
        #   归属部门 → 部门管理员必须落在自己部门，否则能冒充别的部门发任务
        #   审核状态 → 必须由系统定，不能让前端直接传 "approved" 跳过审核
        obj = form.save(commit=False)
        obj.publisher = request.user

        if is_dept_admin(request.user):
            # 部门管理员：任务归自己部门，且要等超管审核
            obj.depart = request.user.depart
            obj.status = "pending"
        elif request.user.is_superuser:
            # 超管：发的是全公司任务，自己发的不需要再自己审
            obj.depart = None
            obj.status = "approved"
        else:
            # 其他角色（理论上没有任务发布权限，兜底也给待审核）
            obj.status = "pending"

        obj.save()
        return JsonResponse({"status": True, "msg": "添加成功"})

    # ---- 校验失败：把 form.errors 转成前端好用的 dict ----
    # form.errors 的结构是 {"字段名": ["错误1", "错误2", ...]}，
    # 一个字段可能有多个错误，但前端每个输入框下面只显示一句，
    # 所以取 errs[0] 只保留第一条
    # 转成普通 dict 是因为 ErrorList 不能被 JSON 序列化
    errors = {field: errs[0] for field, errs in form.errors.items()}

    # status=False + errors 字典：前端用 key 拼出 #err_字段名 的 id，
    # 把提示塞到对应输入框下方（这就是"不用刷新整页"的关键）
    return JsonResponse({"status": False, "msg": "校验失败", "errors": errors})


def task_edit(request, pk):
    """
    编辑任务。

    为什么编辑不用 AJAX，而是退回同步表单？
    ---- 新增用 AJAX 是为了演示"提交不刷新"这个技术点；
    ---- 编辑的入口在表格的某一行，需要先知道要改哪一条（主键来自 URL），
         还要把原来的值回填进表单，做成同步页面最直白，也少一层前端状态管理。
    这就是"按场景选技术"，而不是"为了 AJAX 而 AJAX"——答辩可以主动说这一点。

    核心是 `TaskForm(data=request.POST, instance=obj)`：
    传了 instance，表单解析出来的就是"改动后的这一条"，
    is_valid() 过后 save() 直接 UPDATE 原记录，不会新增一条。
    校验同样沿用 TaskForm（标题至少 2 字符），所以规则只需要维护一份。
    """
    # ---- 先按主键找到要改的那一条 ----
    # filter().first()：pk 不存在时返回 None，下面直接回列表页，
    # 不用 get() 免得抛 DoesNotExist 变 500
    obj = models.Task.objects.filter(pk=pk).first()
    if not obj:  # 主键不存在（比如手改了 URL），回列表页，不要报 500
        return redirect("/task/list/")

    # 负责人下拉框的选项：编辑页和新增页都要用
    emp_list = models.Employee.objects.all()

    if request.method == "GET":
        # 模板里用 obj 的当前值回填 级别 / 标题 / 详情 / 负责人：
        # 不是靠 form 回填（这个编辑页没用 ModelForm 渲染），
        # 而是模板里直接写 value="{{ obj.title }}"、<option selected> 之类
        return render(request, "app01/task/form.html", {"obj": obj, "emp_list": emp_list})

    # ---- POST：data + instance 一起给 ----
    # instance=obj 让 save() 变成 UPDATE，不会新增一条；
    # 校验规则仍然沿用同一个 TaskForm（标题至少 2 字符），只维护一份
    form = forms.TaskForm(data=request.POST, instance=obj)

    if form.is_valid():
        form.save()
        return redirect("/task/list/")

    # ---- 校验失败：同样是异步？不是，这里是同步页面 ----
    # 只取第一条错误塞进 errors 字典，模板里在对应输入框下方显示
    errors = {field: errs[0] for field, errs in form.errors.items()}
    return render(
        request,
        "app01/task/form.html",
        {"obj": obj, "emp_list": emp_list, "errors": errors},
    )


def task_delete(request, pk):
    """
    删除任务。

    删除用 filter(pk=pk).delete() 而不是 obj.delete()：
    主键不存在时不会抛异常，静默跳过，页面照常跳回列表。
    （前端的 confirm 提示负责防手滑，这里只做数据操作。）
    """
    # filter(pk=pk).delete()：主键不存在也只影响 0 行，页面照常跳走；
    # 前端那个 confirm 弹窗负责防手滑，这里只做数据操作，不做二次确认
    models.Task.objects.filter(pk=pk).delete()
    return redirect("/task/list/")


def task_audit(request, pk, action):
    """
    审核任务：超级管理员专用。

    action=pass 通过、action=reject 驳回，写在 URL 里而不是纸上加一个下拉框：
    两个动作就是两个固定地址，不需要前端提交表单，也不需要多一个字段。
    （对比：如果做成一个 form，就要 POST 一个 status 字段，还得再防一遍伪造）
    """
    # 超管身份在视图里再确认一次。
    # 模板里隐藏按钮只是"不给他看"，手敲地址照样能进来，
    # 所以真正的门禁必须写在这里，不能只靠模板
    if not request.user.is_superuser:
        return HttpResponseForbidden("403 只有超级管理员可以审核任务")

    obj = models.Task.objects.filter(pk=pk).first()
    if obj:
        # 一个表达式定两个结果：pass → approved，其余 → rejected
        obj.status = "approved" if action == "pass" else "rejected"

        # 驳回时顺手把"已完成"清掉：
        # 否则一条任务可能同时是"已驳回"和"已完成"，状态自相矛盾，
        # 后面统计"本月完成了多少任务"也会把被驳回的算进去
        if obj.status == "rejected":
            obj.is_done = False

        obj.save()   # 只更新这一条的几个字段

    return redirect("/task/list/")


def task_done(request, pk):
    """
    标记任务已完成。

    谁能点：超管、任务发布人、任务负责人本人。
    URL 级权限控制不了"哪一条"，所以把"能不能操作这一条"的判断放在视图里，
    这也是 RBAC 到行级（数据级）权限的一个典型做法。
    """
    obj = models.Task.objects.filter(pk=pk).first()
    if not obj:  # 主键不存在（手改 URL），安静回列表
        return redirect("/task/list/")

    # 三个身份满足任意一个即可：
    #   超管：全站管理
    #   发布人：我提的任务我自己负责推进
    #   负责人：任务派给我的，我干完了要能勾
    allowed = (
        request.user.is_superuser
        or obj.publisher_id == request.user.id
        or (request.user.employee_id and obj.leader_id == request.user.employee_id)
    )
    if not allowed:
        return HttpResponseForbidden("403 只能标记自己负责的任务")

    # 只有审核通过的任务才能完成：
    # 否则"被驳回"的任务也能打勾，列表里会出现自相矛盾的状态
    if obj.status != "approved":
        return redirect("/task/list/?err=not_approved")

    obj.is_done = True
    obj.save()
    return redirect("/task/list/")
