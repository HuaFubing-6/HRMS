"""
员工管理（T3）
================

四个视图对应 CRUD，外加列表页的搜索、筛选、分页、头像上传。

答辩时可以强调两点：
1. 校验全部交给 EmployeeForm（ModelForm），视图里不写 if 判断；
2. 列表页用 select_related 把 N+1 查询压成 1 次（T11 加分项）。

答辩可讲点：
  1. 列表 —— 搜索用 GET（链接可分享、翻页能带条件），select_related 消 N+1
  2. 新增 —— data=request.POST 与 files=request.FILES 要分开传，头像才传得上来
  3. 编辑 —— instance=obj 才回填，clean_phone 里的 exclude(pk) 才成立
  4. 删除 —— filter().delete()，主键不存在也不抛异常
"""
# render 渲染模板返回 HTML；redirect 返回 302 让浏览器跳转
# get_object_or_404：主键不存在时直接回 404，而不是拿 None 去渲染模板
from django.http import HttpResponseForbidden
from django.shortcuts import render, redirect, get_object_or_404

# models 直接查数据；forms 里是 EmployeeForm（年龄范围、手机号正则、唯一性都在那）
from app01 import models, forms
# Pagination 全站公共分页组件
from app01.utils.pagination import Pagination
# is_dept_admin：判断"绑了部门的部门管理员"，用它实现"不能跨部门"
from app01.utils.scope import is_dept_admin


def employee_list(request):
    """
    员工列表：姓名模糊搜索 + 部门筛选 + 分页。

    查询参数（GET）而不是表单（POST）：
    这样链接可以被分享、刷新、收藏，分页也能把条件带在 URL 上（Pagination 里有处理）。
    """
    # ---------- 1. 取搜索条件 ----------
    # get("name", "")：参数不存在时给空串，省掉先判 None
    # strip()：去掉首尾空格，" 张 " 和 "张" 应该搜出同样的结果
    search_name = request.GET.get("name", "").strip()
    # 部门筛选：值是部门 id 的字符串；空串表示"不限部门"
    depart_id = request.GET.get("depart", "")

    # ---------- 2. 逐步加条件 ----------
    # all() 拿到的是惰性 QuerySet：此刻不发 SQL，filter 也只是往条件链上加一层
    queryset = models.Employee.objects.all()

    # icontains = 包含 + 忽略大小写，最终翻译成 SQL 的 LIKE '%张%'
    if search_name:
        queryset = queryset.filter(name__icontains=search_name)

    # depart_id=值 和 depart__id=值 等价：
    # Employee 上有 depart 字段，Django 会自动拿它的主键列来比较
    if depart_id:
        queryset = queryset.filter(depart_id=depart_id)

    # ---------- 2.5 数据范围：部门管理员只能看自己部门 ----------
    # 这是"权限"之外的"范围"：中间件只保证他有 /employee/list/ 这个 URL 的访问权，
    # 但没管他能看到哪些行；所以这里再套一层硬过滤。
    # 放在搜索条件之后：先按用户输入筛，最后再套权限闸，两条链路互不干扰。
    # 超管不进入这个分支（is_dept_admin 里排除了 is_superuser）。
    if is_dept_admin(request.user):
        queryset = queryset.filter(depart_id=request.user.depart_id)

    # ---------- 3. 消除 N+1（这是 T11 的加分点，一定要讲）----------
    # 模板里每一行都要显示 {{ obj.depart.title }}：
    #   不加 select_related → 1 条查员工 + 每行 1 条查部门 = 11 条（10 个员工时）
    #   加了之后            → ORM 生成一条 INNER JOIN，一次把部门和姓名都拿回来
    # 注意适用范围：select_related 只能跟"外键在本文"的方向（Employee 有 depart）；
    # 反向的"部门查它下面的员工"要用 prefetch_related，那是两次查询在 Python 里拼
    queryset = queryset.select_related("depart")

    # ---------- 4. 分页 ----------
    # Pagination 内部做三件事：count() 算总条数、把 ?page= 夹到 [1, 总页数]、按页切片
    page = Pagination(request, queryset, per_page=10)

    # 部门下拉框的选项：这里必须是全表，因为筛选框要列出所有部门，
    # 不能跟着上面的搜索条件走，否则选完一个部门，别的部门就从下拉框里消失了
    depart_list = models.Department.objects.all()

    return render(
        request,
        "app01/employee/list.html",
        {
            "data_list": page.current_queryset,      # 当前页的 10 条
            "page_html": page.page_html(),           # 整段分页条 HTML
            "depart_list": depart_list,              # 下拉框选项
            # 把条件回传给模板：搜索框和下拉框要保留上次选的值，
            # 否则用户搜完一翻页，条件框就变空了，看起来像"搜索没生效"
            "search_name": search_name,
            "depart_id": depart_id,
        },
    )


def employee_add(request):
    """
    新增员工。

    GET：渲染空表单。
    POST：data=request.POST（文本字段）+ files=request.FILES（头像文件）。
    头像必须单独传 files，否则 request.POST 里拿不到二进制内容。
    """
    # ---- GET：一张空表单 ----
    # 不传 data（不触发校验）、不传 instance（新建而不是编辑），字段自然全空
    # 员工表单里既有文本字段（姓名/年龄…）也有文件字段（头像），但这里不用管，
    # 模板里 每个字段都用 {{ field }} 统一渲染
    if request.method == "GET":
        form = forms.EmployeeForm()
        return render(request, "app01/employee/form.html", {"form": form})

    # ---- POST：文本 + 文件要分成两个参数传 ----
    # data=request.POST   → 姓名、年龄、手机号这些文本值
    # files=request.FILES → 头像的二进制内容（POST 字典里拿不到文件）
    # 两个都传，EmployeeForm 才能既校验文本又接住文件；
    # 前端那张 form 还必须写 enctype="multipart/form-data"，
    # 少了这个属性，request.FILES 就是空的，头像传不上来（本项目实际踩过）
    form = forms.EmployeeForm(data=request.POST, files=request.FILES)

    if form.is_valid():
        # ---- 先 save(commit=False) 拿到对象，再决定所属部门 ----
        # 校验通过才落库：
        #   文本字段 → 写进数据库
        #   头像文件 → 存到 MEDIA_ROOT/avatar/，库里只记相对路径
        # 校验失败时一行都不写，不会出现"半条脏数据"
        obj = form.save(commit=False)

        # 部门管理员新增员工时，所属部门强制为他自己管的部门：
        # 不接受前端下拉里选出来的值，否则他可以在页面上选别的部门，
        # 直接绕过"不能跨部门"这条规则。
        # 超管不受影响，表单里选哪个部门就是哪个。
        if is_dept_admin(request.user):
            obj.depart = request.user.depart

        # 补齐之后才真正 INSERT（文件字段也在这一步落盘）
        obj.save()

        return redirect("/employee/list/")

    # 校验失败：form 身上带着 errors，模板会逐字段显示第一条错误；
    # 用户已经填的文本都还在（头像因为是临时文件，页面会提示需重新选择）
    return render(request, "app01/employee/form.html", {"form": form})


def employee_edit(request, pk):
    """
    编辑员工。

    关键点是 instance=obj：告诉表单"你要校验的是这条已有记录"，
    ModelForm 才能正确回填初始值，clean_phone 里的 exclude(pk) 也才有意义。
    """
    # ---- 先按主键取原记录（不存在就 404）----
    # 这里不能用 filter().first() 拿 None 继续往下渲染：
    # 那样 /employee/edit/999/ 会打开一张看着像"编辑"的空表单，
    # 用户填完一提交，因为 instance=None，save() 执行的是 INSERT ——
    # 本来想改一条，结果凭空多出一条，这是最难排查的那类 bug。
    # get_object_or_404 直接把"主键不存在"说清楚，也和部门编辑的处理保持一致。
    obj = get_object_or_404(models.Employee, pk=pk)

    # ---- 跨部门拦截 ----
    # 部门管理员即使手改 URL 拿到别的部门员工的 id，也不允许打开编辑页：
    # 列表已经过滤过一次，这里是第二道闸（防止直接调接口）。
    # 返回 403 而不是 404：这条员工确实存在，只是不归他管。
    if is_dept_admin(request.user) and obj.depart_id != request.user.depart_id:
        return HttpResponseForbidden("403 不能管理其他部门的员工")

    # ---- GET：带 instance 回填 ----
    # instance=obj 让每个字段从原记录取值：姓名、年龄、部门下拉框都会预先选中；
    # 头像字段存的是路径，页面上显示"当前文件"链接，不选新文件就保持原图不变
    # 多传一个 obj 是给模板用的：form.html 一页两用，靠 obj 判断标题写"编辑"还是"新增"
    if request.method == "GET":
        form = forms.EmployeeForm(instance=obj)
        return render(request, "app01/employee/form.html", {"form": form, "obj": obj})

    # ---- POST：三样参数一起给 ----
    # data + files → 用户新填的文本、新选的头像
    # instance     → 要改的是哪一条（save() 会变成 UPDATE，不会新增一行）
    # clean_phone 里的唯一性校验靠 instance 才能成立：
    # 它会用 instance.pk 排除自己，否则"改自己的资料但手机号没改"也会被判成重复
    form = forms.EmployeeForm(data=request.POST, files=request.FILES, instance=obj)

    if form.is_valid():
        form.save()
        return redirect("/employee/list/")

    # 校验失败：obj 必须继续传，否则模板判断不出"这是编辑页"，
    # 标题会退回成"新增员工"，用户会以为自己填错页了
    return render(request, "app01/employee/form.html", {"form": form, "obj": obj})


def employee_delete(request, pk):
    """
    删除员工。

    这里用 filter().delete() 而不是 get().delete()：
    pk 不存在时 filter 返回空集，delete 什么也不做，不会抛 DoesNotExist 让页面 500。
    """
    # ---- 跨部门拦截：删别人部门的人一律 403 ----
    # 列表里看不到他，但手改 URL 仍能发出这条请求，所以删除这里也要拦一道。
    # 先取对象是为了拿它的 depart_id；取不到（pk 不存在）就直接走到下面
    # filter().delete() 的空操作分支，不报错。
    obj = models.Employee.objects.filter(pk=pk).first()
    if obj and is_dept_admin(request.user) and obj.depart_id != request.user.depart_id:
        return HttpResponseForbidden("403 不能删除其他部门的员工")

    # filter(pk=pk).delete() 只发一条 DELETE，不先把对象读出来：
    #   get(pk=pk).delete()    → 先 SELECT 再 DELETE，pk 不存在时抛 DoesNotExist（500）
    #   filter(pk=pk).delete() → 主键不存在就影响 0 行，页面照常跳回列表
    # 连带影响：考勤、薪资、任务的外键都是 CASCADE，删员工会把这些一起删掉，
    # 所以列表面上的删除按钮带 confirm 二次确认
    models.Employee.objects.filter(pk=pk).delete()
    return redirect("/employee/list/")
