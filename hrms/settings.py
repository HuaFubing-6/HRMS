"""
Django 项目配置（T1）
======================

答辩时按「技术规范表」逐项对照这个文件讲，是最省事的路线：
    后端框架  Django 5.2          -> 看 requirements.txt
    数据库    MySQL                -> DATABASES
    中文      zh-hans              -> LANGUAGE_CODE
    自定义用户 AUTH_USER_MODEL      -> AUTH_USER_MODEL
    权限      中间件                -> MIDDLEWARE
"""
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# ------------------------------------------------------------------
# 大模型配置的加载来源：项目根目录的 .env 文件
#   为什么用 .env：
#     1. Key 不写进代码，避免提交 Git 后泄露（任务书硬性要求）；
#     2. 又不用去改系统环境变量，克隆项目后放一个 .env 就能跑。
#   .env 已在 .gitignore 里，仓库里只提交 .env.example（占位值）。
#   load_dotenv 默认不覆盖已有环境变量：服务器上真实配置的环境变量优先。
# ------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv(BASE_DIR / ".env")
except ImportError:      # 没装 python-dotenv 时安静跳过，只认系统环境变量
    pass


# ------------------------------------------------------------------
# 密钥：Django 用它给 session、CSRF token 等做签名
#
# 这是本项目启动时踩过的坑：漏写这一项不是某个页面报错，
# 而是【每个请求都返回 500】，而且 DEBUG 错误页自己也会抛
# "The SECRET_KEY setting must not be empty"，看起来像代码问题。
# 所以遇到全站 500，第一反应应该先检查 SECRET_KEY 是否存在。
#
# 生产环境应从环境变量读取，绝不能把真实密钥提交到公开仓库。
# ------------------------------------------------------------------
SECRET_KEY = "django-insecure-hrms-2026-y7k3n9p2t5v8x1c4b6m0wqzaejlgfdhs"

# ------------------------------------------------------------------
# 安全配置（T13：上线前要改）
#   DEBUG=True  开发时显示详细报错页，生产必须关掉，否则会泄漏代码路径与配置
#   ALLOWED_HOSTS  生产要写具体域名，["*"] 表示接受任意 Host（便于演示）
# ------------------------------------------------------------------
DEBUG = True
ALLOWED_HOSTS = ["*"]

# ------------------------------------------------------------------
# 账号快速切换（答辩演示用的辅助功能）
#   演示权限差异时要来回切"超管"和"普通员工"，
#   每次退出再输账号密码和验证码太费时间，所以做了个切换入口。
#
#   这里绑在 DEBUG 上：上线时 DEBUG 一关，功能整体失效，
#   不用再单独去改代码，减少"忘记关演示开关"的风险。
# ------------------------------------------------------------------
ACCOUNT_SWITCH_ENABLED = DEBUG

# ------------------------------------------------------------------
# 应用注册
# 顺序不重要（除 admin 依赖 auth/contenttypes），但 app01 必须在最后，
# 便于它覆盖 admin 的模板。
# ------------------------------------------------------------------
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "app01",  # 业务应用
]

# ------------------------------------------------------------------
# 中间件：请求自外向内，响应自内向外
#   最后一条 RbacMiddleware 是自建的权限检查，
#   它放在 AuthenticationMiddleware 之后很关键——
#   因为要先由 AuthenticationMiddleware 把 request.user 解析出来，
#   我们的中间件才能判断 is_authenticated。
# ------------------------------------------------------------------
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",              # 表单里的 {% csrf_token %} 靠它校验
    "django.contrib.auth.middleware.AuthenticationMiddleware",  # 提供 request.user
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    # RBAC 权限中间件：校验当前登录用户是否有权访问目标 URL
    "app01.middleware.rbac.RbacMiddleware",
]

ROOT_URLCONF = "hrms.urls"

# ------------------------------------------------------------------
# 模板配置
#   模板不在项目根，而是放在 app01/templates/app01/ 下
#   靠 APP_DIRS=True 自动查找，所以模板名要带 "app01/" 前缀
# ------------------------------------------------------------------
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        # 模板放在 app01/templates/app01/ 下，不再用项目根的 templates 目录。
        # DIRS 留空 + APP_DIRS=True，Django 会自动去每个 app 的 templates/ 里找，
        # 所以模板名要写成 "app01/xxx.html"。
        # 好处：app01 可以整包复制到别的项目，模板跟着走，不用改项目配置。
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.debug",
                "django.template.context_processors.request",   # 模板里能直接用 request
                "django.contrib.auth.context_processors.auth",  # 模板里能直接用 user
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

WSGI_APPLICATION = "hrms.wsgi.application"

# ------------------------------------------------------------------
# 数据库（MySQL）
#
# 建库 SQL：CREATE DATABASE hrms DEFAULT CHARSET utf8mb4;
# charset 用 utf8mb4 而不是 utf8：utf8 存不了 emoji 和部分生僻字。
#
# 驱动说明：本机没装 mysqlclient（Windows 编译容易失败），
# 改用 PyMySQL，并在 hrms/__init__.py 里执行 install_as_MySQLdb()，
# 所以 ENGINE 仍然写 mysql，Django 感知不到差别。
# ------------------------------------------------------------------
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.mysql",
        "NAME": "qiyerenwu",     # 数据库名（本机单独建库，避免与 HRMS 项目共用 hrms 库撞表）
        "USER": "root",          # MySQL 用户名
        "PASSWORD": "123456",    # MySQL 密码
        "HOST": "127.0.0.1",
        "PORT": "3306",
        "OPTIONS": {"charset": "utf8mb4"},
    }
}

# ------------------------------------------------------------------
# 认证：自定义用户模型（T1 + T5）
# 必须在第一次 migrate 之前就写好，否则 Django 会把默认 auth_user 建出来，
# 之后再改会非常麻烦（要清库重来）。
# ------------------------------------------------------------------
AUTH_USER_MODEL = "app01.User"

# 密码强度校验器：只在通过表单改密码时生效，
# 用 create_user/make_password 写库时不会触发，
# 所以演示账号可以用简单的 123。
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# ------------------------------------------------------------------
# 国际化与时区
#   LANGUAGE_CODE=zh-hans：后台与表单提示都是中文
#   USE_TZ=False：考勤/薪资都是"本地日期"，关掉时区避免差 8 小时
# ------------------------------------------------------------------
LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = False

# ------------------------------------------------------------------
# 静态文件 / 媒体文件
#   STATIC：CSS/JS/图片等随代码发布的资源（本项目走 CDN，本地目录留空）
#   MEDIA ：用户上传的文件（员工头像），存磁盘，数据库只存相对路径
# ------------------------------------------------------------------
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
MEDIA_URL = "/media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# 未登录访问受保护页面时，中间件跳转到这个地址
LOGIN_URL = "/login/"

# 会话有效期：8 小时，下班后自动失效
SESSION_COOKIE_AGE = 8 * 60 * 60

# ------------------------------------------------------------------
# 大模型（AI 智能员工助手）
#   任务书 2.2：API_KEY / BASE_URL / MODEL 一律放环境变量，禁止硬编码。
#   这里只做"读取 + 默认值"，真实值来自 .env 或系统环境变量。
#
#   AI_TIMEOUT      单次调用超时（秒），超时给中文提示，不让页面卡住
#   AI_MAX_INPUT    单次输入字数上限（T6 输入过滤）
#   AI_MIN_INTERVAL 同一会话两次调用最小间隔（秒），防连点（T6 限流）
#   AI_DAILY_LIMIT  同一会话每天最多调用次数（免费额度保护）
# ------------------------------------------------------------------
import os

AI_API_KEY = os.environ.get("AI_API_KEY", "")
AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://api.siliconflow.cn/v1")
AI_MODEL = os.environ.get("AI_MODEL", "Qwen/Qwen2.5-7B-Instruct")

AI_TIMEOUT = 20
AI_MAX_INPUT = 500
AI_MIN_INTERVAL = 3
AI_DAILY_LIMIT = 50

# 离线兜底开关：答辩现场断网时置 True，AI 功能返回预置文本而不是整页报错。
# 默认 False，正常都走真实模型。
AI_OFFLINE_DEMO = os.environ.get("AI_OFFLINE_DEMO", "0") == "1"
