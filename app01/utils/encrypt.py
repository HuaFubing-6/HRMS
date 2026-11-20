"""
密码加密（utils 五件套之一）
============================

★ 这里与教学模板**有意不同**，答辩可以主动讲这个取舍：

模板里写的是 md5(明文) 存库、登录时 md5(输入) 比对。本项目没有照抄，原因：
1. MD5 是"无盐快速哈希"，同一密码每次结果都一样，
   网上有现成彩虹表，几秒就能反查出常见密码；
2. Django 自带的 make_password 默认用 PBKDF2-SHA256：随机盐 + 上万次迭代，
   同一密码两次入库的哈希都不一样，被拖库也几乎无法反查；
3. 项目里"盖亚 / 123"的密码已经是 PBKDF2 哈希，改成 MD5 会导致现有账号全部登录失败。

结论：结构上保留"密码处理集中在一个文件"这个好习惯，
但内部换成更强的算法，而不是为了对齐模板去降级安全。

用法：
    user.password = hash_password("123")     # 新建用户时
    verify_password("123", user.password)    # 登录校验时
"""
from django.contrib.auth.hashers import check_password as _django_check
from django.contrib.auth.hashers import make_password as _django_make


def hash_password(raw_password):
    """把明文密码转成数据库里存的哈希串（自带随机盐，每次结果不同）。"""
    # 不指定 hasher，走 Django 的默认 PBKDF2-SHA256；
    # settings 里没有改 PASSWORD_HASHERS，所以这里就是全局统一的算法
    return _django_make(raw_password)


def verify_password(raw_password, encoded_password):
    """
    校验明文密码是否匹配库里的哈希串。

    为什么不用 == 直接比？
    因为哈希带随机盐，同一个密码两次生成的值不一样，只能由算法自己校验。
    """
    # 密码字段为空直接判失败：老数据或异常写入都可能留下空值，
    # 先拦一道比把 None 交给 check_password 更明确
    if not encoded_password:
        return False
    return _django_check(raw_password, encoded_password)
