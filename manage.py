#!/usr/bin/env python
"""
Django 命令行入口
==================

这个文件由 django-admin startproject 生成，一般不改动。

它的作用只有两件事：
    1. 把 hrms/settings.py 设为默认配置；
    2. 把命令行参数（runserver / migrate / check / test / 自定义命令）
       交给 Django 的 execute_from_command_line 去分发。

所以 `python manage.py init_data`、`python manage.py demo_data` 这些自定义命令，
都是从本文件进入、再由 app01/management/commands/ 下的同名文件处理。

【必须注意】命令要在 manage.py 所在目录执行，也就是 D:\\MIN\\qiyerenwu\\hrms。
在上一级目录（D:\\MIN\\qiyerenwu）执行会报
    can't open file 'D:\\MIN\\qiyerenwu\\manage.py': [Errno 2]
这是"当前目录里没有这个文件"，不是 Python 或 Django 装错了。
"""
import os
import sys


def main():
    """
    设置配置模块，然后把命令行参数交给 Django。

    用 setdefault 而不是直接赋值：这样外部可以用环境变量
    DJANGO_SETTINGS_MODULE 指定别的配置（例如部署时的生产配置），不会被写死。
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hrms.settings")
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "Couldn't import Django. Are you sure it's installed and "
            "available on your PYTHONPATH environment variable? Did you "
            "forget to activate a virtual environment?"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == "__main__":
    main()
