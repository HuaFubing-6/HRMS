"""
自定义模板过滤器（T5 的第三层：前端按权限隐藏按钮）
=====================================================

为什么要做这一层？
中间件能拦住"直接输 URL"的人，但拦不住"按钮还显示着"这件事——
普通员工点进去才收到 403，体验很差。
所以模板里用 has_perm 判断，没权限的按钮直接不渲染。

用法（先 {% load filters %}）：
    {% if request|has_perm:"/employee/add/" %}
        <a href="/employee/add/" class="btn btn-success">新增员工</a>
    {% endif %}

答辩可讲点（RBAC 的第三层）：
  1. 中间件负责"拦住"，过滤器负责"看不见" —— 两层配合，普通员工不会看到点了才报错的按钮
  2. 超管直接返回 True —— 不依赖权限表，即使初始化没配全也不会看到空界面
  3. 这里是精确包含 —— 宁可少显示一个按钮，安全由中间件的"精确 + 前缀"兜住
"""
from django import template

register = template.Library()


@register.filter
def has_perm(request, url_name):
    """
    判断当前用户是否拥有某个 URL 权限。

    超管直接 True，不走权限表——
    这样即使初始化命令没配全权限，管理员也不会看到"空界面"。
    普通用户则比对登录时缓存在 session 里的权限列表。
    """
    if request.user.is_superuser:
        return True

    # ---- 实时查库，和 middleware/rbac.py 保持同一口径 ----
    # 原来是读 request.session["permissions"]（登录时写进去的快照），
    # 结果是：后台改完角色权限，菜单要重新登录才更新，
    # 而中间件已经是实时的 —— 于是出现"菜单里看不到、直接敲 URL 却能进"的错位。
    # 查到的结果缓存在 request 上：一个页面有 10 个菜单项，
    # 不缓存的话同一个请求会重复发 10 条一模一样的 SQL。
    cache = getattr(request, "_perm_cache", None)
    if cache is None:
        role = getattr(request.user, "role", None)
        cache = set(role.permissions.values_list("url", flat=True)) if role else set()
        request._perm_cache = cache

    # 精确包含：宁可少显示一个按钮，也不多显示一个点进去才报 403 的按钮。
    # 带主键的地址（如 /department/delete/3/）在这一层匹配不到，按钮会不显示，
    # 但这不影响安全 —— 真正拦住请求的是中间件里的"精确 + 前缀"两道匹配。
    return url_name in cache
