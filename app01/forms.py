"""
兼容层（别在这里写新表单）
==========================

所有表单已经按脚手架规范移到 app01/utils/form.py，
这里只做一次转发，目的是：老的 import 语句（from app01 import forms）
不用改，降低重构风险。

新代码请统一写：from app01.utils.form import XxxForm
"""
from app01.utils.form import DepartmentForm, EmployeeForm, NoticeForm, TaskForm  # noqa: F401
