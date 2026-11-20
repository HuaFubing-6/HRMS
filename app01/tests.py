"""单元测试：登录、员工校验、薪资计算、权限拦截（任务书 T12）。

答辩可讲点（第十二步"跑一遍单测"时看这个文件）：
  1. 每个测试类自己 setUp 造最小数据 —— 测试库是空的，不依赖演示数据
  2. test_salary_total_with_string_input —— 把修掉的 TypeError 固化成回归用例
  3. test_string_time_no_typeerror —— 考勤那个字符串时间 bug 的回归用例
  4. test_edit_updates_instead_of_inserting —— 用 count() 前后比对证明是 UPDATE
  5. test_delete_role_keeps_its_users —— 证明 role 外键是 SET_NULL
"""
from django.test import TestCase, Client
from app01 import models


class EmployeeModelTest(TestCase):
    """
    模型层单测：实发工资自动计算、手机号唯一校验。

    测试库是空的（不会执行 init_data / demo_data），
    所以每个测试类都在 setUp 里自己造最小数据，互不依赖。
    """

    def setUp(self):
        """前端表单校验依赖一个真实部门记录，所以先建"测试部"。"""
        self.dept = models.Department.objects.create(title="测试部")

    def test_salary_total_auto(self):
        """实发 = 基本 + 奖金 - 扣款。"""
        emp = models.Employee.objects.create(
            name="测试", age=30, phone="13800138000",
            entry_time="2024-01-01", depart=self.dept,
        )
        s = models.Salary.objects.create(employee=emp, month="2026-10",
                                        base_pay=10000, bonus=2000, deduction=500)
        self.assertEqual(float(s.total), 11500.0)

    def test_salary_total_with_string_input(self):
        """
        回归：表单提交的金额是字符串，不能让 save() 抛 TypeError。

        这是 /salary/add/ 真实报过的错：
        unsupported operand type(s) for -: 'str' and 'str'
        """
        emp = models.Employee.objects.create(
            name="字符串", age=30, phone="13600136000",
            entry_time="2024-01-01", depart=self.dept,
        )
        s = models.Salary.objects.create(employee=emp, month="2026-11",
                                        base_pay="8000", bonus="1500", deduction="300")
        self.assertEqual(float(s.total), 9200.0)

    def test_salary_blank_money_as_zero(self):
        """金额留空（空字符串）按 0 处理，不报错。"""
        emp = models.Employee.objects.create(
            name="留空", age=30, phone="13500135000",
            entry_time="2024-01-01", depart=self.dept,
        )
        s = models.Salary.objects.create(employee=emp, month="2026-11",
                                        base_pay="9000", bonus="", deduction="")
        self.assertEqual(float(s.total), 9000.0)

    def test_phone_unique_validation(self):
        """手机号唯一校验。"""
        # 先真的落一条"甲"，再用同一个手机号构造一个尚未入库的"乙"交给表单：
        # 唯一性规则不在数据库层，而在 EmployeeForm.clean_phone 里，
        # 所以必须走表单校验才能测到
        models.Employee.objects.create(
            name="甲", age=30, phone="13900139000",
            entry_time="2024-01-01", depart=self.dept,
        )
        # instance=dup 但 dup 还没入库，相当于"编辑一条待创建的数据"，
        # 规则会把已经存在的"甲"当成冲突对象，因此 is_valid() 应为 False
        dup = models.Employee(
            name="乙", age=30, phone="13900139000",
            entry_time="2024-01-01", depart=self.dept,
        )
        from app01.forms import EmployeeForm
        form = EmployeeForm(instance=dup, data={
            "name": "乙", "age": 30, "gender": 0, "account": 0,
            "entry_time": "2024-01-01", "phone": "13900139000", "depart": self.dept.id,
        })
        self.assertFalse(form.is_valid())


class AttendanceStatusTest(TestCase):
    """考勤状态自动判定：覆盖视图传字符串时间的真实场景。"""

    def setUp(self):
        """每个测试方法前重建一份最小数据：一个部门 + 一个员工。"""
        self.dept = models.Department.objects.create(title="考勤部")
        self.emp = models.Employee.objects.create(
            name="考勤人", age=28, phone="13700137000",
            entry_time="2024-01-01", depart=self.dept,
        )

    def _make(self, on_time, off_time):
        """用字符串时间创建，模拟 HTML 表单提交。"""
        return models.Attendance.objects.create(
            employee=self.emp, date="2026-11-07",
            on_time=on_time, off_time=off_time,
        )

    def test_late(self):
        """09:07 上班 → 迟到（晚于 9:00）。"""
        self.assertEqual(self._make("09:07", "19:55").status, "late")

    def test_normal(self):
        """08:50 上班、18:30 下班 → 按时。"""
        self.assertEqual(self._make("08:50", "18:30").status, "normal")

    def test_early(self):
        """17:00 下班 → 早退（早于 18:00）。"""
        self.assertEqual(self._make("08:40", "17:00").status, "early")

    def test_absent(self):
        """两头都没打卡 → 缺勤。"""
        self.assertEqual(self._make("", "").status, "absent")

    def test_string_time_no_typeerror(self):
        """回归：字符串时间不能与 time 对象直接比较而抛 TypeError。"""
        obj = self._make("09:07", "19:55")
        self.assertIsInstance(obj.on_time, object)
        self.assertIn(obj.status, ["normal", "late", "early", "absent"])


class LoginTest(TestCase):
    """登录拦截：未登录访问首页必须 302 跳登录页（RBAC 中间件第 2 段逻辑）。"""

    def test_redirect_when_not_login(self):
        c = Client()
        resp = c.get("/index/")
        self.assertEqual(resp.status_code, 302)


class TaskCrudTest(TestCase):
    """任务的编辑与删除（T9 的后半部分）。"""

    def setUp(self):
        """准备一条可编辑/可删除的任务，并用超管登录（超管在中间件里直接放行）。"""
        self.dept = models.Department.objects.create(title="任务部")
        self.emp = models.Employee.objects.create(
            name="负责人", age=30, phone="13400134000",
            entry_time="2024-01-01", depart=self.dept,
        )
        # 用一个超管账号登录：超管在中间件里直接放行，不用配权限就能测
        self.user = models.User.objects.create_user(
            username="tester", password="123", is_superuser=True, is_staff=True,
        )
        self.c = Client()
        self.c.force_login(self.user)
        # 造一条原始记录，后面测"改完之后还是这一条、只是内容变了"，
        # 用 count() 前后比对就能证明没有偷偷新增
        self.task = models.Task.objects.create(
            level=1, title="原标题", detail="原详情", leader=self.emp,
        )

    def test_edit_updates_instead_of_inserting(self):
        """编辑必须 UPDATE 原记录，不能新建一条。"""
        before = models.Task.objects.count()
        resp = self.c.post(f"/task/edit/{self.task.pk}/", {
            "level": 3, "title": "改后标题", "detail": "改后详情", "leader": self.emp.pk,
        })
        self.assertEqual(resp.status_code, 302)
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "改后标题")
        self.assertEqual(self.task.level, 3)
        self.assertEqual(models.Task.objects.count(), before)  # 条数没变

    def test_edit_rejects_short_title(self):
        """编辑沿用 TaskForm 的校验：标题少于 2 个字符应被退回。"""
        resp = self.c.post(f"/task/edit/{self.task.pk}/", {
            "level": 1, "title": "短", "detail": "x", "leader": self.emp.pk,
        })
        self.assertEqual(resp.status_code, 200)      # 回到表单页，不是 302 跳走
        self.task.refresh_from_db()
        self.assertEqual(self.task.title, "原标题")   # 原值没被改掉

    def test_delete(self):
        """删除后记录必须真的不存在（而不是只跳回列表页）。"""
        resp = self.c.get(f"/task/delete/{self.task.pk}/")
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(models.Task.objects.filter(pk=self.task.pk).exists())


class RoleCrudTest(TestCase):
    """角色的编辑与删除（T5 的配置界面）。"""

    def setUp(self):
        """造一个超管账号并登录，再自己建几条权限和一个角色——测试库是空的。"""
        self.user = models.User.objects.create_user(
            username="root", password="123", is_superuser=True, is_staff=True,
        )
        self.c = Client()
        self.c.force_login(self.user)
        # 测试库是空的（不会跑 init_data 的数据），所以自己造几条权限
        for i in range(5):
            models.Permission.objects.create(title=f"权限{i}", url=f"/p{i}/")
        self.role = models.Role.objects.create(title="临时角色")
        self.role.permissions.set(models.Permission.objects.all()[:2])

    def test_edit_role_title_and_permissions(self):
        """改名字 + 权限整体替换（set 覆盖面原有勾选）。"""
        ids = list(models.Permission.objects.all().values_list("id", flat=True)[:3])
        resp = self.c.post(f"/role/edit/{self.role.pk}/", {"title": "新角色名", "permissions": ids})
        self.assertEqual(resp.status_code, 302)
        self.role.refresh_from_db()
        self.assertEqual(self.role.title, "新角色名")
        self.assertEqual(self.role.permissions.count(), 3)

    def test_edit_duplicate_title_rejected(self):
        """角色名 unique，重名要给提示而不是抛 IntegrityError。"""
        models.Role.objects.create(title="已占用")
        resp = self.c.post(f"/role/edit/{self.role.pk}/", {"title": "已占用", "permissions": []})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "已被其他角色占用")

    def test_delete_role_keeps_its_users(self):
        """删角色不删账号：用户表的 role 外键是 SET_NULL。"""
        u = models.User.objects.create_user(username="hasrole", password="123", role=self.role)
        resp = self.c.get(f"/role/delete/{self.role.pk}/")
        self.assertEqual(resp.status_code, 302)
        u.refresh_from_db()
        self.assertIsNone(u.role)

    def test_super_role_is_protected(self):
        """超级管理员角色不允许删除。"""
        models.Role.objects.create(title="超级管理员")
        role = models.Role.objects.get(title="超级管理员")
        resp = self.c.get(f"/role/delete/{role.pk}/")
        self.assertEqual(resp.status_code, 302)
        self.assertIn("err=super", resp.headers["Location"])
        self.assertTrue(models.Role.objects.filter(pk=role.pk).exists())
