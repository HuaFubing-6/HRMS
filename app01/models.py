"""
app01 数据模型（数据库设计）
============================

设计思路：
1. 先定 RBAC（角色/权限/用户），因为登录与权限是全站基础；
2. 再定业务实体（部门/员工），其余模块（考勤/薪资/公告/任务）都挂在员工上；
3. 能用数据库约束的就不放到视图里（如外键级联、choices 限制取值）；
4. 能由数据推导出来的字段（考勤状态、实发工资）在 save() 里自动算，避免前后端不一致。

实体关系（答辩时画这张图即可）：
    Role  ←M:N→  Permission        # 角色拥有多个权限，权限可被多个角色复用
    User  →1  Role                 # 一个用户一个角色；User 继承 AbstractUser
    Department ←1:N→ Employee      # 一个部门多个员工，删部门级联删员工
    Employee ←1:N→ Attendance      # 一个员工多条考勤
    Employee ←1:N→ Salary          # 一个员工多条薪资（按月）
    User     ←1:N→ Notice          # 发布人即登录用户
    Employee ←1:N→ Task            # 负责人是员工

答辩可讲点（老师让"打开代码讲讲"时，按这四步说）：
  1. 文件头「设计思路」—— 为什么先定 RBAC 再定业务；能推导的字段一律放 save() 里算
  2. 两个 save() —— Attendance 算考勤状态、Salary 算实发工资，都是"单一数据源"
  3. 两个 to_xxx —— to_time / to_decimal，正是修掉的两个 TypeError 的产物
  4. 字段上方注释 —— 钱为什么用 Decimal、phone 为什么不在模型层做唯一约束
"""
import calendar
# date 在这里被重命名为 date_cls：Attendance 模型自己有个 date 字段，
# 直接 from datetime import date 容易在类体里看混，起个别名更清楚
from datetime import date as date_cls, datetime, time
from decimal import Decimal, InvalidOperation

from django.db import models
from django.contrib.auth.models import AbstractUser
# Sum：薪资保存时汇总本月考勤罚款用
from django.db.models import Sum


# ------------------------------------------------------------------
# RBAC：用户 - 角色 - 权限
# ------------------------------------------------------------------
class Role(models.Model):
    """
    角色表：超级管理员 / 部门管理员 / 普通员工。

    permissions 用 ManyToManyField 而不是外键，是因为：
    同一个权限（比如 /notice/list/）要被多个角色共用，
    多对多才不需要为每个角色复制一份权限记录。
    """

    # unique=True：角色名唯一。重名若不在这里拦，新增角色会抛 IntegrityError → 500
    title = models.CharField(max_length=32, unique=True, verbose_name="角色名称")
    permissions = models.ManyToManyField(
        to="Permission",
        blank=True,          # 允许一个角色暂时没有任何权限
        verbose_name="拥有的权限",
    )

    class Meta:
        verbose_name = "角色"
        verbose_name_plural = verbose_name

    def __str__(self):
        # 后台/模板里直接 {{ role }} 就显示角色名，而不是 "Role object (1)"
        return self.title


class Permission(models.Model):
    """
    权限表：一条记录 = 一个可访问的 URL。

    为什么用 URL 字符串做权限粒度？
    因为中间件能直接拿 request.path_info 去比对，不需要在每个视图里写装饰器，
    新增一个页面只要往这张表插一行、再挂到角色上即可。
    """

    # 给人看的名字，如"部门列表""删除部门"
    title = models.CharField(max_length=32, verbose_name="权限名称")
    # 存的是中间件要拿去比对的路径：列表页存 /department/list/，
    # 带主键的增删改由"前缀匹配"兜住（见 middleware/rbac.py 第 4.2 段）
    url = models.CharField(max_length=128, verbose_name="正则路由", help_text="如 /department/list/")

    class Meta:
        verbose_name = "权限"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


class User(AbstractUser):
    """
    自定义用户模型：继承 AbstractUser，多挂一个 role 外键。

    为什么不直接用 Django 自带 User？
    1. 自带 User 没法加角色字段，硬改不优雅；
    2. 任务书要求 AUTH_USER_MODEL 指向自定义模型。
    继承 AbstractUser 的好处是 username / password / is_superuser 全部现成，
    password 字段自带 PBKDF2 哈希，不需要自己实现加密。

    on_delete=SET_NULL：角色被删时用户保留，只是变回"无角色"，
    避免删角色把账号一起删掉。
    """

    role = models.ForeignKey(
        to=Role,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        verbose_name="角色",
    )

    # ---- 部门管理员：这个账号管哪个部门 ----
    # 只有 role 是"部门管理员"时才有意义；普通员工和超管留空即可。
    # 视图层用它做数据过滤，实现"部门管理员不能跨部门管理"（T5 的细化要求）。
    # SET_NULL：部门被删时账号保留，只是失去管辖范围，不会把账号一起删掉。
    # related_name 避免和 Employee 那边的反向查询重名。
    depart = models.ForeignKey(
        to="Department",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="admin_users",
        verbose_name="管辖部门",
        help_text="仅部门管理员需要填",
    )

    # ---- 普通员工：这个账号对应哪个员工档案 ----
    # 用于"员工只能看见自己的工资"：salary_list 里按 user.employee 过滤。
    # 用 OneToOne 而不是 ForeignKey：一个员工档案只应绑定一个登录账号，
    # 否则两个账号看同一份工资，账就说不清了。
    # 注意 Employee 定义在下面，所以这里用字符串 "Employee" 延迟引用。
    employee = models.OneToOneField(
        to="Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="login_account",
        verbose_name="对应员工",
        help_text="仅普通员工需要填",
    )

    class Meta:
        verbose_name = "用户"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.username


# ------------------------------------------------------------------
# 部门 / 员工
# ------------------------------------------------------------------
class Department(models.Model):
    """部门表：整个系统里最简单的表，用来先跑通 MTV 全流程。"""

    title = models.CharField(max_length=32, verbose_name="部门名称")

    class Meta:
        verbose_name = "部门"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


class Employee(models.Model):
    """
    员工表。

    字段与任务书 T3 一一对应：姓名、年龄、性别、账户余额、入职时间、手机号、部门、头像。
    注意两点设计取舍：
    1. gender 用 SmallIntegerField + choices，而不是 CharField：
       存整数省空间，choices 保证只能取 0/1，模板里 get_gender_display() 自动出"男/女"。
    2. account / salary 用 DecimalField 而不是 FloatField：
       钱不能用浮点数，0.1+0.2 会出精度误差。
    3. depart 用 CASCADE：部门没了，部门下的员工也没有归属，级联删除。
    4. avatar 用 FileField + upload_to，文件落到 MEDIA_ROOT/avatar/，数据库只存相对路径。
    """

    GENDER_CHOICES = ((0, "男"), (1, "女"))

    # 姓名：列表页的模糊搜索查的就是这个字段（name__icontains）
    name = models.CharField(max_length=32, verbose_name="姓名")
    # 年龄：表单里配了 min/max，防止填出 0 岁或负数
    age = models.IntegerField(verbose_name="年龄")
    # 0 男 / 1 女；模板调 get_gender_display() 直接出中文，不用写 if
    gender = models.SmallIntegerField(choices=GENDER_CHOICES, default=0, verbose_name="性别")
    # 钱一律用 Decimal：FloatField 存 0.1+0.2 会出 0.30000000000000004
    account = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="账户余额"
    )
    # 只存日期，不带时分秒；列表页"入职时间"直接显示
    entry_time = models.DateField(verbose_name="入职时间")
    # 11 位字符串；唯一性校验在 EmployeeForm.clean_phone 里（编辑时 exclude(pk) 排除自己）
    phone = models.CharField(max_length=11, verbose_name="手机号")
    # CASCADE：部门被删，部门下的人一起删——员工失去部门就没有归属了
    depart = models.ForeignKey(
        to=Department,
        on_delete=models.CASCADE,
        verbose_name="所属部门",
    )
    # 库里只存相对路径 avatar/xxx.png，文件本体在 MEDIA_ROOT 下；
    # 上传时表单必须带 enctype="multipart/form-data"，否则 request.FILES 是空的
    avatar = models.FileField(
        upload_to="avatar/", blank=True, null=True, verbose_name="头像"
    )

    class Meta:
        verbose_name = "员工"
        verbose_name_plural = "员工"

    def __str__(self):
        return self.name


# ------------------------------------------------------------------
# 考勤
# ------------------------------------------------------------------
class Attendance(models.Model):
    """
    考勤表：状态由上下班时间自动算出来，不允许人工选择。

    任务书明确要求"不要让学生手动选择状态字段"，
    所以 status 虽然还在模型里（要存库、要展示），但只在 save() 里赋值。
    """

    STATUS_CHOICES = (
        ("normal", "按时"),
        ("late", "迟到"),
        ("early", "早退"),
        ("absent", "缺勤"),
    )

    employee = models.ForeignKey(
        to=Employee, on_delete=models.CASCADE, verbose_name="员工"
    )
    # 一条记录 = 某人某天；列表页按日期倒序，同一天多条按时间排
    date = models.DateField(verbose_name="日期")
    # blank=True, null=True：允许只打一次卡（只上班没下班，或反过来）
    on_time = models.TimeField(blank=True, null=True, verbose_name="上班时间")
    off_time = models.TimeField(blank=True, null=True, verbose_name="下班时间")
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="normal", verbose_name="考勤状态"
    )

    # ---- 违规罚款（制度参数）----
    # 金额集中写成类常量，改制度只改这三行，不用去视图或模板里找
    # 用 Decimal 而不是 int/float：罚款最终会流进薪资表做加减，
    # 全程 Decimal 才能保证"分"不丢、不出现 0.9999999 这种浮点误差
    FINE_LATE = Decimal("50")      # 迟到一次罚 50
    FINE_EARLY = Decimal("50")     # 早退一次罚 50
    FINE_ABSENT = Decimal("200")   # 缺勤一天罚 200

    # 罚款金额由 save() 根据状态自动算出来，和 status 一样不允许人工填
    # default=0 是为了已有数据迁移后能直接落地，不会因为缺值报错
    fine = models.DecimalField(
        max_digits=8, decimal_places=2, default=0, verbose_name="违规罚款"
    )

    class Meta:
        verbose_name = "考勤"
        verbose_name_plural = verbose_name

    def save(self, *args, **kwargs):
        """
        重写 save：根据上下班时间自动判定状态。

        为什么放在模型层而不是视图层？
        因为不管从网页表单、后台 admin 还是脚本创建，都会经过 save()，
        规则只写一处，不会出现"某个入口忘了算状态"的情况。

        为什么先做 to_time 转换？
        HTML 的 <input type="time"> 提交上来是字符串 "09:07"，
        字符串不能和 time 对象比大小，直接比较会抛
        TypeError: '>' not supported between instances of 'str' and 'time'。
        这是本项目实际踩到并修掉的一个 bug。
        """
        self.on_time = self.to_time(self.on_time)
        self.off_time = self.to_time(self.off_time)

        # 规则 1：两头都没打卡 -> 缺勤
        if self.on_time is None and self.off_time is None:
            self.status = "absent"
        else:
            # 规则 2：上班晚于 09:00 -> 迟到（迟到优先于早退，两者同时满足时记迟到）
            if self.on_time and self.on_time > time(9, 0):
                self.status = "late"
            # 规则 3：下班早于 18:00 -> 早退
            elif self.off_time and self.off_time < time(18, 0):
                self.status = "early"
            # 规则 4：其余情况按时
            else:
                self.status = "normal"

        # ---- 按判定出的状态给罚款 ----
        # 放在状态判定之后、super().save() 之前：罚款依赖 status，
        # 顺序反了会拿上一次的旧状态算钱。
        # 迟到和早退同时满足时，上面的规则 2 优先判成"迟到"，所以这里只罚一份 50，
        # 不会出现"又迟到又早退罚两次"的重叠计算。
        if self.status == "late":
            self.fine = self.FINE_LATE
        elif self.status == "early":
            self.fine = self.FINE_EARLY
        elif self.status == "absent":
            self.fine = self.FINE_ABSENT
        else:
            self.fine = Decimal("0")

        super().save(*args, **kwargs)

    @staticmethod
    def to_time(value):
        """
        把 str / datetime / time 统一转成 time 对象，空值或无法解析返回 None。

        兼容 "%H:%M:%S" 和 "%H:%M" 两种写法：
        浏览器提交的一般是 "09:07"，而 Django 后台可能带秒 "09:07:00"。
        """
        if value in (None, ""):
            return None
        if isinstance(value, time):
            return value
        if isinstance(value, datetime):
            return value.time()
        if isinstance(value, str):
            text = value.strip()
            for fmt in ("%H:%M:%S", "%H:%M"):
                try:
                    return datetime.strptime(text, fmt).time()
                except ValueError:
                    continue
        return None

    def __str__(self):
        return f"{self.employee}-{self.date}"


# ------------------------------------------------------------------
# 薪资
# ------------------------------------------------------------------
class Salary(models.Model):
    """
    薪资表：实发 = 基本工资 + 奖金 - 扣款。

    month 用 CharField(max_length=7) 存 "2026-10" 而不是 DateField：
    薪资是按"月"聚合的，用日期存每月 1 号反而要做格式化，字符串更直观，
    也方便前端 <input type="month"> 直接绑定。
    """

    employee = models.ForeignKey(
        to=Employee, on_delete=models.CASCADE, verbose_name="员工"
    )
    # 存 "2026-10" 而不是 DateField：薪资按月聚合，字符串能直接和 <input type="month"> 对上
    month = models.CharField(max_length=7, verbose_name="月份", help_text="格式：2026-10")
    # 下面三项都允许留空，save() 里 to_decimal 会把空值归一成 Decimal("0")
    base_pay = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="基本工资"
    )
    bonus = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="奖金"
    )
    deduction = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="扣款"
    )
    # 考勤罚款：不手填，由 save() 去考勤表按"该员工 + 该月"汇总（迟到/早退/缺勤累加）。
    # 单独一个字段而不是并进 deduction，是为了让"钱扣在哪"能解释清楚：
    # deduction 是管理员手填的其他扣款，attendance_fine 是制度自动算的。
    attendance_fine = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="考勤罚款"
    )
    # 结果字段：表单里没有它、视图也不传它，一律由 save() 用上面三项算出来覆盖
    total = models.DecimalField(
        max_digits=10, decimal_places=2, default=0, verbose_name="实发工资"
    )

    class Meta:
        verbose_name = "薪资"
        verbose_name_plural = verbose_name

    def save(self, *args, **kwargs):
        """
        重写 save：保存前统一计算实发工资。

        这样做的关键收益是"单一数据源"：
        页面上不用 JS 算一遍、后端再算一遍，避免两边不一致（任务书 4.2 阶段四的要求）。

        【踩过的坑】表单提交上来的金额是字符串 "8000"，
        `"8000" - "300"` 会抛 TypeError: unsupported operand type(s) for -: 'str' and 'str'。
        原来的 `(self.base_pay or 0)` 挡不住这个坑——非空字符串是真值，or 直接放行。
        所以这里先用 to_decimal 归一化，再参与四则运算，
        无论从网页、admin 还是脚本进来都不会崩。
        """
        self.base_pay = self.to_decimal(self.base_pay)
        self.bonus = self.to_decimal(self.bonus)
        self.deduction = self.to_decimal(self.deduction)

        # ---- 自动汇总"本月考勤罚款" ----
        # 罚款是考勤表算出来的结果，不能让用户在薪资表单里再手填一遍：
        # 两边各填一次，一定会对不上。这里按 employee + 月份去考勤表 SUM，
        # 不管从网页、admin 还是脚本保存薪资，罚款都会自动带上。
        self.attendance_fine = self.sum_attendance_fine()

        # 实发 = 基本工资 + 奖金 - 手动扣款 - 考勤罚款
        # 极端情况（罚款大于应发）会算出负数，表示"该员工欠公司钱"，
        # 这里不做 clamp 成 0，保留真实数值，页面上一眼能看出来异常
        self.total = self.base_pay + self.bonus - self.deduction - self.attendance_fine
        super().save(*args, **kwargs)

    def month_bounds(self):
        """
        把 "2026-11" 拆成 (2026-11-01, 2026-11-30)。

        为什么必须拆：month 是字符串，直接拿去和考勤表的 DateField 比大小，
        格式对不上，永远查不出记录（返回空，罚款就变成 0 了）。
        """
        try:
            year, month = self.month.split("-")
            year, month = int(year), int(month)
            first = date_cls(year, month, 1)
            # monthrange 返回 (当月 1 号是星期几, 当月天数)，用天数算月末，
            # 这样 2 月、30 天、31 天的月份都不用单独判断
            last = date_cls(year, month, calendar.monthrange(year, month)[1])
            return first, last
        except (AttributeError, ValueError):
            return None, None

    def sum_attendance_fine(self):
        """
        汇总本月该员工的考勤罚款。

        aggregate(Sum("fine")) 让数据库求和、只回一个数字，
        不把几十条考勤搬回内存再循环加。
        没有记录时 Sum 返回 None，用 `or Decimal("0")` 兜底，
        否则下一步拿 None 参与加法会抛 TypeError。
        """
        start, end = self.month_bounds()
        if not start:
            return Decimal("0")
        result = Attendance.objects.filter(
            employee_id=self.employee_id, date__gte=start, date__lte=end
        ).aggregate(total=Sum("fine"))
        return result["total"] or Decimal("0")

    @staticmethod
    def to_decimal(value):
        """
        把 str / int / float / Decimal / None 统一转成 Decimal，空值或非法内容按 0 处理。

        为什么要用 str(value) 包一层再转？
        因为 Decimal(0.1) 会把二进制浮点的误差原样带进来（0.1000000000000000055...），
        经 str 转一次再构造才是十进制语义的 0.1。
        """
        if value in (None, ""):
            return Decimal("0")
        if isinstance(value, Decimal):
            return value
        try:
            return Decimal(str(value).strip())
        except (InvalidOperation, ValueError):
            return Decimal("0")

    def __str__(self):
        return f"{self.employee}-{self.month}"


# ------------------------------------------------------------------
# 公告
# ------------------------------------------------------------------
class Notice(models.Model):
    """
    公告表。

    create_time 用 auto_now_add=True：
    发布时间由数据库写入，用户既不能填也不能改，杜绝"伪造发布时间"。
    user 是外键指向 User，而不是存发布人姓名字符串，这样能跟随账号改名。
    """

    # 标题参与模糊搜索（notice_list 里 title__icontains）
    title = models.CharField(max_length=64, verbose_name="标题")
    # 用 TextField 而不是 CharField：正文不限长度、允许换行
    content = models.TextField(verbose_name="内容")
    user = models.ForeignKey(
        to=User, on_delete=models.CASCADE, verbose_name="发布人"
    )
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="发布时间")
    is_top = models.BooleanField(default=False, verbose_name="是否置顶")

    # 发布部门：部门管理员发的公告自动落在自己部门，只有本部门能看到；
    # 留空（null）表示"全公司公告"，谁登录都能看到（超管发的就是这种）。
    # SET_NULL：部门被删后公告不消失，只是退回成"全公司可见"，
    # 免得删一个部门把历史通知一起删了。
    depart = models.ForeignKey(
        to=Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="notices",
        verbose_name="发布部门",
        help_text="留空表示全公司公告",
    )

    class Meta:
        verbose_name = "公告"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


# ------------------------------------------------------------------
# 任务（AJAX）
# ------------------------------------------------------------------
class Task(models.Model):
    """任务表：字段与任务书 T9 一致（级别、标题、详情、负责人）。"""

    LEVEL_CHOICES = ((1, "高"), (2, "中"), (3, "低"))

    # ---- 审核状态（任务要经超管审核才生效）----
    # 部门管理员发布的任务默认 pending，超管在任务列表里点"通过/驳回"才变；
    # 超管自己发布的任务直接 approved（自己发的自己审没有意义）。
    STATUS_CHOICES = (
        ("pending", "待审核"),
        ("approved", "已通过"),
        ("rejected", "已驳回"),
    )

    # 1 高 / 2 中 / 3 低；列表页 get_level_display() 出中文，排序按数字大小
    level = models.SmallIntegerField(choices=LEVEL_CHOICES, verbose_name="级别")
    # 至少 2 个字符：规则写在 TaskForm 里，新增（AJAX）和编辑共用同一份
    title = models.CharField(max_length=64, verbose_name="标题")
    detail = models.TextField(verbose_name="详情")
    leader = models.ForeignKey(
        to=Employee, on_delete=models.CASCADE, verbose_name="负责人"
    )

    # 审核状态：由超管在列表页操作，不允许发布人自己改（视图里只有审核接口能改它）
    status = models.CharField(
        max_length=16, choices=STATUS_CHOICES, default="pending", verbose_name="审核状态"
    )
    # 完成标记：任务干完了打勾，列表页据此显示"已完成"标签。
    # 只有审核通过的任务才能被标记完成（视图里拦），否则会出现"被驳回却已完成"
    is_done = models.BooleanField(default=False, verbose_name="是否已完成")
    # 归属部门：部门管理员发布的任务落在自己部门，只有本部门（和超管）能看到。
    # 超管发布的全公司任务留空（null），所有人都能看到。
    # SET_NULL：部门被删时任务保留，只是失去归属，不会连带删掉历史任务
    depart = models.ForeignKey(
        to=Department,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
        verbose_name="归属部门",
        help_text="留空表示全公司任务",
    )
    # 发布人：用来在列表里区分"谁提的任务"，也用于部门管理员查自己发的
    # 用 User 而不是存姓名字符串，账号改名后这里自动跟着变
    publisher = models.ForeignKey(
        to=User,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="tasks",
        verbose_name="发布人",
    )

    class Meta:
        verbose_name = "任务"
        verbose_name_plural = verbose_name

    def __str__(self):
        return self.title


class Knowledge(models.Model):
    """
    企业知识库（T3 制度问答的"资料"来源）
    ======================================

    为什么不用向量数据库：
      本项目只有几条制度，直接用 SQL 的 icontains 做关键词检索就够；
      检索结果整段拼进提示词即可，属于"最小可用版 RAG"。
      上向量库要额外跑一个服务、做 embedding，课设规模不划算。

    检索字段的设计：
      title    —— 制度名，用户常说"考勤""报销"，容易命中
      content  —— 正文，命中后整段作为资料注入提示词
      keywords —— 人工补充的同义词，解决"迟到"找不到"考勤管理办法"的问题
      is_active—— 停用的条目不参与检索（制度作废时不用删数据）
    """

    CATEGORY_CHOICES = (
        ("attendance", "考勤"),
        ("expense", "报销"),
        ("leave", "请假"),
        ("salary", "薪酬"),
        ("security", "保密"),
        ("other", "其他"),
    )

    title = models.CharField(max_length=128, verbose_name="制度标题")
    content = models.TextField(verbose_name="制度内容")

    category = models.CharField(
        max_length=16,
        choices=CATEGORY_CHOICES,
        default="other",
        verbose_name="分类",
    )

    # 同义词/别名，用逗号分隔，例如"打卡,上下班,迟到,早退"
    keywords = models.CharField(
        max_length=128,
        blank=True,
        verbose_name="检索关键词",
        help_text="多个词用逗号分隔，用于补充同义词",
    )

    is_active = models.BooleanField(default=True, verbose_name="是否启用")

    # auto_now_add：只在创建时写一次，后续编辑不改
    create_time = models.DateTimeField(auto_now_add=True, verbose_name="创建时间")

    class Meta:
        verbose_name = "制度条目"
        verbose_name_plural = verbose_name
        # 按分类、标题排序，检索结果顺序稳定，方便复现和答辩演示
        ordering = ["category", "id"]

    def __str__(self):
        return self.title

    def short_content(self, length=80):
        """列表页摘要：避免把整段制度内容铺在表格里。"""
        return self.content if len(self.content) <= length else self.content[:length] + "…"
