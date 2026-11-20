r"""
T1 的"测试命令"：一条命令验证大模型调通
=====================================

用法：
    .\.venv\Scripts\python.exe manage.py ai_check
    .\.venv\Scripts\python.exe manage.py ai_check "用一句话介绍你自己"

为什么用 management command 而不是写个独立脚本：
    1. 它会自动加载 Django 配置，能直接读到 settings 里的 AI_* 配置；
    2. 在项目目录下 `manage.py xxx` 就能跑，不用配 PYTHONPATH；
    3. 答辩演示时"敲一条命令就出结果"，比自己找脚本路径利索。

这条命令也是 T1 的验收证据：
    输出里会打印 base_url、模型名、耗时、回答 —— 四项都对，就说明封装可用。
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from app01.utils.ai import LLMClient, LLMError


class Command(BaseCommand):
    help = "验证大模型配置与调用是否正常（T1）"

    def add_arguments(self, parser):
        parser.add_argument(
            "question",
            nargs="?",
            default="用一句话介绍你自己",
            help="要问模型的问题，默认“用一句话介绍你自己”",
        )

    def handle(self, *args, **options):
        question = options["question"]

        # ---- 1. 先看配置，不先发请求 ----
        # Key 只打印前 6 位 + 后 4 位，避免截图或日志把整把 Key 泄露出去
        key = settings.AI_API_KEY
        masked = (key[:6] + "…" + key[-4:]) if key else "（未配置）"
        self.stdout.write(f"BASE_URL : {settings.AI_BASE_URL}")
        self.stdout.write(f"MODEL    : {settings.AI_MODEL}")
        self.stdout.write(f"API_KEY  : {masked}")
        self.stdout.write(f"超时      : {settings.AI_TIMEOUT}s")

        if not LLMClient.available():
            self.stdout.write(self.style.ERROR(
                "未读取到 AI_API_KEY：请在项目根目录的 .env 里填写，或设置系统环境变量"
            ))
            return

        # ---- 2. 真正调用一次 ----
        self.stdout.write("-" * 50)
        self.stdout.write(f"提问：{question}")
        started = time.time()
        try:
            answer = LLMClient.chat(question, temperature=0.3, max_tokens=200)
        except LLMError as exc:
            # 失败也只打印中文提示，不打印堆栈 —— 这才是"友好报错"的示范
            self.stdout.write(self.style.ERROR(f"调用失败：{exc}"))
            return

        elapsed = time.time() - started
        self.stdout.write(self.style.SUCCESS(f"回答：{answer}"))
        self.stdout.write(self.style.SUCCESS(f"耗时：{elapsed:.2f}s（含网络往返）"))
