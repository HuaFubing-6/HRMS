"""
分页工具
==========

为什么自己写而不是用 Django 的 Paginator？
因为要控制页码条的外观（上一页 / 数字 / 下一页 / 尾页 + 跳转），
并且要把当前的搜索条件拼回 URL —— 否则翻页会把筛选条件丢掉。

用法（所有列表页统一）：
    page = Pagination(request, queryset, per_page=10)
    page.queryset           # 当前页的 10 条数据，直接丢给模板循环
    page.page_html()        # 分页条 HTML（方法调用，模板里仍是 {{ page_html }}）

答辩可讲点（所有列表页共用，T11 的"公共组件"）：
  1. 为什么自己写 —— 要控制页码条外观（上一页/尾页/跳转），还要把搜索条件带过页
  2. 页码容错 —— ?page=abc、?page=999 都兜成合法值，不抛异常
  3. 窗口算法 —— 20 页时只显示 11 个数字，当前页居中，不会把页码铺满屏
  4. 翻页保留条件 —— 复制 GET 再删掉 page，保证"搜了张再翻页还是张的结果"
"""
import math

from django.utils.safestring import mark_safe


class Pagination:
    """
    分页器：new 一个实例，取 queryset 和 page_html() 两样东西就够用。

    做成类而不是函数的原因：一次分页要同时产出「当前页数据」和「页码条 HTML」，
    两者依赖同一份计算结果（总数、总页数、当前页），用类只算一次，不会各算各的。
    """

    def __init__(self, request, queryset, per_page=10, max_show=11):
        """
        :param request: 用来取 ?page= 和保留其它查询参数
        :param queryset: Django QuerySet（必须是 QuerySet，list 没有 .count()）
        :param per_page: 每页条数
        :param max_show: 页码条最多显示几个数字，取奇数，当前页居中
        """
        self.request = request
        self.per_page = per_page
        self.max_show = max_show

        # ---- 当前页：容错处理 ----
        # 用户可能在地址栏手输 ?page=abc 或 ?page=999，
        # 这里把非法值兜底成 1，避免 int() 抛异常或切片越界。
        try:
            self.current_page = int(request.GET.get("page", 1))
        except (TypeError, ValueError):
            self.current_page = 1

        # ---- 总条数 / 总页数 ----
        self.total_count = queryset.count()
        # 向上取整；至少 1 页，否则空数据时会出现 0 页的尴尬
        self.total_page = math.ceil(self.total_count / self.per_page) or 1

        # 页码再夹紧到 [1, total_page]
        if self.current_page < 1:
            self.current_page = 1
        if self.current_page > self.total_page:
            self.current_page = self.total_page

        # ---- 切片取当前页数据 ----
        # QuerySet 惰性求值：这里是 LIMIT/OFFSET 分页，不是把所有数据捞到内存再切
        self.start = (self.current_page - 1) * self.per_page
        self.end = self.current_page * self.per_page
        self.queryset = queryset[self.start : self.end]

    @property
    def current_queryset(self):
        """当前页数据（老名字，保持向后兼容）。"""
        return self.queryset

    def page_html(self):
        """
        生成 Bootstrap 3 风格的分页条 HTML。

        为什么是方法而不是 property？
        —— 和教学脚手架的 Pagination 写法一致（page.page_html()），
           一眼就知道"这里要拼 HTML、有开销"；property 容易被误当成一个普通属性，
           在模板里 {{ page_html }} 也会隐式调用，两种写法混用反而不好排查。
        """
        # ---- 计算页码窗口 ----
        # 例如总共 20 页、最多显示 11 个，当前第 10 页时显示 5~15，
        # 而不是把所有 20 个页码全铺出来。
        half = self.max_show // 2
        if self.total_page <= self.max_show:
            start_page, end_page = 1, self.total_page
        else:
            if self.current_page <= half:
                # 当前页靠前：从头显示
                start_page, end_page = 1, self.max_show
            elif self.current_page + half >= self.total_page:
                # 当前页靠后：贴到尾页
                start_page = self.total_page - self.max_show + 1
                end_page = self.total_page
            else:
                # 当前页在中间：两边各留 half 个
                start_page = self.current_page - half
                end_page = self.current_page + half

        # ---- 保留搜索/筛选参数 ----
        # 先复制 GET 参数，再删掉 page，剩下的拼回去。
        # 这一步保证"搜了'张'再翻页，第 2 页依然是'张'的结果"。
        query_params = self.request.GET.copy()
        query_params.pop("page", None)
        base_url = "?" + query_params.urlencode() + "&page=" if query_params else "?page="
        # 拼进 HTML 属性时 & 要转义成 &amp;，否则会被解析成实体
        safe_base = base_url.replace("&", "&amp;")

        link_list = []

        # 上一页：已经在第 1 页时就指向自己，不会出现负数页码
        prev = self.current_page - 1 if self.current_page > 1 else 1
        link_list.append(f'<li><a href="{base_url}{prev}">上一页</a></li>')

        # 数字页码，当前页加 active 高亮
        for p in range(start_page, end_page + 1):
            active = ' class="active"' if p == self.current_page else ""
            link_list.append(f'<li{active}><a href="{base_url}{p}">{p}</a></li>')

        # 下一页
        nxt = self.current_page + 1 if self.current_page < self.total_page else self.total_page
        link_list.append(f'<li><a href="{base_url}{nxt}">下一页</a></li>')

        # 尾页：直接跳到最后一页
        link_list.append(f'<li><a href="{base_url}{self.total_page}">尾页</a></li>')

        # ---- 页码输入 + 跳转 ----
        # 用 JS 拼 URL，而不是提交表单，避免在 GET 请求里嵌套 form
        jump_html = (
            '<span class="page-jump">'
            '页码 <input id="pageJumpInput" type="number" class="form-control input-sm" '
            f'min="1" max="{self.total_page}" value="{self.current_page}" '
            'style="width:64px;display:inline-block;vertical-align:middle;"> '
            f'<button type="button" class="btn btn-default btn-sm" '
            f"onclick=\"location.href='{safe_base}'+document.getElementById('pageJumpInput').value\">"
            "跳转</button></span>"
        )

        # mark_safe：告诉模板这段 HTML 已经是安全的，不要转义尖括号，
        # 否则浏览器会把 <ul> 原样显示成文本。
        return mark_safe(
            '<ul class="pagination" style="margin:0;vertical-align:middle;">'
            + "".join(link_list)
            + "</ul> " + jump_html
        )
