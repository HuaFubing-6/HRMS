"""
演示数据命令：python manage.py demo_data
=========================================

作用：一条命令造出可直接演示的数据，对齐参考截图（6 部门 / 18 员工 / 54 条薪资 / 5 公告）。
答辩时如果被要求"现场重来一遍"，这条命令能在一秒内恢复演示环境。

设计要点：
- 全部用 get_or_create 或"先判断数量"，重复执行不会把数据堆成两倍；
- 手机号按 1[3-9]+9 位随机生成，保证能通过 EmployeeForm 的正则校验；
- 薪资覆盖近三个月，这样薪资趋势折线图有三段，不是一条平线。
"""
import random
from datetime import date, timedelta

from django.core.management.base import BaseCommand

from app01 import models


class Command(BaseCommand):
    """
    写演示数据：部门、员工、考勤、薪资、公告。

    全部走 get_or_create 或"只补差额"，重复执行不会让数据翻倍，
    所以答辩前想补点数据，直接再跑一次即可。
    """

    help = "写入演示数据"

    def handle(self, *args, **options):
        """按「部门 → 员工 → 考勤 → 薪资 → 公告」的顺序造数，后一步依赖前一步的数据。"""
        # ---- 1. 部门（6 个）----
        dept_names = ["技术部", "人事部", "财务部", "市场部", "运营部", "产品部"]
        depts = []
        for name in dept_names:
            d, _ = models.Department.objects.get_or_create(title=name)
            depts.append(d)

        # ---- 2. 员工（补到 18 人）----
        # 只补差额，不重复造：把 18-existing 作为循环次数
        surnames = ["张", "李", "王", "刘", "陈", "杨", "赵", "黄", "周", "吴", "徐", "孙"]
        given = ["伟", "芳", "娜", "敏", "静", "磊", "洋", "艳", "勇", "军", "杰", "娟", "涛", "明", "超", "霞"]
        existing = models.Employee.objects.count()
        if existing >= 18:
            self.stdout.write("员工已存在，跳过造数")
        else:
            for _ in range(18 - existing):
                name = random.choice(surnames) + random.choice(given)
                # 生成合法手机号：1 + [3-9] + 9 位数字，正好 11 位
                phone = "1" + random.choice(["3", "5", "7", "8", "9"]) + "".join(
                    random.choices("0123456789", k=9)
                )
                models.Employee.objects.create(
                    name=name,
                    age=random.randint(22, 45),          # 落在 16~65 的合法区间内
                    gender=random.randint(0, 1),
                    account=random.randint(1000, 50000),
                    # 入职时间随机分布在 2020-01-01 之后约 4 年内
                    entry_time=date(2020, 1, 1) + timedelta(days=random.randint(0, 1500)),
                    phone=phone,
                    depart=random.choice(depts),
                )

        # ---- 3. 薪资（每个员工 × 近 3 个月）----
        # 只在薪资表为空时生成，避免重复执行变成 108 条
        emp_list = list(models.Employee.objects.all())
        if models.Salary.objects.count() == 0:
            months = ["2026-08", "2026-09", "2026-10"]
            for emp in emp_list:
                for m in months:
                    base = random.randint(6000, 15000)
                    bonus = random.randint(0, 3000)
                    deduct = random.randint(0, 1000)
                    # 注意：这里不传 total，由 Salary.save() 自动算实发
                    models.Salary.objects.create(
                        employee=emp, month=m,
                        base_pay=base, bonus=bonus, deduction=deduct,
                    )

        # ---- 4. 公告（5 条，两条置顶）----
        if models.Notice.objects.count() == 0:
            # 发布人取当前超级管理员，而不是写死 "admin"：
            # 账号改名后写死会导致找不到人、外键为空直接报错
            publisher = models.User.objects.filter(is_superuser=True).first()
            if publisher is None:
                self.stdout.write(
                    self.style.ERROR("未找到超级管理员账号，请先执行：python manage.py init_data")
                )
                return

            # 元组第三项是 is_top，前两条置顶，正好演示"置顶优先排序"
            notices = [
                ("关于加强信息安全管理的通知", "近期钓鱼邮件频发，请全员注意账号安全。", True),
                ("关于国庆中秋假期安排的通知", "国庆中秋连休 8 天，值班表见附件。", True),
                ("办公系统升级维护公告", "本周六 22:00-24:00 系统升级，请提前保存工作。", False),
                ("公司新员工入职培训通知", "下周三下午 14:00 三楼会议室举行新员工培训。", False),
                ("2026年第三季度优秀员工名单公示", "经过综合评定，第三季度优秀员工名单如下。", False),
            ]
            for title, content, top in notices:
                # create_time 由 auto_now_add 自动写入，这里不用传
                models.Notice.objects.create(title=title, content=content, user=publisher, is_top=top)

        self.stdout.write(self.style.SUCCESS("演示数据写入完成"))
