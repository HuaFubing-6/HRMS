"""
Django 启动时的兼容处理。

本机未安装 mysqlclient（Windows 下需编译，容易失败），
改用纯 Python 的 pymysql 作为 MySQL 驱动。
"""
import pymysql

pymysql.install_as_MySQLdb()
