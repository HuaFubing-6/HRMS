"""
RBAC 权限中间件（T5）
======================

这是整个权限体系的第一层，也是唯一"全局生效"的一层。

RBAC 三层联动（答辩重点）：
    第 1 层  中间件   —— 拦截所有请求，未登录跳登录，无权限返回 403（本文件）
    第 2 层  装饰器   —— 对单个视图做更细的权限控制（可选用）
    第 3 层  模板过滤器 —— 前端按权限隐藏按钮，避免"点了才报错"

为什么用中间件而不是每个视图都写 @login_required？
因为系统有 30 多个路由，逐个加装饰器既容易漏，也不利于新增页面。
中间件只写一次，新页面只要在权限表里配好 URL 就自动受控。

注册顺序（很容易踩的坑）：
    本类必须排在 SessionMiddleware 和 AuthenticationMiddleware 之后，
    因为它要用 request.session 和 request.user。
    排到前面的话 request.user 还不存在，请求一进来就 AttributeError。
    实际注册位置见 hrms/settings.py 的 MIDDLEWARE 列表。

答辩可讲点（这是全项目最该讲的文件）：
  1. 为什么用中间件而不是每个视图加装饰器 —— 30 多个路由，写一次全站生效，新增页面只要配条权限
  2. 注册顺序的坑 —— 必须排在 AuthenticationMiddleware 之后，否则 request.user 不存在直接 AttributeError
  3. 第 4 段的两步匹配 —— 先精确、再前缀；前缀匹配就是修掉"部门管理员点删除却 403"的那次改动
  4. 第 5 段为什么 403 不用 404 —— 地址存在、只是没权限，403 才符合 HTTP 语义
"""
from django.conf import settings
from django.shortcuts import redirect
from django.utils.deprecation import MiddlewareMixin

# 白名单：这些地址不登录也能访问，否则登录页自己都要登录，形成死循环
WHITE_LIST = [
    "/",           # 根地址：只是跳板（已登录去 /index/、未登录去 /login/），不参与权限比对
    "/login/",
    "/logout/",
    "/captcha/",   # 登录页要显示验证码图片，必须放行
]

# 登录后即可访问、不参与权限表比对的地址。
# 账号切换是"所有角色都可能需要走"的特殊入口：
# 切到普通员工后，他的权限里当然没有 /account/switch/back/，
# 如果走权限表就会被 403 卡住、再也切不回来。
# 所以这里放行，具体能不能切由视图自己判断（视图里有超管校验 + switch_from 标记校验）。
LOGIN_ONLY_PREFIXES = ["/account/switch/"]


class RbacMiddleware(MiddlewareMixin):
    """
    请求进入视图之前先过一遍权限检查。

    process_request 的返回值约定：
        返回 None        -> 继续走后续中间件和视图
        返回 HttpResponse -> 直接短路，后面的视图不再执行
    """

    def process_request(self, request):
        """
        权限检查主流程，顺序固定（后一步依赖前一步的结果）：
            1 白名单放行 → 2 未登录跳登录页 → 3 超管放行
            → 3.5 登录即可的特殊入口 → 4 按 session 权限表精确/前缀比对 → 5 返回 403
        返回 None 表示放行；返回 HttpResponse 表示短路，后面的视图不再执行。
        """
        path = request.path_info  # 当前请求路径，如 /employee/list/

        # ---- 1. 白名单放行 ----
        if path in WHITE_LIST:
            return None

        # ---- 2. 未登录拦截 ----
        # is_authenticated 由 AuthenticationMiddleware 根据 session 里的 user_id 得出
        if not request.user.is_authenticated:
            return redirect(settings.LOGIN_URL)   # 302 跳到 /login/

        # ---- 3. 超级管理员放行 ----
        # 超管不依赖 role.permissions，避免初始化数据没配全时把自己锁在门外
        if request.user.is_superuser:
            return None

        # ---- 3.5 登录即可访问的特殊入口 ----
        # 账号切换：切到普通员工后，他没有 /account/switch/back/ 这条权限，
        # 但必须能点"切回管理员"，否则就卡在员工身份里出不来了。
        # 能不能真正切换，由视图内部再判断（是否超管 / 是否带 switch_from 标记）。
        if any(path.startswith(p) for p in LOGIN_ONLY_PREFIXES):
            return None

        # ---- 4. 普通用户按权限表校验（每次都实时读库）----
        # 为什么不用 session 里的权限快照：
        # 快照是"登录那一刻"拍的照。后台把角色权限改了之后，
        # 已登录用户手里拿的还是旧列表，现场就会出现
        # "权限明明改了，页面还是 403 / 或者还能进"，
        # 让人以为"角色管理里改权限是摆设"。
        # 改成每个请求查一次数据库（1 条 M2M 查询，课设规模可以忽略），改完立刻生效。
        # 万一角色被删成 None，兜底成空列表，不会 AttributeError。
        permissions = (
            list(request.user.role.permissions.values_list("url", flat=True))
            if request.user.role
            else []
        )

        # 4.1 精确匹配：/employee/list/ 这种固定地址直接比
        if path in permissions:
            return None

        # 4.2 前缀匹配：解决带主键的动态地址
        # 权限表里存的是 /department/delete/，但真实请求是 /department/delete/3/，
        # 主键不同，精确比对永远对不上（这正是"部门管理员点删除却 403"的原因）。
        # 所以再按前缀过一遍：/department/delete/3/ 以 /department/delete/ 开头，就算有权限。
        # 前提是权限记录本身以 "/" 结尾，避免 /chart 这种半截规则误伤。
        for perm in permissions:
            if perm.endswith("/") and path.startswith(perm):
                return None

        # ---- 5. 有登录但无权限 ----
        # 返回 403 而不是跳登录页：用户已经登录了，再让他登录一次会让人困惑。
        # 也不返回 404：404 会让人以为"这个地址不存在"，
        # 而 403 明确表达"地址存在、只是你没权限"，既符合 HTTP 语义也便于排查。
        from django.http import HttpResponseForbidden

        return HttpResponseForbidden("403 权限不足")
