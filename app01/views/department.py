"""
部门管理（T2）——整个项目最简单的 CRUD，用来打通 MTV 链路
=========================================================

为什么先做部门？
因为它是唯一没有外键、没有图片、没有业务计算的表，
可以最省成本地把「模型 → 路由 → 视图 → 模板」这条线跑通，
后面员工等复杂模块直接套同样的骨架。

★ 结构对齐说明
本学期项目按教学脚手架规范重构了管理层：
- 校验规则从"视图里手写 if"挪到 utils/form.py 的 DepartmentForm.clean_title；
- 新建/编辑共用 app01/templates/app01/change.html 一张页面，靠 title 区分；
- 视图只留三件事：收数据 → 交给表单 → 决定跳转。
这就是模板第 6 章说的"一个模块的标准 CRUD 套路"，
后面加别的简单表照这个抄即可。

答辩可讲点（"标准 CRUD 套路"这一问就指这里）：
  1. 一个模块只要四件事：list / add / edit / delete，视图只做"取数据 → 交表单 → 跳转"
  2. 校验不在视图里写 if —— 交给 utils/form.py 的 DepartmentForm.clean_title
  3. 新建/编辑共用一张 change.html —— add 不传 instance、edit 传 instance=obj
  4. 删除要说清连带影响 —— CASCADE 会连带删掉该部门下的员工及其考勤/薪资
"""
# get_object_or_404：主键查不到时直接回 404，省掉自己写 if 判断
# redirect：返回 302 让浏览器跳到另一个地址；render：把模板渲染成 HTML 返回
from django.shortcuts import get_object_or_404, redirect, render

# models：直接用 ORM 查数据（列表、删除这类不需要表单的场景）
from app01 import models
# DepartmentForm：部门的所有校验规则（不能为空、不能重名）都在这一个类里，
# 视图只负责调用它，不写 if
from app01.utils.form import DepartmentForm
# Pagination：全站公共的分页组件，所有列表页都用它，保证页码条样式一致
from app01.utils.pagination import Pagination
# is_dept_admin：部门管理员只看自己那个部门
from app01.utils.scope import is_dept_admin


def department_list(request):
    """
    列表：查全部 + 分页。

    ---- 这个函数只有三步，但每一步都有讲究 ----
    第 1 步  取数据：Department.objects.all() 拿到的是「惰性 QuerySet」，
             此刻还不会发 SQL，只有后面 count()、切片、循环时才真正查库；
    第 2 步  分页：Pagination 内部会 count() 一次（第 1 条 SQL），
             再切出当前页的 10 条（第 2 条 SQL，带 LIMIT/OFFSET），
             所以"共 N 条"和表格里的数据是同一份 QuerySet 算出来的，不会对不上；
    第 3 步  渲染：交给模板，页面本身不含任何查询逻辑。
    """

    # 全表查询。部门表没有外键、也没有搜索条件，
    # 所以既不用 filter()，也不用 select_related()（没有关联表可 JOIN）
    queryset = models.Department.objects.all()

    # 数据范围：部门管理员只看到自己管的那一个部门。
    # 他本来就不该有配置部门结构的权限，列表里只剩自己部门，
    # 也就不会出现"能点别的部门的删除按钮"这种情况。
    if is_dept_admin(request.user):
        queryset = queryset.filter(id=request.user.depart_id)

    # per_page=10：一页 10 条，对齐参考截图的行数。
    # Pagination 干三件事：
    #   ① 算总条数、总页数（空表时兜底成 1 页）
    #   ② 把地址栏的 ?page= 夹到 [1, 总页数]，传 abc 或 999 都不报错
    #   ③ 按当前页切片，只取这一页的 10 条
    page = Pagination(request, queryset, per_page=10)

    # render(request, 模板路径, 上下文字典)
    # 模板里能用的两个变量就是字典里的两个 key：
    #   data_list —— 循环出表格的每一行（当前页的 10 个部门）
    #   page_html —— 一整段 <ul class="pagination">，模板里写 {{ page_html }} 即可
    #                （后端已经 mark_safe 过，模板不要再加 |safe，否则会重复标记）
    # 删除被拒时，department_delete() 会带 ?err=has_emp&n=3 回来，
    # 在这里翻译成一句人话，交给模板显示
    error = ""
    if request.GET.get("err") == "has_emp":
        error = (
            f"该部门还有 {request.GET.get('n', '0')} 名员工，"
            "请先在员工管理里把他们转到其他部门，再回来删除。"
        )

    return render(
        request,
        "app01/department/list.html",
        {"data_list": page.current_queryset, "page_html": page.page_html(), "error": error},
    )


def department_add(request):
    """
    新增部门。

    GET  渲染空表单
    POST 表单校验 → 通过则 save() → 跳回列表；不通过则带着错误重新渲染

    注意没有 obj 参数：新建时 ModelForm 不传 instance，
    所有控件自然是空的。
    """
    # ---- GET：渲染一张空表单 ----
    # 这里给 change.html 传了三个 key，缺一个页面就不完整：
    #   form     —— 表单对象，模板里 {{ form.title }} 渲染出输入框
    #   title    —— 页面标题栏显示的文字，"新增部门" vs "编辑部门"
    #   back_url —— 取消/返回按钮跳回哪里
    # 注意新建时 DepartmentForm() 不带任何参数：
    # 不传 instance，字段就全是空的；不传 data，就不会触发校验
    if request.method == "GET":
        return render(
            request,
            "app01/change.html",
            {"form": DepartmentForm(), "title": "新增部门", "back_url": "/department/list/"},
        )

    # ---- POST：拿用户提交的数据构造表单 ----
    # data=request.POST 是关键字参数，不能省：
    # 省掉的话 Django 会以为这是"绑定到某个实例"，校验永远是 False
    form = DepartmentForm(data=request.POST)

    # is_valid() 会按顺序跑：字段类型 → 字段约束（max_length 等）→ clean_title
    # 其中 clean_title 里判了"不能为空"和"不能重名"，所以视图里一个 if 都不用写
    if form.is_valid():
        # 校验通过的 ModelForm，save() 内部直接 INSERT 一行，字段值从 form.cleaned_data 取
        form.save()
        return redirect("/department/list/")

    # 校验失败：把"填过的值 + 错误信息"一起送回页面，
    # form 对象此刻身上已经带着 errors，模板用 {{ form.title.errors.0 }} 显示第一条错误，
    # 输入框也会保留用户刚填的内容，不用重填一遍
    return render(
        request,
        "app01/change.html",
        {"form": form, "title": "新增部门", "back_url": "/department/list/"},
    )


def department_edit(request, pk):
    """
    编辑部门。

    和新增只差两处：
    1. instance=obj —— ModelForm 会把这条记录的值填进控件；
    2. 标题改成"编辑部门"。
    """
    # ---- 先找到要改的那一条 ----
    # pk 来自 URL 里的 <int:pk>，Django 已经保证它是整数。
    # 用 get_object_or_404 而不是 filter().first()：
    # 地址栏被手改成一个不存在的主键时，这里直接回 404（页面明确说"不存在"），
    # 而不是拿一个 None 去渲染模板，在模板里访问 obj.title 时崩成 500。
    # 它顺便还省掉一次自己写 if obj is None: return redirect(...) 的判断。
    obj = get_object_or_404(models.Department, pk=pk)

    # ---- GET：带上 instance 渲染，输入框自动填原来的值 ----
    # instance=obj 是 ModelForm 的关键参数：它告诉表单"你要编辑的是这条记录"，
    # Django 会逐个字段从 obj 上取值作为初始值。
    # 不传 instance 的话，页面就是一张空白表单，用户得把部门名重打一遍。
    if request.method == "GET":
        return render(
            request,
            "app01/change.html",
            {"form": DepartmentForm(instance=obj), "title": "编辑部门", "back_url": "/department/list/"},
        )

    # ---- POST：data + instance 两个参数一起给 ----
    # data=request.POST 是"用户新填的值"，instance=obj 是"要改的是哪一条"。
    # 两者缺一不可：
    #   只给 data        → 会当成新建，save() 变成 INSERT，库里多一条
    #   只给 instance    → 表单没有新数据，校验永远不通过
    form = DepartmentForm(data=request.POST, instance=obj)

    if form.is_valid():
        # 因为带了 instance，这里的 save() 执行的是 UPDATE 而不是 INSERT：
        # Django 拿 obj 的主键去改原来那一行，不会新增记录
        form.save()
        return redirect("/department/list/")

    # 校验失败：同样要把 instance 一起带回去，
    # 否则模板里拿不到 obj，页面上"编辑部门"的上下文就断了；
    # 同时 form 身上带着 errors 和用户刚输入的值，错误提示和已填内容都会保留
    return render(
        request,
        "app01/change.html",
        {"form": form, "title": "编辑部门", "back_url": "/department/list/"},
    )


def department_delete(request, pk):
    """
    删除部门。

    ---- 删除的前提：这个部门里已经没有员工了 ----
    Employee.depart 是 CASCADE，直接删会连带删掉该部门所有员工，
    再往下还会删掉他们的考勤、薪资、负责的任务。一次误点可能抹掉好几张表的数据，
    而且删掉的数据是找不回来的（这是最不该用 CASCADE 的地方之一）。

    正确的"转移"顺序（答辩被问"想删一个还有人的部门怎么办"就这么答）：
        员工管理 → 编辑该员工 → 把"所属部门"改成别的部门 → 再回来删这个空部门
    """

    # ---- 1. 先数这个部门还有多少人 ----
    # filter(depart_id=pk) 直接比外键列，不用先把部门对象查出来
    # count() 只回一个整数，代价可以忽略
    emp_count = models.Employee.objects.filter(depart_id=pk).count()

    # ---- 2. 还有人 → 打回列表页，说明原因 ----
    # 不能只靠列表页那个 confirm 弹窗兜底：confirm 挡不住误点，
    # 人员损失不可逆，必须在服务端拦
    # 用 query 参数把人数带回去，提示里能说清"还有 3 个人"这种具体信息
    if emp_count:
        return redirect(f"/department/list/?err=has_emp&n={emp_count}")

    # ---- 3. 空部门才真正删除 ----
    # filter(pk=pk).delete()：主键不存在也只影响 0 行，页面照常跳走
    # （QuerySet.delete() 不调用模型的 delete() 方法，别指望在这挂钩子）
    models.Department.objects.filter(pk=pk).delete()

    return redirect("/department/list/")
