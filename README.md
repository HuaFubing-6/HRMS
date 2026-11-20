# 企业员工管理系统（HRMS）

基于 **Django 5.2 + MySQL + Bootstrap 3.4.1 + jQuery 3.6.0 + ECharts** 的课程设计项目。

## 一、功能清单

| 模块 | 功能 |
|------|------|
| 认证 | 登录（图片验证码）/ 注销 / 密码哈希存储 |
| RBAC | 用户-角色-权限、中间件接口拦截、前端按钮显隐 |
| 部门 | 增删改查 + 分页 |
| 员工 | CRUD + ModelForm 校验（年龄/手机号正则+唯一）+ 姓名模糊搜索 + 部门筛选 + 分页 + 头像上传 |
| 考勤 | CRUD + 上下班时间自动判定（按时/迟到/早退/缺勤） |
| 薪资 | 录入 + 实发自动计算（基本+奖金-扣款）+ 月份/员工筛选 + 月度总额统计 |
| 公告 | 发布 + 列表 + 置顶 + 标题搜索 + 分页 |
| 任务 | AJAX 异步提交 + JSON 返回 + 错误不刷新页面回显 |
| 可视化 | ECharts 部门人数饼图 + 各月薪资趋势折线（AJAX 取数） |
| 性能 | `select_related` 消除列表页 N+1 |

## 二、运行步骤

### 1. 准备 MySQL
先在 MySQL 中建库：
```sql
CREATE DATABASE hrms DEFAULT CHARSET utf8mb4;
```
打开 `hrms/settings.py`，把 `DATABASES` 里的 `USER` / `PASSWORD` 改成你本机的 MySQL 账号密码（本机已配置为 `root / 123456`）。

### 2. 安装依赖
```bash
cd D:\MIN\qiyerenwu\hrms
pip install -r requirements.txt
```
本项目用纯 Python 的 **PyMySQL** 作为 MySQL 驱动（已在 `hrms/__init__.py` 中注册），无需编译 `mysqlclient`。

### 3. 迁移 + 初始化
```bash
python manage.py makemigrations
python manage.py migrate
python manage.py init_data     # 建角色/权限/管理员账号
python manage.py demo_data    # 造演示数据（6部门/18员工/54薪资/5公告）
```

### 4. 启动
```bash
python manage.py runserver
```
浏览器访问 <http://127.0.0.1:8000/login/>

> 本机已完整跑通：迁移 19 张表、初始化 29 项权限、登录与各业务页面均返回 200。
> 服务启动命令：`python manage.py runserver 127.0.0.1:8000`

## 三、默认账号

| 账号 | 密码 | 角色 |
|------|------|------|
| 盖亚 | 123 | 超级管理员（全部权限） |

> 若账号已存在需重置密码：`python manage.py init_data --reset`
> 也可自定义：`python manage.py init_data --username 你的名字 --password 你的密码 --reset`

> 部门管理员 / 普通员工账号可在「用户管理」里新建并分配角色。

## 四、目录结构

> 按《EMS 项目构建思路与脚手架模板》对齐：视图按业务拆包、公共能力统一进 `utils/`、
> 模板放在 app 内部的 `templates/app01/` 并统一继承 `layout.html`。

```
hrms/
├── manage.py
├── requirements.txt
├── hrms/                       # 项目配置层
│   ├── settings.py             # 注册 app、MySQL、中间件、静态
│   └── urls.py                 # 路由总入口（include app01.urls）
└── app01/                      # 业务应用层
    ├── models.py               # 9 张数据表（全部模型）
    ├── forms.py                # 兼容层，只做转发（新表单写 utils/form.py）
    ├── views/                  # 视图按业务拆包 ★
    │   ├── account.py          # 登录 / 注销 / 切换账号
    │   ├── dashboard.py        # 首页统计
    │   ├── department.py       # 部门 CRUD（ModelForm + change.html 标准套路）
    │   ├── employee.py         # 员工 CRUD（含头像上传）
    │   ├── attendance.py       # 考勤
    │   ├── salary.py           # 薪资
    │   ├── notice.py           # 公告
    │   ├── task.py             # 任务（列表 + AJAX 提交）
    │   ├── chart.py            # ECharts 数据接口
    │   └── rbac.py             # 用户 / 角色 / 权限
    ├── middleware/
    │   └── rbac.py             # RBAC 权限中间件（比模板的 AuthMiddleware 更强）
    ├── utils/                  # 公共能力包 ★
    │   ├── bootstrap.py        # 表单统一样式基类
    │   ├── form.py             # 所有 ModelForm
    │   ├── pagination.py       # 分页组件（保留搜索条件）
    │   ├── encrypt.py          # 密码哈希（PBKDF2，不是 MD5）
    │   ├── check_code.py       # 验证码统一入口
    │   └── captcha.py          # 验证码绘制实现（150×48 清晰版）
    ├── templates/app01/        # 模板 ★
    │   ├── layout.html         # 全局布局（原 base.html）
    │   ├── change.html         # 通用表单页（新建/编辑共用）
    │   ├── login.html  index.html
    │   └── department/ employee/ attendance/ salary/ notice/ task/ role/ user/ chart/ ...
    ├── templatetags/           # 模板过滤器
    └── management/commands/    # init_data / demo_data
```

> 模板查找靠 `settings.TEMPLATES["APP_DIRS"] = True`（`DIRS` 已留空），
> 所以视图里写 `render(request, "app01/xxx.html")`、模板里写
> `{% extends "app01/layout.html" %}`。
