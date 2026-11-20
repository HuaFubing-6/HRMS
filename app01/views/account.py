"""
认证模块（T4）
================

涉及四个函数：
    captcha        生成并返回图片验证码
    login_view     登录（用户名 + 密码 + 验证码）
    logout_view    注销
    switch_account / switch_to / switch_back   账号快速切换（答辩演示用）

答辩要点：密码从不明文落库。Django 的 User 模型自带 set_password/check_password，
底层是 PBKDF2 + SHA256 加盐迭代，登录时把输入的密码用同样算法算一遍比对。

答辩可讲点（这个文件通常是第一站）：
  1. _build_session —— 登录和切换账号共用同一段建会话逻辑，不复制两份
  2. login 为什么要显式指定 backend —— user 不是 authenticate() 返回的对象
  3. 验证码为什么绕不过 —— 答案只在 session 里，页面只有像素
  4. 密码为什么不能 filter(password=...) 直接查 —— 库里存的是哈希
  5. logout 之后还要 flush —— 连权限缓存一起销毁，并换发 session key
  6. 切换账号的三层安全限制 —— 仅超管可发起、switch_from 防提权、DEBUG 开关
"""
# settings：读 LOGIN_URL 和 ACCOUNT_SWITCH_ENABLED 开关
from django.conf import settings
# HttpResponseForbidden：直接返回 403，比 redirect 更明确地表达"你没权限"
from django.http import HttpResponseForbidden
# render 渲染登录页/切换页；redirect 返回 302 跳转
from django.shortcuts import render, redirect
# login / logout：Django 自带的会话建立与销毁，负责写 user_id、换 session key
from django.contrib.auth import login, logout

# generate_captcha：画图 + 把答案写进 session + 返回 PNG 响应，一步到位
from app01.utils.captcha import generate_captcha
# models：查用户、校验密码、切换账号时取角色
from app01 import models


def home(request):
    """
    根地址 "/" 的入口视图。

    为什么需要它：
      访问 http://127.0.0.1:8001/ 时，"/" 并不是一个业务路由，
      也不在权限表的 URL 里，所以旧版直接落到 RBAC 中间件第 5 段，
      已登录的非超管用户会看到"403 权限不足"。
      这里统一把它变成一个跳板：
        已登录  -> /index/
        未登录  -> /login/（再由中间件白名单放行）
    这样打开根地址永远有去处，不会卡在 403。
    """
    return redirect("/index/" if request.user.is_authenticated else "/login/")


def _build_session(request, user):
    """
    建立登录态（登录和切换账号共用的那段逻辑）。

    抽成函数的原因：
    login_view 和 switch_to 都要做同一件事 —— 写 user_id、缓存权限列表、记用户名。
    如果复制两份，以后改权限规则就得改两处，早晚会不一致。

    permissions 缓存在 session 里是"性能换实时性"：
    每个请求不再查库，代价是改完角色权限要重新登录才生效。
    """
    # 第三个参数 backend 不能省：user 不是 authenticate() 返回的对象，
    # 而是直接查库拿到的，Django 需要显式告诉它用哪个认证后端记这个会话。
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")

    permissions = []
    if user.role:
        permissions = list(user.role.permissions.values_list("url", flat=True))
    request.session["permissions"] = permissions
    request.session["username"] = user.username


def captcha(request):
    """
    返回一张 PNG 验证码图片。

    图片本身由 Pillow 现画（见 utils/captcha.py），
    同时会把答案（4 位字符）写进 session，登录时比对。
    前端 <img src="/captcha/" onclick="this.src='/captcha/?'+Math.random()">
    点击刷新靠加随机参数绕过浏览器缓存。
    """
    return generate_captcha(request)


def login_view(request):
    """
    登录视图，分 GET / POST 两个分支。

    GET：返回登录页。
    POST：按「验证码 → 账号密码 → 建立会话」三步顺序校验，任一步失败都回到登录页。
    """
    if request.method == "GET":
        return render(request, "app01/login.html")

    # ---- 取三个值，全部 strip ----
    # username/password：strip 掉首尾空格，避免复制粘贴时带进看不见的字符
    # （密码理论上是精确的，但用户手输常常带空格，这里按"净化"处理更宽容）
    # captcha：同样 strip，答案里本来就没有空格
    username = request.POST.get("username", "").strip()
    password = request.POST.get("password", "").strip()
    captcha_text = request.POST.get("captcha", "").strip()

    # ---- 第 1 步：验证码 ----
    # 答案存在 session 里（服务端），前端看不到，所以不能被绕过。
    # 忽略大小写，减少用户输入负担。
    session_captcha = request.session.get("captcha", "")
    if not captcha_text or captcha_text.lower() != session_captcha.lower():
        # 第 1 步失败：回到登录页，error 变量由模板渲染成红字提示
        # 注意这里重新 render 而不是 redirect：redirect 会丢掉 error 消息
        return render(request, "app01/login.html", {"error": "验证码错误"})

    # ---- 第 2 步：账号密码 ----
    # 注意这里不能用 filter(username=..., password=...) 直接查，
    # 因为库里存的是哈希密文，输入的明文永远对不上。
    # 正确做法是取出用户，再调 check_password() 让 Django 用哈希算法比对。
    user = models.User.objects.filter(username=username).first()
    if user is None or not user.check_password(password):
        # 账号不存在和密码错误给同一句提示，避免被人枚举出"哪些用户名存在"
        return render(request, "app01/login.html", {"error": "用户名或密码错误"})

    # ---- 第 3 步：建立会话 ----
    # ---- 第 3 步：建立会话 ----
    # 到这一步说明验证码对、账号密码也对，
    # 交给 _build_session 统一写 user_id + 权限快照 + 用户名
    _build_session(request, user)

    # 跳首页而不是留在登录页：登录成功后没有理由再回登录页
    return redirect("/index/")


def logout_view(request):
    """
    注销。

    logout() 清掉认证信息；session.flush() 把整个会话数据连同
    缓存的 permissions 一起销毁，并换发新的 session key，防止会话固定攻击。
    """
    # logout() 只清认证信息（request.user 变 AnonymousUser），session 里其他数据可能还在
    logout(request)
    # flush() 才是彻底清空：连 permissions 一起扔掉，并换发新的 session key，
    # 防止"旧 key 被复用"的会话固定攻击
    request.session.flush()
    return redirect("/login/")


# ==========================================================================
#  账号快速切换（答辩演示用）
# ==========================================================================
#  为什么需要这个功能？
#  答辩要演示"权限差异"：同一套页面，超管能看到 10 个菜单、普通员工只有 3 个，
#  敲同一个地址一个 200 一个 403。如果每次都退出、重新输账号密码和验证码，
#  一次演示要折腾两分钟，还容易在讲台上输错。
#
#  安全上做了三层限制（老师问起来这是加分点）：
#    1. 只有超级管理员能发起切换（普通员工根本打不开这个页面）；
#    2. 切出去之后，原管理员的 id 记在 session 的 switch_from 里，
#       只有带着这个标记的会话才能"切回管理员"——普通员工自己登录拿不到这个标记，
#       所以没法靠这个入口把自己提权成超管；
#    3. settings.ACCOUNT_SWITCH_ENABLED 只在 DEBUG 下为 True，
#       上线关掉 DEBUG，这个功能就整体失效。


def _switch_enabled():
    """总开关：没开就直接当这个功能不存在。"""
    return getattr(settings, "ACCOUNT_SWITCH_ENABLED", False)


def switch_account(request):
    """
    切换账号的列表页：把所有账号列出来，点一下换身份。

    只有超管能进。这里返回 403 而不是跳登录页，
    因为用户已经登录了、只是权限不够，跳登录会让人困惑。
    """
    # 二次校验：总开关没开（比如线上）→ 当这个功能不存在；不是超管 → 也进不来
    # 两个条件合成一句，任一不满足都直接 403
    if not _switch_enabled() or not request.user.is_superuser:
        return HttpResponseForbidden("403 权限不足")

    # select_related("role")：列表里要显示每个账号的角色名，
    # 不加就是 N+1；order_by("id") 让账号顺序固定，演示时好找
    user_list = models.User.objects.select_related("role").order_by("id")
    return render(request, "app01/account/switch.html", {"user_list": user_list})


def switch_to(request, pk):
    """
    切换到指定账号。

    关键顺序：先记下"我从谁切出来的"，再 logout（会 flush 掉整个 session），
    然后重新把 switch_from 写回去，最后建立新身份。
    如果先 logout 再读 request.user.pk，拿到的就是匿名人，标记就丢了。
    """
    if not _switch_enabled() or not request.user.is_superuser:
        return HttpResponseForbidden("403 权限不足")

    target = models.User.objects.filter(pk=pk).select_related("role").first()
    if target is None:
        return redirect("/account/switch/")

    # 已经是"切出来的"状态时，保留最初的管理员 id，避免 A→B→C 切换后回不去 A
    origin_id = request.session.get("switch_from") or request.user.pk

    logout(request)                       # 清掉旧身份和旧权限缓存
    request.session["switch_from"] = origin_id
    _build_session(request, target)

    # 演示提示：切到普通员工后，顶部菜单会自动收缩，不用额外处理
    return redirect("/index/")


def switch_back(request):
    """
    切回切换前的管理员。

    没有 switch_from 的会话一律拒绝 —— 这是防提权的关键一行：
    普通员工自己登录时 session 里没有这个键，所以走不通这条路。
    """
    origin_id = request.session.get("switch_from")
    if not _switch_enabled() or not origin_id:
        return HttpResponseForbidden("403 权限不足")

    origin = models.User.objects.filter(pk=origin_id).first()
    if origin is None or not origin.is_superuser:
        return HttpResponseForbidden("403 权限不足")

    logout(request)
    _build_session(request, origin)       # 回到管理员本尊，不再带 switch_from
    return redirect("/index/")
