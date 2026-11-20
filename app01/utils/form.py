"""
表单层（utils 五件套之一）
==========================

为什么所有表单都放一个文件，不散在 views 里？
1. 视图只负责"取数据 → 调表单 → 决定跳转"，逻辑单一；
2. ModelForm 会自动把 POST 数据回填到字段，校验失败时页面还能保留用户输入；
3. clean_xxx 方法的报错会自动收集到 form.errors，模板里统一渲染。

为什么统一继承 BootStrapModelForm？
—— 字段的 class="form-control" 和 placeholder 由基类自动加，
   模板里直接 {{ field }} 就有 Bootstrap 样式，不用每页手写。

校验分工：
- 字段类型/必填/长度：Model 字段本身（max_length 等）
- 业务规则（年龄范围、手机号格式、唯一性）：clean_xxx 方法

答辩可讲点：
  1. 表单集中在这个文件 —— 视图只管"取数据 → 调表单 → 决定跳转"
  2. clean_xxx —— 规则跟字段绑在一起，报错自动进 form.errors，模板统一渲染
  3. clean_phone 的 exclude(pk=pk) —— 编辑时把自己排除，否则不改手机号就永远报"已存在"
  4. 年龄范围 / 手机号正则 —— 都写在 clean 里，不散落在视图的 if 里
"""
import re

from django import forms

from app01 import models
from app01.utils.bootstrap import BootStrapModelForm


class DepartmentForm(BootStrapModelForm):
    """
    部门表单：整个项目最短的表单，只用来说明"标准套路"。

    这里把原来的"视图里手写 if not title"改成 ModelForm 的 clean_title：
    - 校验规则跟字段绑在一起，部门接口以后加别的入口也不会漏校验；
    - 报错自动挂到字段上，模板统一用 {{ field.errors.0 }} 显示。
    """

    class Meta:
        model = models.Department
        # 部门表只有 title 一列，所以这里只有一个字段
        fields = ["title"]
        # 把 Django 默认的英文提示 "This field is required." 换成中文
        error_messages = {"title": {"required": "部门名称不能为空"}}

    def clean_title(self):
        """
        为什么还要 strip 一次？
        Django 的 CharField 默认会 strip，但只 strip 一层；
        这里显式再 strip 并把空串变成校验错误，保证库里不会出现"看不见的空部门"。
        """
        title = (self.cleaned_data.get("title") or "").strip()
        if not title:
            raise forms.ValidationError("部门名称不能为空")
        return title


class EmployeeForm(BootStrapModelForm):
    """
    员工表单：校验姓名长度、年龄范围、手机号正则 + 唯一。

    校验为什么要分三个 clean_ 方法？
    每个方法只负责一个字段，报错信息能挂到对应输入框下面，
    用户一眼知道是哪一格填错了，而不是笼统一句"数据有误"。
    """

    class Meta:
        model = models.Employee
        # 8 个业务字段全部暴露给页面；id 是自增主键，不用出现在表单里
        fields = ["name", "age", "gender", "account", "entry_time", "phone", "depart", "avatar"]
        # 原生 HTML5 日期选择器，比手输 "2024/1/1" 再解析更稳
        widgets = {
            "entry_time": forms.DateInput(attrs={"type": "date"}),
        }

    def clean_name(self):
        """姓名长度 2~32：拦住空串、单个字符和超长输入。"""
        name = self.cleaned_data.get("name")
        if len(name) < 2 or len(name) > 32:
            raise forms.ValidationError("姓名长度需在 2~32 个字符之间")
        return name

    def clean_age(self):
        """年龄 16~65：低于 16 是童工，高于 65 已达退休年龄。"""
        age = self.cleaned_data.get("age")
        if age < 16 or age > 65:
            raise forms.ValidationError("年龄需在 16~65 之间")
        return age

    def clean_phone(self):
        """
        手机号两条校验：
        1. 格式：^1[3-9]\\d{9}$ —— 1 开头、第二位 3~9、后面 9 位数字，共 11 位。
        2. 唯一：数据库层面没加 unique=True，因为要在同一条校验里区分新增/编辑。

        为什么编辑要 exclude(pk=...)?
        编辑时这条记录自己就在库里，不排除自己的话，
        用户什么都不改直接保存会被判成"手机号重复"。
        这是任务书 4.2 阶段二特别强调的坑。
        """
        phone = self.cleaned_data.get("phone")
        if not re.match(r"^1[3-9]\d{9}$", phone):
            raise forms.ValidationError("手机号格式不正确")

        pk = self.instance.pk  # 新增时是 None，编辑时是当前记录主键
        exists = models.Employee.objects.filter(phone=phone).exclude(pk=pk).exists()
        if exists:
            raise forms.ValidationError("该手机号已被其他员工使用")
        return phone


class NoticeForm(BootStrapModelForm):
    """
    公告表单。

    只暴露 title / content / is_top 三个字段：
    user 由视图从 request.user 取（发布人不能让人随便填），
    create_time 由 auto_now_add 自动写。
    """

    class Meta:
        model = models.Notice
        # 只让用户填这三个；user 由视图从 request.user 取，create_time 由 auto_now_add 写
        fields = ["title", "content", "is_top"]


class TaskForm(BootStrapModelForm):
    """
    任务表单：专门服务于 AJAX 提交。

    和普通表单的区别不在表单本身，而在视图的处理方式：
    校验失败时不是重新渲染 HTML，而是把 form.errors 序列化成 JSON 返回，
    前端用 $("#err_" + 字段名) 回显。
    """

    class Meta:
        model = models.Task
        # 这四个字段与列表页表单里的 name 属性一一对应，少一个 serialize() 就会漏掉
        fields = ["level", "title", "detail", "leader"]

    def clean_title(self):
        """标题至少 2 个字符，防止只提交一个字的无效任务。"""
        title = self.cleaned_data.get("title")
        if len(title) < 2:
            raise forms.ValidationError("标题至少 2 个字符")
        return title
