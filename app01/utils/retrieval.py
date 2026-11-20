"""
制度检索（T3 的"最小可用 RAG"第一步）
=====================================

流程：用户问题 → 抽检索词 → SQL 模糊匹配 → 命中的制度按匹配度排序 → 拼成上下文。

为什么不用向量检索：
  知识库只有 8 条制度，关键词匹配足够；向量库要额外服务 + embedding 费用，
  课设规模属于"为了用技术而用技术"。
  答辩说法：检索方式与数据规模要匹配，8 条数据上向量库是过度设计。

一个真实坑：
  用户问"迟到扣多少钱"，制度标题是"考勤管理办法"，正文里才出现"迟到"。
  只按整句去 icontains 会搜不到 —— 所以这里把问题切成词组 + 二字片段再匹配。
"""
import re

from django.db.models import Q

from app01 import models

# 汉语停用词：这些词几乎每条制度里都有，拿来做检索词只会把结果泛化
STOP_WORDS = {
    "公司", "我们", "请问", "怎么", "如何", "什么", "多少", "一下", "可以", "是否",
    "的话", "那个", "这个", "以及", "还有", "需要", "应该", "能不能", "有没有",
    "的", "了", "吗", "呢", "啊", "是", "在", "有", "和", "与", "就", "都",
}

# 标点与空白：检索前先清掉，避免"迟到，"这种词匹配不上
# 标点与空白：检索前先清掉，避免"迟到，"这种词匹配不上。
# 这里用 re.escape 把标点整体转义，避免在字符类里手写转义出错
_LITERAL = (
    "，。！？、；：\u201c\u201d\u2018\u2019（）《》〈〉·"
    ",.;:!?()[]{}<>-—_/\\|@#$%^&*+=~`\"'"
)
_PUNCT = re.compile("[" + re.escape(_LITERAL) + r"\s\u3000]+")


def extract_terms(question, max_terms=6):
    """
    从问题里抽检索词。

    规则（简单但够用）：
      1. 去掉标点，按空白切开；
      2. 丢掉停用词和单字；
      3. 对每个剩下的片段，再补它的二字片段（"迟到扣钱" → "迟到""到扣""扣钱"）；
      4. 最多取 6 个，避免 OR 条件太多把全库都查出来。
    """
    cleaned = _PUNCT.sub(" ", question)
    chunks = [c for c in cleaned.split(" ") if c]

    terms = []
    for chunk in chunks:
        if chunk in STOP_WORDS:
            continue
        if len(chunk) > 1:
            terms.append(chunk)
        # 二字片段：中文没有分词器时，用滑动窗口近似
        if len(chunk) > 2:
            for i in range(len(chunk) - 1):
                piece = chunk[i:i + 2]
                if piece not in STOP_WORDS:
                    terms.append(piece)

    # 去重 + 截断，保序
    seen = set()
    result = []
    for term in terms:
        if term not in seen:
            seen.add(term)
            result.append(term)
    return result[:max_terms]


def search(question, limit=5):
    """
    检索相关制度。

    返回：
        (items, terms)
        items —— Knowledge 对象列表，按"命中词数"降序；
        terms —— 实际使用的检索词，页面可以展示出来，便于解释"为什么答这个"。

    无命中时返回空列表 —— 调用方据此直接回答"不知道"，不再消耗模型额度。
    """
    terms = extract_terms(question)
    if not terms:
        return [], []

    condition = Q()
    for term in terms:
        condition |= (
            Q(title__icontains=term)
            | Q(content__icontains=term)
            | Q(keywords__icontains=term)
        )

    candidates = list(models.Knowledge.objects.filter(is_active=True).filter(condition))
    if not candidates:
        return [], terms

    def hit_score(k):
        """命中词数越多越相关；标题命中额外加权，因为标题最能代表主题。"""
        text = f"{k.title} {k.content} {k.keywords}"
        score = sum(1 for t in terms if t.lower() in text.lower())
        score += sum(2 for t in terms if t.lower() in k.title.lower())
        return score

    candidates.sort(key=hit_score, reverse=True)
    # 只保留"相对相关"的条目：命中数不到最高分一半的，属于顺带匹配上的噪音
    # （例如问"迟到扣钱"，会顺带命中含"钱"字的保密制度 —— 展示出来会让依据显得不准）
    best = hit_score(candidates[0])
    kept = [k for k in candidates if hit_score(k) >= max(1, best * 0.5)]
    return kept[:limit], terms


def build_context(items):
    """
    把命中的制度拼成提示词里的【资料】段。

    每条前面标书名号标题，好处有两个：
      1. 模型能引用标题，答案末尾的"依据：《xx》"才有着落；
      2. 用户核对时可以一眼看出答案出自哪条制度。
    """
    parts = []
    for k in items:
        parts.append(f"《{k.title}》（{k.get_category_display()}）\n{k.content}")
    return "\n\n".join(parts)
