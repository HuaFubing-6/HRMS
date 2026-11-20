"""
数据范围工具
============

中间件解决的是"能不能访问这个 URL"（URL 级权限）。
但同一类角色之间还要再分一层：范围——即"能看哪些数据行"。
    - 部门管理员：只能看/改自己部门的数据，不能跨部门
    - 普通员工：只能看自己的工资

这一层必须在视图里做，因为只有视图知道
"当前账号绑了哪个部门、对应哪个员工"——中间件拿不到这些业务语义。

用法（视图里）：
    from app01.utils.scope import is_dept_admin, is_plain_employee
    if is_dept_admin(request.user):
        queryset = queryset.filter(depart_id=request.user.depart_id)
"""


DEPT_ADMIN_TITLE = "部门管理员"
STAFF_TITLE = "普通员工"


def is_dept_admin(user):
    """
    判断是不是"绑定了部门的部门管理员"。

    四个条件缺一不可：
    1. 已登录；
    2. 不是超管 —— 超管要看全站，不能被自己的 depart 限制住；
    3. 角色名是"部门管理员"；
    4. 真的绑了部门 —— 没绑部门的部门管理员没有管辖范围，
       这时不启用过滤（退回全量），否则他什么数据都看不到，比不限制更糟。
    """
    return (
        user.is_authenticated
        and not user.is_superuser
        and user.role is not None
        and user.role.title == DEPT_ADMIN_TITLE
        and user.depart_id is not None
    )


def is_plain_employee(user):
    """
    判断是不是"普通员工"这个角色。

    ★ 注意这里**故意不要求** user.employee_id 非空，原因：
      最早写的是"绑了员工档案才算普通员工"，结果没绑档案的普通员工
      在这里判定成 False，视图里那段 if 整段被跳过 —— 等于**退回看全量**，
      他一点进薪资管理就看到全公司所有人的工资，正好是最该防住的泄露。
      所以现在按"身份"判断，绑没绑交给下面的 plain_employee_salary_scope
      决定：绑了只看自己那条，没绑一条都不给（绝不是"全给"）。

    函数名故意不叫 is_staff：Django 的 user.is_staff 是"能否进后台"，
    两者含义完全不同，重名会让人在答辩时讲错。
    """
    return (
        user.is_authenticated
        and not user.is_superuser
        and user.role is not None
        and user.role.title == STAFF_TITLE
    )


def plain_employee_scope(queryset, user):
    """
    把"按员工过滤"的 queryset 收敛到普通员工自己的那部分。

    薪资表和考勤表的外键字段都叫 employee_id，所以同一个函数两处通用。
    两种情况：
      1. 绑了员工档案 → filter(employee_id=...)，只留自己那几条；
      2. 没绑档案   → queryset.none()，一条都不返回。
    第 2 种绝不能返回原 queryset：那样等于把全公司的工资/考勤都给他。
    返回空列表时页面会提示"请联系管理员绑定员工档案"，
    这比"悄悄看到全部"安全得多。
    """
    if user.employee_id:
        return queryset.filter(employee_id=user.employee_id)
    return queryset.none()
