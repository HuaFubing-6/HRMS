"""
图片验证码（utils 五件套之一）
==============================

为什么叫 check_code.py 而不叫 captcha.py？
—— 教学模板（EMS 脚手架）里这个文件就叫 check_code.py，
   统一命名后，别人拿到项目能直接对上模板的结构。
   真正的绘制逻辑在 utils/captcha.py（那边写得更清楚：浅色底 + 深色字 + 噪点），
   这里只做一层统一入口，避免同样的画法维护两份。

对外只暴露一个函数：
    check_code(width=150, height=48, char_length=4) -> (PIL.Image, "ABCD")

和模板的差别（都是为了投影可读性，答辩可以讲）：
- 模板：120×30、5 个字符、整体 EDGE_ENHANCE_MORE 滤镜 → 教室投影上糊成一团；
- 本项目：150×48、4 个字符、字号 34、去掉模糊滤镜 → 远处也能认出来。
"""
from app01.utils.captcha import draw_captcha


def check_code(width=150, height=48, char_length=4):
    """生成验证码：返回 (图片对象, 答案字符串)，答案由调用方决定存哪里。"""
    # 这里只做转调，真正的绘制逻辑在 utils/captcha.py；
    # 以后换画法（比如改字号、换干扰方式）只需要改那一处，两个入口不会各写一套
    return draw_captcha(width=width, height=height, char_length=char_length)


def check_code_response(request):
    """
    一步到位版：画图 + 把答案写进 session + 返回 HttpResponse。

    视图里如果有别的入口需要验证码，直接用这个，不用再自己拼 BytesIO。
    """
    from app01.utils.captcha import generate_captcha

    return generate_captcha(request)
