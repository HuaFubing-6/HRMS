"""
用户管理 / 角色管理（T5 的"配置界面"部分）
============================================

中间件负责"拦"，这两个模块负责"配"：
管理员在这里建账号、建角色、给角色勾权限。

为什么角色配完权限要重新登录？
因为权限列表是登录时缓存进 session 的（为了每个请求不查库）。
改完权限后，已登录用户的 session 里还是旧列表，
退出重进才会重新加载 —— 这是性能与实时性的取舍。

答辩可讲点（"权限怎么配"这一问的答案就在这儿）：
  1. 中间件负责"拦"、这两个模块负责"配" —— 建账号、建角色、勾权限
  2. 密码为什么必须 make_password —— 直接 create(password="123") 会存明文，登录也必失败
  3. getlist 而不是 get —— 多选框同名参数会出现多次，get 只拿到最后一个
  4. 权限整体替换（set）—— 用户看到的勾选状态就是最终结果，取消的也要真被摘掉
  5. 超管角色不允许删 —— 它不是一条数据，是最高权限入口
"""
from django.contrib.auth.hashers import make_password
from django.shortcuts import render, redirect

from app01 import models


def user_list(request):
    """用户列表：显示角色，select_related 避免每行查一次角色表。"""
    # select_related("role")：列表每行要显示角色名，
    # 不加就是 1 条查用户 + 每行 1 条查角色（N+1）；加了合并成一条 JOIN
    # 注意 role 可能为空（SET_NULL 的结果），模板里用 default:"-" 兜底显示"-"
    # select_related 三个外键：列表要同时显示角色名、管辖部门、对应员工。
    # 一次 JOIN 全拿回来，避免"每行 3 次额外查询"的 N+1。
    # 注意 role / depart / employee 都可能为 NULL，模板里一律用 default:"-" 兜底。
    queryset = models.User.objects.all().select_related("role", "depart", "employee")

    # 用户表不带分页（账号数量少，一页全列出来更省事），
    # 删除被拒时由 user_delete() 带 ?err=last_super 回来，这里翻译成一句提示
    error = ""
    if request.GET.get("err") == "last_super":
        error = "系统里只剩这一个超级管理员，删掉就没人能管理权限了。请先新建一个超管，再删这个。"

    # 所以直接把整个 queryset 交给模板循环
    return render(request, "app01/user/list.html", {"data_list": queryset, "error": error})


def user_add(request):
    """
    新增用户。

    ---- 密码为什么必须 make_password？----
    如果直接 User.objects.create(password="123")，
    库里存的就是明文 "123"，任何人打开数据库都能看到，
    而且登录时 check_password 也会失败（它期待的是哈希串）。
    make_password 会把明文转成 PBKDF2 哈希再入库，
    和 create_user 内部做的事完全一样。
    """
    # ---- GET：空表单 + 三个下拉框 ----
    # 这里没有用 ModelForm，是因为 User 继承自 AbstractUser，
    # 它的 password 字段是哈希串；用 ModelForm 渲染会把哈希值填进输入框，
    # 所以手写表单、自己处理这几个字段更直接
    # 三个下拉各有用途：角色决定身份，管辖部门给部门管理员用，对应员工给普通员工用
    if request.method == "GET":
        return render(
            request,
            "app01/user/form.html",
            {
                "role_list": models.Role.objects.all(),
                "depart_list": models.Department.objects.all(),
                "emp_list": models.Employee.objects.all(),
            },
        )

    # ---- POST：取五个值 ----
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()
    role_id = request.POST.get("role")
    # 两个可选字段：部门管理员才需要 depart，普通员工才需要 employee
    depart_id = request.POST.get("depart")
    employee_id = request.POST.get("employee")

    # 出错的统一上下文：三份下拉列表每次都要带回去，否则用户没法改选
    err_ctx = {
        "role_list": models.Role.objects.all(),
        "depart_list": models.Department.objects.all(),
        "emp_list": models.Employee.objects.all(),
    }

    if not username or not password:
        err_ctx["error"] = "用户名密码不能为空"
        return render(request, "app01/user/form.html", err_ctx)

    # 一个员工档案只能绑一个账号（模型里是 OneToOne，重复绑会抛 IntegrityError → 500）
    # 这里先查一次，给用户一句人话，而不是一个红色错误页
    if employee_id and models.User.objects.filter(employee_id=employee_id).exists():
        err_ctx["error"] = "这个员工已经绑定了别的账号，一个员工只能有一个登录账号"
        return render(request, "app01/user/form.html", err_ctx)

    # ---- 落库 ----
    # password=make_password(password)：明文进、哈希出
    # 三个 id 都走 `or None`：空串表示"不填"，存 None 而不是空字符串
    models.User.objects.create(
        username=username,
        password=make_password(password),   # 明文进、哈希出
        role_id=role_id or None,            # 允许暂不分配角色
        depart_id=depart_id or None,        # 只有部门管理员需要
        employee_id=employee_id or None,    # 只有普通员工需要
    )

    # 建完跳回列表，新账号会出现在表格里
    return redirect("/user/list/")


def user_delete(request, pk):
    """
    删除用户。

    ---- 一条硬性保护：不许删掉系统里最后一个超级管理员 ----
    超管是唯一"不依赖权限表也能进用户/角色管理"的账号
    （中间件里 is_superuser 直接放行）。把它删掉之后，
    没有人能再分配角色和权限，系统等于永久锁死，只能进数据库手改。
    所以删之前先数一遍超管人数。
    """
    # 先取对象，判断"要删的这个是不是超管"
    obj = models.User.objects.filter(pk=pk).first()

    # 只有真要删的是超管才需要数一遍；普通账号直接放行
    # count() <= 1 表示"就剩他了"，此时拒绝，并带 ?err=last_super 回列表页提示
    if obj and obj.is_superuser and models.User.objects.filter(is_superuser=True).count() <= 1:
        return redirect("/user/list/?err=last_super")

    # 这名用户发的公告是 CASCADE，会一起被删掉（删账号前要想到这点）
    # filter(pk=pk).delete()：主键不存在也只影响 0 行，页面照常跳走
    models.User.objects.filter(pk=pk).delete()
    return redirect("/user/list/")


def role_list(request):
    """
    角色列表：显示每个角色挂了多少权限。

    ?err=super 用来在"想删超级管理员被拒"之后回显一句提示——
    删除拦截发生在 role_delete()，但它只能 redirect 回来，没法直接弹窗，
    所以用 query 参数把结果带回列表页。
    """
    queryset = models.Role.objects.all()

    # 两种被拒情况各给一句人话：
    #   err=super       想在列表里删超管角色
    #   err=super_edit  想在编辑页改超管角色
    err = request.GET.get("err")
    error = ""
    if err == "super":
        error = "超级管理员是最高权限角色，不允许删除。"
    elif err == "super_edit":
        error = "超级管理员角色不允许改名字或删减权限，否则最高权限会被改瘸。"

    return render(request, "app01/role/list.html", {"data_list": queryset, "error": error})


def role_add(request):
    """
    新增角色并勾选权限。

    request.POST.getlist("permissions")：
    前端是多选框，同名参数会出现多次，
    用 getlist 才能拿到完整列表（用 get 只会拿到最后一个）。
    permissions.set(ids) 会自动替换掉旧关联，不需要手动 clear。
    """
    perm_list = models.Permission.objects.all()

    if request.method == "GET":
        return render(request, "app01/role/form.html", {"perm_list": perm_list, "checked": [], "title_value": ""})

    title = request.POST.get("title", "").strip()
    perm_ids = request.POST.getlist("permissions")
    # 模板里要用 p.id in checked 判断勾选，p.id 是整数，
    # 而 POST 拿到的 id 是字符串，类型对不上会永远判为"未勾选"，所以统一转成 int
    checked = [int(i) for i in perm_ids if i.isdigit()]

    # 角色名在模型里是 unique=True，重名会直接抛 IntegrityError（500），
    # 所以先手动校验一次，给用户一句人话提示。
    if not title:
        return render(request, "app01/role/form.html",
                      {"perm_list": perm_list, "checked": checked, "title_value": "",
                       "error": "角色名称不能为空"})
    if models.Role.objects.filter(title=title).exists():
        return render(request, "app01/role/form.html",
                      {"perm_list": perm_list, "checked": checked, "title_value": title,
                       "error": "角色名称已存在，请换一个"})

    role = models.Role.objects.create(title=title)
    role.permissions.set(perm_ids)
    return redirect("/role/list/")


def role_edit(request, pk):
    """
    编辑角色：改名字 + 重新勾权限。

    权限是整体替换（permissions.set），不是增量追加：
    用户在页面上看到的勾选状态就是他期望的最终结果，
    取消勾选的权限也应该真的被摘掉，所以先用 set() 覆盖。
    """
    obj = models.Role.objects.filter(pk=pk).first()
    if not obj:
        return redirect("/role/list/")

    # ---- 超级管理员角色：整页拒绝编辑 ----
    # 两个理由：
    #   1. 它的权限必须永远是"全量"。允许在这里改，就等于允许把最高权限改瘸，
    #      而且改完超管自己不受影响（中间件靠 is_superuser 放行），
    #      问题要等下一个账号登录才暴露，很难查。
    #   2. role_delete() 是靠 title == "超级管理员" 来拦截删除的。
    #      如果这里允许改名，改完名字删除保护就形同虚设 —— 堵住这个后门。
    if obj.title == "超级管理员":
        return redirect("/role/list/?err=super_edit")

    perm_list = models.Permission.objects.all()

    if request.method == "GET":
        # checked 传 id 列表，模板里判断"这个权限该不该打勾"
        checked = list(obj.permissions.values_list("id", flat=True))
        return render(request, "app01/role/form.html",
                      {"obj": obj, "perm_list": perm_list, "checked": checked, "title_value": obj.title})

    title = request.POST.get("title", "").strip()
    perm_ids = request.POST.getlist("permissions")
    checked = [int(i) for i in perm_ids if i.isdigit()]   # 同上：统一成 int 才能和 p.id 比对

    error = ""
    if not title:
        error = "角色名称不能为空"
    elif models.Role.objects.exclude(pk=pk).filter(title=title).exists():
        error = "角色名称已被其他角色占用"

    if error:
        # 出错时把"用户刚输入的标题"和"刚勾的权限"带回去，别让他重填一遍
        return render(request, "app01/role/form.html",
                      {"obj": obj, "perm_list": perm_list, "checked": perm_ids,
                       "title_value": title, "error": error})

    obj.title = title
    obj.save()
    obj.permissions.set(perm_ids)
    return redirect("/role/list/")


def role_delete(request, pk):
    """
    删除角色。

    两个保护：
    1. 超级管理员角色不允许删 —— 它不是"一条数据"，它是系统的最高权限入口，
       删掉之后新账号就没有可继承的角色了，演示现场也不好恢复。
    2. 用户表的 role 外键是 SET_NULL，所以删角色不会连带删账号，
       这些账号只是变成"无角色"，重新分配即可。
    """
    # ---- 超管角色保护（第一层）----
    # obj 可能为 None（手改 URL），所以先判 obj 再判名字，避免 None.title 报错
    # 命中就直接 redirect 回列表，并带上 ?err=super 让列表页显示提示
    obj = models.Role.objects.filter(pk=pk).first()
    if obj and obj.title == "超级管理员":
        return redirect("/role/list/?err=super")

    # ---- 真正删除（第二层保护在数据库）----
    # 角色被删时，User.role 是 SET_NULL：账号不会跟着消失，只是变成"无角色"
    # 所以这里可以放心删，不需要额外检查"有没有人在用这个角色"
    models.Role.objects.filter(pk=pk).delete()
    return redirect("/role/list/")
