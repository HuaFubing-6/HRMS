r"""
AI 模块单元测试（不联网）
========================

为什么这些测试不真的调模型：
    1. 单元测试要快、要可重复 —— 每次跑测试都烧 API 额度不合适；
    2. 模型输出本身不稳定，拿它做断言会"今天过明天挂"；
    3. 真正需要验证的链路（真的能调通）由 `manage.py ai_check` 负责，
       两条线分工：一条测逻辑，一条测连通性。

运行：
    .\.venv\Scripts\python.exe manage.py test app01.tests_ai -v 2
"""
import json
from unittest import mock

from django.test import RequestFactory, TestCase
from django.utils import timezone

from app01 import models
from app01.utils.ai import check_rate_limit, clean_input, mark_rate_used
from app01.utils.prompts import build_chat_messages, build_jd_prompt, build_qa_prompt
from app01.utils.retrieval import build_context, extract_terms, search
from app01.views import ai as ai_views


def as_json(response):
    """直接调用视图函数拿到的是 JsonResponse（没有 .json() 方法），这里统一解析。"""
    return json.loads(response.content.decode("utf-8"))


class CleanInputTests(TestCase):
    """T6：输入清洗"""

    def test_empty_rejected(self):
        self.assertEqual(clean_input(""), ("", "内容不能为空"))

    def test_whitespace_rejected(self):
        _, err = clean_input("   ")
        self.assertTrue(err)

    def test_single_char_rejected(self):
        _, err = clean_input("a")
        self.assertIn("至少 2 个字", err)

    def test_pure_symbol_rejected(self):
        _, err = clean_input("！！！？？")
        self.assertIn("需要包含文字或数字", err)

    def test_control_chars_removed(self):
        # \x07 是响铃字符，会污染日志；清洗后应消失
        text, err = clean_input("你\x07好")
        self.assertEqual(text, "你好")
        self.assertIsNone(err)

    def test_too_long_rejected(self):
        _, err = clean_input("啊" * 600)
        self.assertIn("过长", err)

    def test_normal_passes(self):
        text, err = clean_input("  迟到扣多少钱  ")
        self.assertEqual(text, "迟到扣多少钱")
        self.assertIsNone(err)


class FakedRequest:
    """限流函数只用到 session，这里用一个带 dict 的最小对象代替真实请求。"""

    def __init__(self):
        self.session = {}


class RateLimitTests(TestCase):
    """T6：会话限流"""

    def test_first_call_allowed(self):
        self.assertIsNone(check_rate_limit(FakedRequest()))

    def test_second_call_within_interval_blocked(self):
        req = FakedRequest()
        mark_rate_used(req)
        self.assertIn("过快", check_rate_limit(req))

    def test_daily_limit_blocked(self):
        from django.test import override_settings

        with override_settings(AI_DAILY_LIMIT=2):
            req = FakedRequest()
            mark_rate_used(req)
            mark_rate_used(req)
            self.assertIn("上限", check_rate_limit(req))

    def test_counter_resets_next_day(self):
        req = FakedRequest()
        req.session["ai_rate"] = {"day": "2000-01-01", "count": 999, "last": 0}
        # 跨天后应重新计数，而不是继续被昨天的次数挡住
        self.assertIsNone(check_rate_limit(req))


class RetrievalTests(TestCase):
    """T3：关键词检索"""

    @classmethod
    def setUpTestData(cls):
        cls.kaoqin = models.Knowledge.objects.create(
            title="考勤管理办法", category="attendance",
            keywords="打卡,迟到,早退",
            content="迟到一次罚款 50 元，早退一次罚款 50 元。",
        )
        cls.mimi = models.Knowledge.objects.create(
            title="信息安全与保密要求", category="security",
            keywords="密码,保密",
            content="密码长度不少于 8 位。",
        )

    def test_extract_terms_drops_punctuation(self):
        terms = extract_terms("迟到，扣多少钱？")
        self.assertNotIn("迟到，", terms)
        self.assertTrue(any("迟到" in t for t in terms))

    def test_extract_terms_limited(self):
        terms = extract_terms("一二三四五六七八九十甲乙丙丁戊己庚辛")
        self.assertLessEqual(len(terms), 6)

    def test_search_hits_relevant(self):
        items, terms = search("迟到一次扣多少钱")
        self.assertTrue(items)
        self.assertEqual(items[0].title, "考勤管理办法")
        self.assertIn("迟到", terms)

    def test_search_returns_empty_when_no_match(self):
        items, _ = search("公司的股票代码是多少")
        self.assertEqual(items, [])

    def test_irrelevant_item_dropped(self):
        # 保密制度与考勤问题无关，不应出现在依据列表里
        items, _ = search("迟到一次扣多少钱")
        titles = [k.title for k in items]
        self.assertNotIn("信息安全与保密要求", titles)

    def test_build_context_contains_title(self):
        context = build_context([self.kaoqin])
        self.assertIn("《考勤管理办法》", context)
        self.assertIn("罚款 50 元", context)


class PromptTests(TestCase):
    """提示词组装"""

    def test_jd_prompt_contains_title(self):
        prompt = build_jd_prompt("前端工程师", depart="技术部")
        self.assertIn("前端工程师", prompt)
        self.assertIn("技术部", prompt)
        self.assertIn("【岗位职责】", prompt)

    def test_qa_prompt_wraps_context(self):
        prompt = build_qa_prompt("迟到怎么罚", "《考勤》迟到罚 50")
        self.assertIn("【资料】", prompt)
        self.assertIn("【问题】", prompt)

    def test_chat_messages_trim_history(self):
        # 传入 10 轮历史，只应保留最近 6 轮（12 条）+ system + 本次提问
        history = []
        for i in range(10):
            history.append({"role": "user", "content": f"问题{i}"})
            history.append({"role": "assistant", "content": f"回答{i}"})
        messages = build_chat_messages("新问题", history)
        self.assertEqual(messages[0]["role"], "system")
        self.assertEqual(messages[-1]["content"], "新问题")
        self.assertLessEqual(len(messages), 1 + 12 + 1)
        self.assertNotIn("问题0", [m["content"] for m in messages])


class ViewLogicTests(TestCase):
    """视图层：成功/失败分支（模型调用被 mock 掉）"""

    @classmethod
    def setUpTestData(cls):
        cls.dept = models.Department.objects.create(title="技术部")
        cls.employee = models.Employee.objects.create(
            name="测试员工", age=28, entry_time=timezone.now().date(),
            phone="13800000000", depart=cls.dept,
        )
        cls.staff_role = models.Role.objects.create(title="普通员工")
        cls.staff = models.User.objects.create_user(
            username="staff1", password="123", role=cls.staff_role,
        )
        cls.staff.employee = cls.employee
        cls.staff.save()

    def _post(self, path_data):
        request = RequestFactory().post("/", path_data)
        request.session = {}
        return request

    def test_jd_generate_returns_json(self):
        request = self._post({"title": "Python 工程师"})
        with mock.patch.object(ai_views.LLMClient, "chat", return_value="【岗位职责】写代码"):
            response = ai_views.jd_generate(request)
        self.assertEqual(response.status_code, 200)
        payload = as_json(response)
        self.assertTrue(payload["status"])
        self.assertIn("岗位职责", payload["data"])

    def test_jd_generate_rejects_short_title(self):
        request = self._post({"title": "a"})
        response = ai_views.jd_generate(request)
        self.assertFalse(as_json(response)["status"])

    def test_qa_without_hit_skips_model(self):
        request = self._post({"question": "公司的股票代码是多少"})
        with mock.patch.object(ai_views.LLMClient, "chat") as mocked:
            response = ai_views.qa_ask(request)
            mocked.assert_not_called()
        self.assertEqual(as_json(response)["data"], "不知道")

    def test_qa_with_hit_calls_model(self):
        models.Knowledge.objects.create(
            title="考勤管理办法", category="attendance", keywords="迟到",
            content="迟到一次罚款 50 元。",
        )
        request = self._post({"question": "迟到扣多少钱"})
        with mock.patch.object(ai_views.LLMClient, "chat", return_value="罚款 50 元"):
            response = ai_views.qa_ask(request)
        payload = as_json(response)
        self.assertTrue(payload["status"])
        self.assertEqual(payload["sources"], ["考勤管理办法"])

    def test_comment_denied_for_other_employee(self):
        # 普通员工只能点评自己；换成别人的 employee_id 应被拒绝
        other = models.Employee.objects.create(
            name="别人", age=30, entry_time=timezone.now().date(),
            phone="13900000000", depart=self.dept,
        )
        request = self._post({"employee_id": other.pk, "month": timezone.now().strftime("%Y-%m")})
        request.user = self.staff
        response = ai_views.comment_generate(request)
        self.assertFalse(as_json(response)["status"])
        self.assertIn("没有权限", as_json(response)["msg"])

    def test_sse_frame_format(self):
        self.assertTrue(ai_views._sse({"delta": "你"}).startswith("data: "))
        self.assertTrue(ai_views._sse({"delta": "你"}).endswith("\n\n"))
