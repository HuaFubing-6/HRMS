"""
初始化命令：python manage.py init_data
========================================

为什么要写这个命令？
因为权限表、角色、超管账号都是"环境相关"的数据。
每换一台电脑就要重新点一遍后台太麻烦，写成命令后一条就搞定，
也保证所有人的权限配置完全一致（任务书 4.2 阶段一的要求）。

可重复执行：全部用 get_or_create，跑几遍都不会重复插入。
"""
from django.core.management.base import BaseCommand

from app01 import models

# 全部业务权限：url 必须和 app01/urls.py 里写的 path 一模一样，
# 少一个斜杠都会导致该页面永远 403，这是最常见的配置错误。
ALL_PERMS = [
    ("首页", "/index/"),
    ("部门列表", "/department/list/"),
    ("部门新增", "/department/add/"),
    ("部门编辑", "/department/edit/"),
    ("部门删除", "/department/delete/"),
    ("员工列表", "/employee/list/"),
    ("员工新增", "/employee/add/"),
    ("员工编辑", "/employee/edit/"),
    ("员工删除", "/employee/delete/"),
    ("考勤列表", "/attendance/list/"),
    ("考勤新增", "/attendance/add/"),
    ("考勤删除", "/attendance/delete/"),
    ("薪资列表", "/salary/list/"),
    ("薪资录入", "/salary/add/"),
    ("薪资删除", "/salary/delete/"),
    ("公告列表", "/notice/list/"),
    ("公告发布", "/notice/add/"),
    ("公告删除", "/notice/delete/"),
    ("公告置顶", "/notice/top/"),
    ("任务列表", "/task/list/"),
    ("任务AJAX新增", "/task/add/"),
    ("任务编辑", "/task/edit/"),
    ("任务删除", "/task/delete/"),
    ("用户列表", "/user/list/"),
    ("用户新增", "/user/add/"),
    ("用户删除", "/user/delete/"),
    ("角色列表", "/role/list/"),
    ("角色新增", "/role/add/"),
    ("角色编辑", "/role/edit/"),
    ("角色删除", "/role/delete/"),
    ("图表页", "/chart/"),
    ("部门饼图数据", "/chart/dept/pie/"),
    ("薪资趋势数据", "/chart/salary/trend/"),

    # ---- AI 智能助手（大模型）----
    # 页面和接口都要单独登记：中间件是按"请求路径"比对的，
    # 页面有权限但接口没登记，会出现"页面进得去、点按钮却 403"。
    ("招聘JD页", "/ai/jd/"),
    ("招聘JD生成", "/ai/jd/generate/"),
    ("制度问答页", "/ai/qa/"),
    ("制度问答接口", "/ai/qa/ask/"),
    ("数据点评页", "/ai/comment/"),
    ("数据点评接口", "/ai/comment/generate/"),
    ("对话助手页", "/ai/chat/"),
    ("对话接口", "/ai/chat/ask/"),
    ("对话清空", "/ai/chat/clear/"),
    ("流式对话", "/ai/chat/stream/"),
]


class Command(BaseCommand):
    """
    一次性建好权限表、三个角色和超级管理员账号。

    可重复执行：所有写入都走 get_or_create，已存在就复用，不会重复插入。
    所以答辩前数据乱了、或换台机器部署，直接再跑一遍就能恢复成可用状态。
    """

    help = "初始化角色、权限与超级管理员账号"

    def add_arguments(self, parser):
        """三个可选参数：账号名、密码，以及 --reset（账号已存在时重置密码）。"""
        # 支持自定义账号密码，不写死，方便换人或改密码
        parser.add_argument("--username", default="盖亚", help="超级管理员用户名，默认 盖亚")
        parser.add_argument("--password", default="123", help="超级管理员密码，默认 123")
        parser.add_argument("--reset", action="store_true", help="账号已存在时重置密码")

    def handle(self, *args, **options):
        """
        四步：建权限 → 建角色 → 把权限分给角色 → 建超管账号。
        顺序不能反：角色要挂权限，账号要挂角色。
        """
        # ---- 1. 权限 ----
        # get_or_create(url=..., defaults={"title": ...})：
        # 以 url 作为唯一依据，已存在就复用，不重复插入
        perm_objs = []
        for title, url in ALL_PERMS:
            obj, _ = models.Permission.objects.get_or_create(url=url, defaults={"title": title})
            perm_objs.append(obj)
        self.stdout.write(self.style.SUCCESS(f"权限就绪：{len(perm_objs)} 条"))

        # ---- 2. 角色 ----
        super_role, _ = models.Role.objects.get_or_create(title="超级管理员")
        dept_role, _ = models.Role.objects.get_or_create(title="部门管理员")
        emp_role, _ = models.Role.objects.get_or_create(title="普通员工")

        # ---- 3. 角色 ↔ 权限（RBAC 的核心映射）----
        # 超级管理员：配全所有权限。
        # 中间件里它其实是靠 is_superuser 直接放行的，不依赖这份列表；
        # 但角色列表页会显示"权限数"，配成 0 看起来像漏配了，所以照样给全。
        super_role.permissions.set(perm_objs)

        # 部门管理员：能管业务（部门/员工/考勤/薪资/公告/任务/图表），
        # 但不能碰用户和角色——这是"最小权限"原则。
        dept_urls = {
            "/index/", "/department/list/", "/department/add/", "/department/edit/", "/department/delete/",
            "/employee/list/", "/employee/add/", "/employee/edit/", "/employee/delete/",
            "/attendance/list/", "/attendance/add/", "/attendance/delete/",
            "/salary/list/", "/salary/add/", "/salary/delete/",
            "/notice/list/", "/notice/add/", "/notice/delete/", "/notice/top/",
            "/task/list/", "/task/add/", "/task/edit/", "/task/delete/",
            "/chart/", "/chart/dept/pie/", "/chart/salary/trend/",
            # AI：部门管理员可以用全部 AI 功能（点评限本部门，在视图里过滤数据范围）
            "/ai/jd/", "/ai/jd/generate/", "/ai/qa/", "/ai/qa/ask/",
            "/ai/comment/", "/ai/comment/generate/",
            "/ai/chat/", "/ai/chat/ask/", "/ai/chat/clear/", "/ai/chat/stream/",
        }
        dept_role.permissions.set([p for p in perm_objs if p.url in dept_urls])

        # 普通员工：只读——首页、公告、图表，看不到任何增删改入口
        # AI 只开放"制度问答"和"对话助手"；JD、数据点评属于 HR 工作，不给
        emp_urls = {
            "/index/", "/notice/list/", "/chart/", "/chart/dept/pie/", "/chart/salary/trend/",
            "/ai/qa/", "/ai/qa/ask/",
            "/ai/chat/", "/ai/chat/ask/", "/ai/chat/clear/", "/ai/chat/stream/",
        }
        emp_role.permissions.set([p for p in perm_objs if p.url in emp_urls])

        # ---- 4. 超级管理员账号 ----
        username = options["username"]
        password = options["password"]
        user = models.User.objects.filter(username=username).first()

        if user is None:
            # create_user 内部会调 set_password，密码自动变成哈希，不是明文
            models.User.objects.create_user(
                username=username,
                password=password,
                is_superuser=True,
                is_staff=True,
                role=super_role,
            )
            self.stdout.write(self.style.SUCCESS(f"超级管理员账号已创建：{username} / {password}"))
        elif options["reset"]:
            # 账号已存在时按需重置，避免"跑完命令却登不进去"
            user.set_password(password)
            user.is_superuser = True
            user.is_staff = True
            user.role = super_role
            user.save()
            self.stdout.write(self.style.SUCCESS(f"账号已存在，密码已重置：{username} / {password}"))
        else:
            # 默认不覆盖已有密码，防止误把别人改过的密码重置掉
            self.stdout.write(f"账号 {username} 已存在，保留原密码（如需重置请加 --reset）")

        self.stdout.write(self.style.SUCCESS("初始化完成"))
