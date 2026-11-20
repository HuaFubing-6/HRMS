"""
图片验证码（T4 的一部分）
==========================

思路：用 Pillow 现画一张图 → 把 4 位答案写进 session → 登录时比对。

安全设计：
- 答案只存在服务端 session，图片里只有像素，前端读不到文本；
- 每次请求重新生成，旧答案被覆盖，防止重复使用同一个验证码。

可读性设计（改过一版，原因是投影上看不清）：
1. 背景取浅色（215~255），字符取深色（20~110）。
   早期版本背景和字符都用 0~200 随机，经常撞成同一色系，绿底绿字糊成一团；
   把明度拉开之后，一眼就能认出来。
2. 去掉整体 BLUR。模糊确实能干扰 OCR，但人眼也跟着糊了。
   现在改成"浅色噪点 + 2 条浅灰干扰线"，机器仍不好识别，人眼不受影响。
3. 字号 34、画布 150×48。原来 24px 字配 120×40，投影到教室屏幕上基本看不清。
4. 字符集去掉 0/O/1/I/L，避免"看着是 0 其实是 O"这种输对了还报错的坑。

答辩可讲点（这个文件是"改过一版才清楚"的最好素材）：
  1. 答案只存 session —— 页面上只有像素，前端读不到文本，绕不过
  2. 明度拉开 —— 背景 215~255、字符 20~110，不再撞成同一色系
  3. 去掉整体模糊 —— 改成浅色噪点 + 2 条浅灰干扰线，机器难识别、人眼不受影响
  4. 字号 34 / 画布 150×48 —— 原版 24px 配 120×40，投影到教室根本看不清
  5. 画图和返回响应拆开 —— utils/check_code.py 和视图共用同一套画法
"""
import random
from io import BytesIO

from django.http import HttpResponse
from PIL import Image, ImageDraw, ImageFont

# 去掉易混字符：0 与 O、1 与 I/L
CHARS = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

# 画布尺寸（比原来大一档，投影和缩小显示都还清楚）
WIDTH, HEIGHT = 150, 48
FONT_SIZE = 34


def _bg_color():
    """浅色背景：三个通道都在 215~255，保证是低饱和的浅色。"""
    return tuple(random.randint(215, 255) for _ in range(3))


def _fg_color():
    """深色字符：三个通道都在 20~110，与背景形成足够对比度。"""
    return tuple(random.randint(20, 110) for _ in range(3))


def _noise_color():
    """噪点/干扰线用中间调浅灰，只增加纹理，不抢字符的视觉。"""
    return tuple(random.randint(165, 205) for _ in range(3))


def _load_font(size):
    """优先用系统 arial，取不到就退回内置默认字体，避免在别的机器上直接崩。"""
    for name in ("arial.ttf", "Arial.ttf", "calibri.ttf"):
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_captcha(width=WIDTH, height=HEIGHT, char_length=4):
    """
    纯绘图函数：只负责画一张验证码图，不碰 request / session / HttpResponse。

    为什么把"画图"和"返回响应"拆开？
    因为 utils/check_code.py 需要拿到 (图片, 答案) 两样东西自己处理，
    视图那边又要直接返回 HttpResponse。拆开之后两边共用同一套画法，
    不会出现"两个验证码模块画风不一样"的情况。

    :return: (PIL.Image 对象, 答案字符串)
    """
    # 1. 画布：浅色随机底
    image = Image.new("RGB", (width, height), _bg_color())
    draw = ImageDraw.Draw(image)

    # 2. 噪点：60 个浅灰像素点，制造纹理但不遮字
    for _ in range(60):
        draw.point(
            (random.randint(0, width - 1), random.randint(0, height - 1)),
            fill=_noise_color(),
        )

    # 3. 生成答案
    code = "".join(random.choices(CHARS, k=char_length))

    # 4. 逐字绘制：把画布按字符数等分成若干格，每个字落在格子中间，
    #    再叠一点随机抖动。抖动是为了让字符不排成一条死板的直线（机器更难切分），
    #    幅度控制在 ±3px，既不影响人眼扫读，也不会让字叠在一起。
    font = _load_font(FONT_SIZE)
    unit = width / char_length            # 每个字占的横向宽度
    for i, ch in enumerate(code):
        center = unit * (i + 0.5)         # 该格子的中心点
        x = int(center) - 12 + random.randint(-2, 2)   # 减 12 是把字符往左挪半个字宽
        y = 4 + random.randint(-3, 3)
        draw.text((x, y), ch, font=font, fill=_fg_color())

    # 5. 干扰线：只画 2 条、颜色浅灰，划过字符但不影响辨认
    for _ in range(2):
        draw.line(
            [
                (random.randint(0, width), random.randint(0, height)),
                (random.randint(0, width), random.randint(0, height)),
            ],
            fill=_noise_color(),
            width=1,
        )

    return image, code


def generate_captcha(request):
    """
    生成验证码图片，并把答案写入 session["captcha"]。

    返回 HttpResponse(image/png)，模板里直接当图片地址用：<img src="/captcha/">
    """
    image, code = draw_captcha()

    # 关键一步：答案存 session（服务端），页面上只有像素，前端读不到文本
    request.session["captcha"] = code

    # 输出到内存缓冲区，不落磁盘
    buf = BytesIO()
    image.save(buf, "png", optimize=True)
    return HttpResponse(buf.getvalue(), content_type="image/png")
