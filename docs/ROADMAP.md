# 开发计划（路线图）

> 本文件是**规则层**资产，描述接下来几次提交的目标、产出、验收标准与"不做什么"。
> 分层规矩见 [AGENTS.md](../AGENTS.md)，架构讲解见 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 总原则

1. **考卷先行**：先定义"什么算好句子"的评测集，再写实现——标准先立，实现围绕标准写。
2. **每次提交自带验收**：不写"以后再补测试"，测试与实现同一次提交落地。
3. **行为不变的重构要有证据**：不改变行为的提交，必须证明 `vidrecap demo` 输出与改前逐字节一致。
4. **骨架已就位**：函数签名与契约已写好，后续提交只填实现、补测试，不再改结构。

## 依赖关系

```
提交1（打分器）──→ 提交2（考卷+跑分）──┐
        │                              ├──→ 提交4（注毒+端到端）
        └────────→ 提交3（语义修正）────┘
```

提交 2 与 3 都依赖提交 1，彼此独立，可以调换顺序；提交 4 依赖 3。

---

## 提交 1：规则层三指标打分器

**目标**：能对一句话给出可解释的质量分——这是后续"低于阈值就修"的判据。

**产出文件**

| 文件 | 动作 |
|---|---|
| `vidrecap/rules/quality.py` | 填实现：三指标规则 + 加权总分 + 扣分原因 |
| `vidrecap/rules/api/__init__.py` | 已挂出，无需改动 |
| `tests/test_quality.py` | 新建：每指标正反例、加权总分、阈值行为 |

**三指标规则设计**（每条规则都是可解释的，扣分要写进 `reasons`）

| 指标 | 规则 | 扣分 |
|---|---|---|
| 清晰度 | 句首缺主语（以谓语动词开头，如"介绍了…"） | 重扣 |
| | 指代词过密（他/她/它/这个/那个 占比过高） | 按比例扣 |
| 通顺度 | 相邻字词重复（"介绍介绍了"） | 重扣 |
| | 标点异常（句中出现连续标点、整句无标点且过长） | 中扣 |
| | 句长异常（过短如碎片、过长如未断句连读） | 轻扣 |
| 完整度 | 句末无终止标点（截断信号） | 重扣 |
| | 结构不成型（有主语无谓语或有谓语无宾语） | 中扣 |

**刻意不做**：完整度**不查**"是否覆盖原文全部信息"——概括本来就该丢细节，
用覆盖率当标准会误伤好句；补信息的活交给修正器。

**测试清单**：三类病句各自出现时对应分项明显低；好句三项都高且总分过阈值；
加权公式正确（权重改一下总分跟着变）；同一输入两次调用结果一致（纯函数）；
`isinstance(HeuristicScorer(), QualityScorer)` 通过（形状对齐插座）。

**验收**：新增测试全绿；CI 全绿；分层检查（纯判断层）不红。

**不做什么**：不碰服务层、不改调度器、不做修正——这一步只产出"判断"。

---

## 提交 2：A 层考卷 + 跑分器 + `vidrecap eval`

**目标**：给打分器一张考卷和一份成绩单，并让成绩单进 CI 当门槛。

**产出文件**

| 文件 | 动作 |
|---|---|
| `vidrecap/monitor/evals/cases/scorer_v1.jsonl` | 新建：约 50 条手写考卷 |
| `vidrecap/monitor/evals/loader.py` | 填实现：JSONL 加载（容忍 CRLF） |
| `vidrecap/monitor/evals/metrics.py` | 填实现：阈值准确率、排序正确率、分类别准确率、错题清单 |
| `vidrecap/monitor/evals/runner.py` | 填实现：`run_scorer_eval` / `run_eval` |
| `vidrecap/user/cli.py` | 新增 `vidrecap eval` 子命令：打印成绩单 |
| `vidrecap/rules/baselines.py` | 按首次实测校准门槛数值 |
| `tests/test_evals.py` | 新建：加载器往返、指标算法（玩具数据）、冒烟、门槛 |
| `README.md` | 发榜：公布启发式打分器的基线成绩 |

**考卷配比**（详见 `monitor/evals/cases/README.md`）
清晰度 8 坏 + 4 好；通顺度 8 坏 + 4 好；完整度 8 坏 + 4 好；混合 5 坏；好句对照 8 好。

**指标定义**

- **阈值准确率** = 判"过/不过"与标准答案一致条数 ÷ 总条数；
- **排序正确率** = 所有（好句, 坏句）配对中"好句分更高"的比例（比准确率更细）；
- **分类别准确率** = 按 `category` 拆开的阈值准确率（看在哪类病句上翻车）。

**基线门槛**：先按 `rules/baselines.py` 的初值（准确率 ≥ 0.75、排序 ≥ 0.90），
首次跑完按实测结果**只上调不下调**地校准，并写进 README 发榜。

**测试清单**：加载器能读内置考卷且条数、类别配比符合预期；指标函数用玩具数据
逐条验算（含"全判过"这种退化情形）；跑分器对桩打分器给出预期分数；
门槛测试：启发式打分器必须达到 `rules/baselines.py` 的下限。

**验收**：`vidrecap eval` 能打印成绩单；门槛测试全绿；CI 全绿。

**不做什么**：不写修正器；不接真实模型（留给路线图）。

---

## 提交 3：语义修正（规划 / 服务 / 规则 / 数据 联动）

**目标**：低于阈值的句子被修正，且**绝不引入原文没有的事实**。

**产出文件**

| 文件 | 动作 |
|---|---|
| `vidrecap/planning/sentences.py` | 填实现：共享断句纯函数 |
| `vidrecap/planning/corrections.py` | 填实现：`plan_corrections`（挑低于阈值的句子） |
| `vidrecap/rules/guardrail.py` | 填实现：实体抽取 + 忠实性校验 |
| `vidrecap/service/corrector.py` | 填实现：拆句 → 打分 → 按计划修正 → 重打分 → 护栏 → 回退 |
| `vidrecap/service/orchestrator.py` | 接入：`scorer` / `corrector` 可选参数（默认 None） |
| `vidrecap/data/models.py` | 补 `PartialSummary.avg_quality` / `corrected_count`、`RecapStats` 汇总字段 |
| `vidrecap/monitor/evals/cases/corrector_v1.jsonl` | 新建：约 15 条修正考卷 |
| `vidrecap/monitor/evals/*` | 填实现：修正器指标与跑分器 |
| `tests/test_corrector.py` | 新建：护栏拦截、回退、好句不动 |

**执行流程**（服务层只执行、不发明策略）

1. 规划层 `split_sentences` 拆句；
2. 规则层打分器逐句打分；
3. 规划层 `plan_corrections` 给出"修哪几句"的计划；
4. 服务层按计划调修正器（外部层插座），修正结果重打分；
5. 规则层护栏校验：**有原文外实体，或分数没变好 → 回退原句**；
6. 重组摘要，记录平均分与修正条数。

**回退优先原则**：宁可保留原样，也不接受"改出新事实"或"越改越糟"。
这条决定了修正器的成绩单里"无幻觉率"和"不倒退率"必须是满分。

**测试清单**：护栏能抓出凭空捏造的实体、放过正常改写；好句送进去原样返回；
修正结果变差时回退；修正器抛异常时不炸整条流水线（降级保留原句）；
**不传 scorer/corrector 时行为与提交前逐字节一致**（demo 输出对比）。

**验收**：修正成功率 ≥ 0.80、无幻觉率 = 100%、不倒退率 = 100%（`rules/baselines.py`）；
默认关闭修正时，`vidrecap demo` 输出与提交前逐字节一致。

**不做什么**：不改前端提示词、不接真实模型、不动压缩与分片逻辑。

---

## 提交 4：demo 注毒 + 端到端评测 + 命令行开关

**目标**：让整条链路在"有烂句"的情况下也能被验证，且保持确定性。

**产出文件**

| 文件 | 动作 |
|---|---|
| `vidrecap/external/adapters/demo/source.py` | 新增 `poison_rate` 参数：确定性注毒 |
| `vidrecap/external/adapters/demo/corrector.py` | 填实现：抽取式确定性修正器 |
| `vidrecap/monitor/evals/scenarios.py` | 新建：端到端场景与属性断言 |
| `vidrecap/user/cli.py` | 新增 `--poison` / `--no-correct` / `--threshold` / `--weights` |
| `README.md`、`docs/ARCHITECTURE.md`、`AGENTS.md` | 更新架构图、状态与清单 |

**注毒设计**（按句子序号确定性选择，不用随机）

| 手法 | 效果 |
|---|---|
| 丢主语 | 考验清晰度 |
| 动词重复 | 考验通顺度 |
| 截断（去句末标点并砍半） | 考验完整度 |

**端到端断言**

- 注毒开启时 `corrected_count > 0`，关闭时 `= 0`；
- 最终概括里的实体全部来自原文（无幻觉）；
- 修正后平均分高于修正前；
- **同一输入跑两次，输出逐字节一致**（确定性兜底）。

**验收**：端到端测试全绿；`vidrecap demo` 在注毒+修正下仍两次一致；
既有 74 个测试不回归。

**不做什么**：不做真实模型接入、不做失败重试。

---

## 交付之后的路线图

| 功能 | 落哪层 | 依赖 |
|---|---|---|
| 真实大模型适配器（OpenAI 兼容） | 外部层 `external/adapters/openai/` | 同一套考卷上对比分数 |
| SRT / ASR 媒体源适配器 | 外部层 `external/adapters/srt/` | 需要真实数据做 case study |
| 分片级失败重试与降级 | 服务层 | 与 80% 增量摘要协同 |
| 任务持久化、断点续跑 | 数据层 | 引入存储后端 |
| gRPC / HTTP 服务化 | 用户层 | 复用 `run_recap` 入口 |
| 监控指标导出与告警 | 监控层 | 结构化日志先行 |

每加一项，先确认它属于哪层、是否需要新插座，再补 `AGENTS.md` 的归属表与文件清单。

---

## 常用验收命令

```bash
# 全部测试（含分层硬检查）
.venv/Scripts/python.exe -m pytest tests/ -q

# 离线 demo（需要证明"行为不变"时与改前输出逐字节对比）
.venv/Scripts/python.exe -m vidrecap demo > /tmp/after.txt
diff /tmp/baseline.txt /tmp/after.txt

# 跑评测集（提交 2 之后可用）
.venv/Scripts/python.exe -m vidrecap eval
```
