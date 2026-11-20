"""
Django 后台注册（访问地址 /admin/）
===================================

把九张表都注册进 Django 自带的后台，用途有三个：
    1. 答辩被问"数据怎么来的"时，可以打开 /admin/ 现场看表结构和真实记录；
    2. 调试期直接在后台改数据，不用写 SQL；
    3. 需要临时造一条测试数据时，比跑脚本快。

要讲清楚的一点：/admin/ 只是框架自带的调试窗口，不是本项目的功能主体，
所有业务页面（部门、员工、考勤、薪资、公告、任务、图表）都在 app01 自己写的视图里。
它同样受 RbacMiddleware 保护：未登录访问会被重定向到本项目的 /login/；
登录了但没有 /admin/ 这条权限则直接 403（超管靠 is_superuser 放行，不受权限表限制）。

注意：admin 里改数据同样会经过模型的 save()，
所以考勤状态、实发工资这些自动计算的字段，在后台改也照样会重新算一遍。
"""
from django.contrib import admin
from app01 import models

admin.site.register(models.User)
admin.site.register(models.Role)
admin.site.register(models.Permission)
admin.site.register(models.Department)
admin.site.register(models.Employee)
admin.site.register(models.Attendance)
admin.site.register(models.Salary)
admin.site.register(models.Notice)
admin.site.register(models.Task)
