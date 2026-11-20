"""
公告管理（T8）
================

四个视图：列表（搜索 + 排序 + 分页）、发布、删除、置顶切换。

答辩重点：
1. 排序是"置顶优先、时间倒序"，一条 order_by 就能做到，不需要两条查询；
2. 发布人取自登录用户，不允许前端提交；
3. 发布时间用 auto_now_add，由数据库写入。

答辩可讲点：
  1. 排序一条 order_by 搞定 —— "-is_top" 布尔降序 + "-create_time" 时间倒序，不用两次查询
  2. 一页 5 条 —— per_page=5，对齐参考截图
  3. commit=False —— 发布人不在表单里，先拿到对象补 user 再 save（任务书 4.2 节点要求）
  4. 置顶做成"切换" —— 一个按钮来回切，后端只有一处逻辑
"""
from django.db.models import Q
from django.shortcuts import render, redirect

from app01 import models, forms
from app01.utils.pagination import Pagination
# 判断是不是部门管理员：决定他发的公告要不要绑定部门
from app01.utils.scope import is_dept_admin


def notice_list(request):
    """
    公告列表：支持标题模糊搜索，置顶排最前，其次按发布时间倒序。
    """
    # ---- 1. 取搜索词 ----
    # 只按标题搜，不去正文里找：正文内容太长，模糊匹配没意义，也慢
    # strip() 去掉首尾空格，避免" 通知 "搜不出"通知"
    search_title = request.GET.get("title", "").strip()

    # ---- 2. 基础查询 + 条件 ----
    # all() 是惰性 QuerySet，此刻不发 SQL
    queryset = models.Notice.objects.all()

    # ---- 可见范围（先过滤再排序）----
    # 超管跳过这整段 → 看到全部，这就是"超管能看见所有公告"。
    # 其他人：全公司公告（depart 为空）+ 本部门的公告。
    # 顺序很重要：过滤放在排序前面，否则会先给全表排序再砍掉一半，白算一次
    if not request.user.is_superuser:
        # 部门管理员身上直接有 depart；普通员工没有，得顺着员工档案取部门
        dept_id = request.user.depart_id
        if not dept_id and request.user.employee_id:
            dept_id = request.user.employee.depart_id

        if dept_id:
            # Q(...) | Q(...)：两个条件取"或"，不能用逗号（逗号是"且"，永远查不到）
            queryset = queryset.filter(
                Q(depart__isnull=True) | Q(depart_id=dept_id)
            )
        else:
            # 既不是部门管理员、又没绑员工档案：只看全公司公告，部门公告一律不露出
            queryset = queryset.filter(depart__isnull=True)

    if search_title:
        # icontains = 包含 + 忽略大小写 → SQL 的 LIKE '%通知%'
        queryset = queryset.filter(title__icontains=search_title)

    # ---- 3. 排序技巧（一条 SQL 搞定"置顶优先 + 时间倒序"）----
    # "-is_top" 表示布尔字段降序：True(1) 排在前面，False(0) 在后面；
    # 再按 "-create_time" 让新公告在上。
    # 这样"置顶"只是排序规则，不需要拆两张表、也不需要在 Python 里分两批查。
    # 注意多个排序字段是"依次比较"：先按置顶，置顶状态相同的再按时间
    queryset = queryset.order_by("-is_top", "-create_time")

    # ---- 4. 分页 ----
    # 参考截图里一页显示 5 条，所以 per_page=5（其他列表页是 10）
    page = Pagination(request, queryset, per_page=5)

    # 回传 search_title 是为了把搜索框里上次的词填回去，
    # 不然翻页之后输入框会变空，用户以为条件丢了
    return render(
        request,
        "app01/notice/list.html",
        {
            "data_list": page.current_queryset,
            "page_html": page.page_html(),
            "search_title": search_title,   # 回填搜索框
        },
    )


def notice_add(request):
    """
    发布公告。

    commit=False 的用途：
    form.save() 默认会把所有字段一次性写库，但 user 字段不在表单里（表单只有标题/内容/置顶），
    直接 save 会因为 user 为空而报错。
    先 commit=False 拿到对象、补上 user，再 save 才完整。
    这是任务书 4.2 阶段四点名要练的写法。
    """
    # ---- GET：空表单 ----
    # NoticeForm 只包含 标题 / 内容 / 置顶 三个字段，
    # 发布人和发布时间都不在表单里（见下面的 POST 分支）
    if request.method == "GET":
        form = forms.NoticeForm()
        return render(request, "app01/notice/form.html", {"form": form})

    # ---- POST：先校验，再补字段，最后落库 ----
    form = forms.NoticeForm(data=request.POST)

    if form.is_valid():
        # commit=False = "先别写库，把对象给我，我还要补字段"
        # 因为表单里没有 user，直接 save() 会因 user 为空而报 IntegrityError
        obj = form.save(commit=False)

        # 发布人取当前登录用户，不从表单取 —— 前端改不了，也就伪造不了发布人
        # request.user 来自 AuthenticationMiddleware，中间件已保证它是登录态
        obj.user = request.user

        # ---- 部门归属 ----
        # 部门管理员发的公告绑定自己部门，只有本部门的人（和超管）看得到；
        # 超管发的是全公司公告，depart 留空，人人可见。
        # 这一行同样不让前端传：否则部门管理员可以随手改成别的部门，跨部门发通知
        if is_dept_admin(request.user):
            obj.depart = request.user.depart
        else:
            obj.depart = None

        # 补齐之后，这一句才真正 INSERT
        # create_time 由 auto_now_add 在写入时自动填，同样不用管
        obj.save()

        return redirect("/notice/list/")

    # 校验失败：form 带 errors 回去，已填的标题和正文都保留
    return render(request, "app01/notice/form.html", {"form": form})


def notice_delete(request, pk):
    """删除公告。"""
    # 只发一条 DELETE，主键不存在也不抛异常；
    # 公告是链尾表（没有别的表引用它），删一条不会连带删数据
    models.Notice.objects.filter(pk=pk).delete()
    return redirect("/notice/list/")


def notice_top(request, pk):
    """
    切换置顶状态（置顶 ↔ 取消置顶）。

    做成"切换"而不是"置顶/取消"两个接口：
    一个按钮就能来回切，前端只改按钮文字，后端逻辑只有一处。
    """
    # 先取对象（这里必须拿到对象，因为要读它当前的 is_top 再取反）
    obj = models.Notice.objects.filter(pk=pk).first()

    # obj 可能是 None（手改 URL 到不存在的主键），所以先判空：
    # 不判的话 obj.is_top 会抛 AttributeError → 500
    if obj:
        # not obj.is_top：True 变 False、False 变 True，一个字段搞定两个方向
        obj.is_top = not obj.is_top
        # save() 只更新这一条，不用写 UPDATE ... SET is_top = ...
        obj.save()

    # 无论切换成功还是对象不存在，都回列表页 —— 不做提示，
    # 因为列表里的置顶标记本身就变了，用户能直接看到结果
    return redirect("/notice/list/")
