"""
首页仪表盘（对应参考截图的三/四张统计卡）
==========================================

四个数字不是写死的，每次刷新都从数据库实时 count()。
答辩时若被问"为什么改了数据首页数字会变"，就是因为这里读的是实时值。

count() 走的是 SQL 的 COUNT(*)，只返回数字、不搬数据，开销很小。

答辩可讲点（第二步"首页四个数字"）：
  1. 数字不是写死的 —— 每次刷新都实时查，改了数据回来就变
  2. count() 只回一个数字 —— 不把记录搬到 Python，开销很小
"""
from django.shortcuts import render

from app01 import models


def index(request):
    """首页：统计四个核心实体的数量。"""
    # 四个数字各自对应一张统计卡（顺序和页面上从左到右一致）
    # 每个 count() 都是一条 SELECT COUNT(*)：只回一个整数，不搬任何记录，
    # 所以四次查询的开销可以忽略（数据量大时也不过是四个索引扫描）
    data = {
        "dept_count": models.Department.objects.count(),      # 部门数量
        "emp_count": models.Employee.objects.count(),         # 员工数量
        "notice_count": models.Notice.objects.count(),        # 公告数量
        "salary_count": models.Salary.objects.count(),        # 薪资记录数
    }

    # 模板里直接用 {{ dept_count }} 之类取值；
    # 注意这是"每次刷新才算"的实时值，不是页面打开时的缓存
    return render(request, "app01/index.html", data)
