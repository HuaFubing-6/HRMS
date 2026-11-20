"""
app01 的应用配置
=================

Django 启动时会读这个文件来识别 app01 这个应用。

两个字段值得讲：
    verbose_name  —— 显示在 Django 后台（/admin/）左侧的应用名，
                     写"企业员工管理系统"比默认的"App01"正式；
    default_auto_field —— 自动主键统一用 BigAutoField（大整数），
                     避免以后数据量涨上去还要改主键类型、动全表。
"""
from django.apps import AppConfig


class App01Config(AppConfig):
    """app01 的应用配置类，Django 3.2 之后默认用它作为应用入口。"""

    default_auto_field = "django.db.models.BigAutoField"
    name = "app01"
    verbose_name = "企业员工管理系统"
