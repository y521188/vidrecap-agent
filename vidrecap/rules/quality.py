"""质量打分器：按清晰度 / 通顺度 / 完整度给一句话打分。

三块规则（都是可解释的，每次扣分都会写进 ``SentenceScore.reasons``）：

- **清晰度**：句首直接出现谓语（"介绍了…"）说明缺主语；指代词（他/这个/那个）
  堆多了就指不明白；
- **通顺度**：相邻字词重复、标点连用、长句中间没有停顿、句子过短或过长；
- **完整度**：结尾没有标点收尾（被截断）、以停顿标点结尾（话说一半）、
  看不出谓语（结构不成型）。

**完整度刻意不查"有没有覆盖原文的全部信息"**：概括本来就该丢细节，
用覆盖率当标准会误伤好句；补信息的活交给修正器。这也是 ``context`` 参数
在当前实现里不参与判断的原因（保留它是为了对齐插座，模型档实现会用它）。

本层是纯判断：不调模型、不读时钟、不用随机（由 tests/test_layering.py 强制）。
所有词表与扣分权重都是"标尺"，可按业务替换；评分模型与阈值配置在数据层。
"""

from __future__ import annotations

import re

from vidrecap.data.api import QualityConfig, SentenceScore

# --- 标尺：词表 ---

# 句首直接出现谓语，说明这句话缺主语
SUBJECT_LESS_PREFIXES: tuple[str, ...] = (
    "介绍了",
    "分析了",
    "回顾了",
    "质疑了",
    "总结了",
    "展望了",
    "复盘了",
    "说明了",
    "提出了",
    "强调了",
    "指出了",
    "讲述了",
    "讨论了",
    "提到了",
    "认为",
    "表示",
    "指出",
    "强调",
    "建议",
    "呼吁",
    "透露",
    "报道",
)

# 指代词：堆多了就"指不明白"。
# 负向断言 ``(?<!其)`` 是为了放过"其他"这类词——"他"出现在里面不算指代。
PRONOUN_PATTERN = re.compile(
    r"(?<!其)(?:他们|她们|它们|这个|那个|这些|那些|他|她|它)"
)

# 判断句子"有没有谓语"用的动词表。
# 这一条是弱信号（只扣一点分），宁可放宽也别误伤好句，所以常见动词尽量收全。
PREDICATE_VERBS: tuple[str, ...] = (
    # 本业务场景（节目/会议转写）最常出现的
    "分析",
    "回顾",
    "介绍",
    "质疑",
    "总结",
    "展望",
    "复盘",
    "说明",
    "提出",
    "强调",
    "指出",
    "讲述",
    "讨论",
    "提到",
    "认为",
    "表示",
    "建议",
    "呼吁",
    "透露",
    "报道",
    "给出",
    "结合",
    # 通用高频动词
    "说",
    "讲",
    "谈",
    "问",
    "答",
    "看",
    "听",
    "做",
    "用",
    "去",
    "来",
    "发生",
    "出现",
    "发布",
    "宣布",
    "决定",
    "完成",
    "开始",
    "结束",
    "增加",
    "减少",
    "提升",
    "下降",
    "变化",
    "调整",
    "设立",
    "成立",
    "举行",
    "举办",
    "参加",
    "参与",
    "拍摄",
    "播放",
    "观看",
    "采访",
    "回应",
    "计划",
    "争取",
    "需要",
    "包括",
    "属于",
    "成为",
    "进行",
    "是",
    "有",
    "在",
)

TERMINAL_PUNCTUATIONS = "。！？!?…"
HALF_STOP_PUNCTUATIONS = "，、；,;：:"
PAUSE_PUNCTUATIONS = "，、；"

# --- 标尺：扣分与阈值 ---

_PENALTY_SUBJECT_LESS = 0.60
_PENALTY_PRONOUN_MAX = 0.55
_PRONOUN_DENSITY_LIMIT = 0.08
_PRONOUN_DENSITY_FACTOR = 3.5

_PENALTY_REPEAT_WORD = 0.60
_PENALTY_REPEAT_FUNCTION_CHAR = 0.55
_PENALTY_CONSECUTIVE_PUNCTUATION = 0.55
_PENALTY_RUN_ON_SEVERE = 0.55
_PENALTY_RUN_ON_MILD = 0.25
_PENALTY_FRAGMENT = 0.55
_PENALTY_TOO_LONG = 0.20

_PENALTY_TRUNCATED = 0.55
_PENALTY_HALF_STOP_ENDING = 0.55
_PENALTY_NO_PREDICATE = 0.30

FRAGMENT_MAX_CHARS = 6
RUN_ON_MIN_CHARS = 25
RUN_ON_SEVERE_CHARS = 40
LONG_SENTENCE_MIN_CHARS = 80

# 判定口径（重要，改规则前先读这段）：
# **硬缺陷**——缺主语、指代过密、相邻词重复、虚词重复、标点连用、
# 被截断、话说一半、碎片、严重连读——扣分都超过 0.5，也就是说
# 单独命中一条就足以让所在分项跌破下限、触发一票否决。
# **轻扣**——句子稍长、略短、看不出谓语、轻度连读——只做辅助信号，
# 单独出现不该把一句还算通顺的话打成不合格。
# 判断依据：三个指标是加权平均（权重都小于 1），单条扣分若不到 0.5，
# 加权后根本拉不下总分，那条规则就等于没有闸门作用。

SEVERE_METRIC_FLOOR = 0.5
"""单项严重不合格的下限：任一指标低于它，整句判为需要修正（一票否决）。

为什么需要它：三个指标是加权平均（清晰度 0.5 / 通顺度 0.3 / 完整度 0.2），
通顺度全崩也只能把总分拉到 0.7、完整度全崩只能拉到 0.8，都卡在阈值上而
"侥幸通过"。加一道"任何一项严重不合格就整句不合格"的闸门，
才符合"逐条字幕质检"的业务意图。
"""

_WORD_REPEAT_PATTERN = re.compile(r"([\u4e00-\u9fff]{2})\1")
_FUNCTION_CHAR_REPEAT_PATTERN = re.compile(r"([了的是在和])\1")
# 缺陷型连用标点：逗号顿号连排、停顿标点挨着句末标点、连续句号。
# 不含「！！」「？？」——重复感叹或疑问是强调，不是缺陷。
_CONSECUTIVE_PUNCTUATION_PATTERN = re.compile(
    r"[，、；：]{2,}|[，、；：][。！？]|[。！？][，、；：]|。{2,}"
)
_PAUSE_PATTERN = re.compile(f"[{PAUSE_PUNCTUATIONS}]")


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


class HeuristicScorer:
    """启发式打分器：零依赖、确定性、可离线复现。

    形状对齐外部层 QualityScorer 插座。真实模型的打分器将来放进
    external/adapters/，在同一套考卷上比分数——那是"对比报告"，不进 CI 门槛。
    """

    def __init__(self, config: QualityConfig | None = None) -> None:
        self.config = config or QualityConfig()

    async def score(self, sentence: str, context: str) -> SentenceScore:
        """给一句话打分：三个分项各 0~1，按权重加权得总分。

        异步只是为了对齐插座形状（模型档实现要 await 线程池），
        这里全是同步纯计算，不引入任何等待。
        """
        clarity, clarity_reasons = self._clarity(sentence)
        fluency, fluency_reasons = self._fluency(sentence)
        completeness, completeness_reasons = self._completeness(sentence)

        cfg = self.config
        total = (
            clarity * cfg.clarity_weight
            + fluency * cfg.fluency_weight
            + completeness * cfg.completeness_weight
        )
        return SentenceScore(
            sentence=sentence,
            clarity=clarity,
            fluency=fluency,
            completeness=completeness,
            total=_clamp(total),
            reasons=[*clarity_reasons, *fluency_reasons, *completeness_reasons],
        )

    # --- 清晰度 ---

    def _clarity(self, sentence: str) -> tuple[float, list[str]]:
        score = 1.0
        reasons: list[str] = []

        if sentence.startswith(SUBJECT_LESS_PREFIXES):
            score -= _PENALTY_SUBJECT_LESS
            reasons.append("句首缺主语：不知道是谁做的")

        pronoun_chars = sum(match.end() - match.start() for match in PRONOUN_PATTERN.finditer(sentence))
        if sentence and pronoun_chars / len(sentence) > _PRONOUN_DENSITY_LIMIT:
            density = pronoun_chars / len(sentence)
            score -= min(_PENALTY_PRONOUN_MAX, density * _PRONOUN_DENSITY_FACTOR)
            reasons.append("指代词过多（他/这个/那个），指不明白说的是谁或哪件事")

        return _clamp(score), reasons

    # --- 通顺度 ---

    def _fluency(self, sentence: str) -> tuple[float, list[str]]:
        score = 1.0
        reasons: list[str] = []

        if _WORD_REPEAT_PATTERN.search(sentence):
            score -= _PENALTY_REPEAT_WORD
            reasons.append("相邻字词重复（如「介绍介绍了」）")
        elif _FUNCTION_CHAR_REPEAT_PATTERN.search(sentence):
            score -= _PENALTY_REPEAT_FUNCTION_CHAR
            reasons.append("虚词重复（了了、的的）")

        if _CONSECUTIVE_PUNCTUATION_PATTERN.search(sentence):
            score -= _PENALTY_CONSECUTIVE_PUNCTUATION
            reasons.append("标点连用")

        if len(sentence) > RUN_ON_SEVERE_CHARS and not _PAUSE_PATTERN.search(sentence):
            score -= _PENALTY_RUN_ON_SEVERE
            reasons.append("严重连读：几十个字中间没有任何停顿标点")
        elif len(sentence) > RUN_ON_MIN_CHARS and not _PAUSE_PATTERN.search(sentence):
            score -= _PENALTY_RUN_ON_MILD
            reasons.append("长句中间没有停顿标点")

        if len(sentence) < FRAGMENT_MAX_CHARS:
            score -= _PENALTY_FRAGMENT
            reasons.append("碎片：字数太少，不成句子")
        elif len(sentence) > LONG_SENTENCE_MIN_CHARS:
            score -= _PENALTY_TOO_LONG
            reasons.append("句子过长，一句里塞了太多内容")

        return _clamp(score), reasons

    # --- 完整度 ---

    def _completeness(self, sentence: str) -> tuple[float, list[str]]:
        score = 1.0
        reasons: list[str] = []
        stripped = sentence.strip()

        if not stripped:
            return 0.0, ["空句"]

        if not stripped.endswith(tuple(TERMINAL_PUNCTUATIONS)):
            if stripped.endswith(tuple(HALF_STOP_PUNCTUATIONS)):
                score -= _PENALTY_HALF_STOP_ENDING
                reasons.append("话说一半就断了（以停顿标点结尾）")
            else:
                score -= _PENALTY_TRUNCATED
                reasons.append("句子被截断：结尾没有标点收尾")

        if len(stripped) >= 8 and not any(verb in stripped for verb in PREDICATE_VERBS):
            score -= _PENALTY_NO_PREDICATE
            reasons.append("看不出谓语，句子结构不成型")

        return _clamp(score), reasons


def unacceptable_reason(
    score: SentenceScore, config: QualityConfig | None = None
) -> str | None:
    """不达标时给出一句原因，达标返回 None。

    两条标准，缺一不可：

    1. 加权总分达到阈值；
    2. 三个分项没有一项低于 :data:`SEVERE_METRIC_FLOOR`
       （一票否决，见该常量的说明）。

    规划层用它挑出要修哪几句，并把原因写进修正计划；评测用它统计准确率，
    这样"线上判的"和"考卷量的"是同一个标准。
    """
    cfg = config or QualityConfig()

    if score.total < cfg.threshold:
        return f"总分 {score.total:.2f} 低于阈值 {cfg.threshold:.2f}"

    weakest = min(
        ("清晰度", score.clarity),
        ("通顺度", score.fluency),
        ("完整度", score.completeness),
        key=lambda item: item[1],
    )
    if weakest[1] < SEVERE_METRIC_FLOOR:
        return f"{weakest[0]}严重不合格（{weakest[1]:.2f} < {SEVERE_METRIC_FLOOR}）"

    return None


def is_acceptable(score: SentenceScore, config: QualityConfig | None = None) -> bool:
    """这句话是否达标（达标 = 不需要修正）。"""
    return unacceptable_reason(score, config) is None
