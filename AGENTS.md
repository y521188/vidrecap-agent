# AGENTS.md — vidrecap-agent 项目规则

> 本文件是**规则层**的资产，也是所有后续 agent 与协作者的统一入口。
> **改架构必须同步改本文件**：第 8 节的受检清单会被 CI 检查（列了不存在的文件就会红），
> 完整讲解见 [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)。

---

## 1. 项目使命

把 3 小时级别的长视频（节目、会议、直播回放）切成带重叠缓冲区的分片并行摘要，再逐层收敛成全局概括。
核心引擎只认两个插座（`MediaSource` / `LLMClient`），不绑定任何厂商。

两条产品底线：

- **零 Key 可跑**：`python -m vidrecap demo` 不需要任何 API Key、不联网。
- **确定性**：demo 与评测集的输出必须可复现（跑两次逐字节一致），否则测试没有意义。

---

## 2. 先读这四条铁律

1. **跨层引用只走 api 窗口**：`from vidrecap.planning.api import plan_windows` ✅；
   `from vidrecap.planning.windows import ...` ❌（绕过窗口直闯内部，CI 会红）。
2. **规划层只规划、服务层只修改**：规划层产出计划（纯数据），服务层照计划执行；
   执行中发现情况变了，回去找规划层要下一步计划，**不许在服务层里内联发明策略**。
3. **可调参数的默认值只在 `data/models.py` 的 `PipelineConfig` / `QualityConfig` 声明一次**，
   其他地方只做覆盖，不许再抄一遍数字。
4. **新增功能先在第 4 节的归属表里找到自己的层，再动手写代码**。
5. **数据模型归属**：跨层共享的模型放数据层；只在本层内部流转的结构留本层
   （例如评测用例、成绩单住在 `monitor/evals/schemas.py`）。
6. **契约先行**：插座（Protocol）与数据模型可以先于实现落地；
   骨架函数体写 `raise NotImplementedError("待第 N 次提交实现：…")`，
   并在 [docs/ROADMAP.md](docs/ROADMAP.md) 里登记属于哪次提交。

---

## 3. 七层职责

| 层 | 一句话职责 | 目录 | 对外窗口 |
|---|---|---|---|
| 用户层 | 接单与交付：解析输入、组装依赖、展示结果 | `vidrecap/user/` | `user.api` |
| 服务层 | 照图纸施工：调度、并发、取内容、调模型、收统计 | `vidrecap/service/` | `service.api` |
| 规划层 | 只出主意：切窗、拆分、修哪些句子（纯函数） | `vidrecap/planning/` | `planning.api` |
| 规则层 | 标准与宪法：打分规则、阈值闸门、忠实性护栏、本文件 | `vidrecap/rules/` | `rules.api` |
| 数据层 | 数据长什么样：模型、计划对象、配置 | `vidrecap/data/` | `data.api` |
| 外部层 | 对外窗口：插座协议 + 具体适配器（含离线 demo） | `vidrecap/external/` | `external.api` |
| 监控层 | 质检与仪表盘：统计、评测跑分、基线门槛 | `vidrecap/monitor/` | `monitor.api` |

**一层一个文件夹**：每层独立成夹，夹里必须有一个 `api/` 窗口；代码不许躺在包根。
唯一的例外是 `vidrecap/__init__.py` 与 `vidrecap/__main__.py` 两个壳文件——
Python 与 `python -m vidrecap` 的约定要求它们必须在包根，所以它们只准放入口转发、不准放逻辑。
这条由 `tests/test_layering.py` 强制：新目录意味着新的一层，得先改本文件。

---

## 4. 功能归属表（新代码写哪层）

| 要做的功能 | 写到哪层 | 落点 |
|---|---|---|
| 命令行命令、参数、输出展示 | 用户层 | `user/cli.py` |
| 装配具体适配器（决定用哪个模型/媒体源） | 用户层（唯一装配根） | `user/cli.py` |
| 任务级入口、并行调度、增量摘要、失败重试 | 服务层 | `service/orchestrator.py` |
| 按窗取内容、递归调模型这类"动作" | 服务层 | `service/sharder.py`、`service/compressor.py` |
| 修正执行（打分→修正→重打分→护栏→回退） | 服务层 | `service/corrector.py` |
| 时间窗怎么切、文本怎么拆 | 规划层 | `planning/windows.py`、`planning/splits.py`、`planning/sentences.py` |
| 该修哪几句、怎么挑 | 规划层 | `planning/corrections.py` |
| 人物权重与配角过滤策略 | 规划层 | `planning/speakers.py` |
| 质量打分规则 | 规则层 | `rules/quality.py` |
| 防幻觉护栏 | 规则层 | `rules/guardrail.py` |
| 评测基线门槛（最低可接受标准） | 规则层 | `rules/baselines.py` |
| 数据模型、计划对象、可调参数（跨层共享） | 数据层 | `data/models.py` |
| 真实大模型 / ASR / 字幕文件的接入 | 外部层 | `external/adapters/<厂商>/` |
| 插座接口（新增一类外部能力） | 外部层 | `external/protocols.py` |
| 考卷数据、加载、指标、跑分 | 监控层 | `monitor/evals/`（用例结构留本层 `schemas.py`） |
| 将来的 gRPC / HTTP 服务端 | 用户层 | `user/`（新子目录） |
| 任务持久化、断点续跑 | 数据层 | `data/`（新模块） |

---

## 5. 计划 / 执行配对表

想加一类新处理逻辑时，**先在这张表里找配对**：计划函数进规划层，执行函数进服务层。

| 计划函数（规划层） | 执行函数（服务层） | 干什么 |
|---|---|---|
| `plan_windows` | `shard` | 切时间窗 → 按窗取内容组装分片 |
| `plan_compression` | `compress` | 单步决定放行/拆分 → 递归执行并调模型 |
| `split_sentences` + `plan_corrections` | `apply_corrections` | 拆句并挑出低分句 → 调修正器、重打分、过护栏、回退 |

---

## 6. 依赖方向

| 层 | 可以引用 |
|---|---|
| 用户层 | 用户层、服务层、监控层、**规则层**、外部层、数据层 |
| 服务层 | 服务层、规划层、规则层、外部层、数据层 |
| 规划层 | 规划层、**规则层**、数据层 |
| 规则层 | 规则层、数据层 |
| 数据层 | 数据层（不依赖任何其他层） |
| 外部层 | 外部层、数据层 |
| 监控层 | 监控层、服务层、规则层、外部层、数据层 |

四条解释：

- 服务层**不依赖**监控层：进度回调类型 `ProgressCallback` 由服务层定义，监控层/用户层实现后注入。
- 规划层依赖规则层：**计划要依据标准**——"哪句该修"用的就是规则层的达标判定，
  标准只写一处，线上判的与考卷量的是同一个。
- 用户层依赖规则层：**用户层是装配根**，把各层零件（含打分器）组装起来是它的本职；
  但规划层不在其列——用户层永远不直接调规划层，走服务层。
- 外部层（适配器）只依赖本层与数据层，不准反向依赖服务层、规划层、规则层。

这张表与 `tests/test_layering.py` 里的 `ALLOWED_LAYER_DEPS` 一一对应，改一处要改两处。

---

## 7. api 窗口规矩

- 每个 `xxx/api/` 就是该层的服务窗口：**跨层引用只能从窗口进**。
- 窗口文件只准写三样东西：文档字符串、`import`/`from ... import`、`__all__`。
  窗口里出现函数或类（**包括 Protocol 类定义**）会被 CI 判红——
  逻辑与定义一律住在层内的实现模块里，窗口只负责挂出来。
- 没挂在窗口里的东西就是该层私事（例如 `planning` 内部的段落对半拆细节）。
- 窗口是包还是单文件都行（`api/__init__.py` 与 `api.py` 对调用方完全等价），
  按接口多少自然演进，不必为了形式硬撑目录。

---

## 8. 文件清单（受 CI 检查）

新增/移动文件后必须同步这一节，`tests/test_layering.py` 会逐个检查存在性。

<!-- files:begin -->
vidrecap/__init__.py
vidrecap/__main__.py
vidrecap/user/__init__.py
vidrecap/user/api/__init__.py
vidrecap/user/cli.py
vidrecap/user/skills.py
vidrecap/service/__init__.py
vidrecap/service/api/__init__.py
vidrecap/service/orchestrator.py
vidrecap/service/sharder.py
vidrecap/service/compressor.py
vidrecap/service/corrector.py
vidrecap/planning/__init__.py
vidrecap/planning/api/__init__.py
vidrecap/planning/windows.py
vidrecap/planning/splits.py
vidrecap/planning/sentences.py
vidrecap/planning/corrections.py
vidrecap/planning/speakers.py
vidrecap/rules/__init__.py
vidrecap/rules/api/__init__.py
vidrecap/rules/quality.py
vidrecap/rules/guardrail.py
vidrecap/rules/baselines.py
vidrecap/data/__init__.py
vidrecap/data/api/__init__.py
vidrecap/data/models.py
vidrecap/data/store.py
vidrecap/external/__init__.py
vidrecap/external/api/__init__.py
vidrecap/external/protocols.py
vidrecap/external/adapters/__init__.py
vidrecap/external/adapters/demo/__init__.py
vidrecap/external/adapters/demo/llm.py
vidrecap/external/adapters/demo/source.py
vidrecap/external/adapters/demo/corrector.py
vidrecap/external/adapters/demo/text.py
vidrecap/external/adapters/demo/backend.py
vidrecap/external/adapters/srt/__init__.py
vidrecap/external/adapters/srt/source.py
vidrecap/external/adapters/openai/__init__.py
vidrecap/external/adapters/openai/llm.py
vidrecap/monitor/__init__.py
vidrecap/monitor/api/__init__.py
vidrecap/monitor/evals/__init__.py
vidrecap/monitor/evals/schemas.py
vidrecap/monitor/evals/loader.py
vidrecap/monitor/evals/metrics.py
vidrecap/monitor/evals/runner.py
<!-- files:end -->

---

## 9. 测试与提交

- 跑测试：`.venv/Scripts/python.exe -m pytest -q`（Windows）或 `pytest -q`。
- **分层硬检查**（`tests/test_layering.py`）会验证：跨层引用只走 api 窗口、窗口只做转出、
  规划层与规则层保持纯判断、一层一个文件夹、每层窗口能干净导入、本文件的受检清单不过期。
- **新增功能必须带测试**；修 bug 先写能复现的测试。
- **行为不变的重构**（搬家、提炼、改名）必须验证：`python -m vidrecap demo` 的输出
  与重构前**逐字节一致**。
- 测试风格与现有一致：plain assert + `pytest.raises` + `pytest.approx`，异步测试不需要装饰器。
- CI 覆盖 Python 3.10 / 3.11 / 3.12，`pytest -q` 必须全绿才算完成。
- 依赖极简：运行时只允许 `pydantic`，测试只允许 `pytest` + `pytest-asyncio`。**加依赖前先问。**

---

## 10. 开放核心边界

| 开源（本仓库） | 闭源（不进本仓库） |
|---|---|
| 七层引擎骨架、规划层纯函数 | 客户专有适配器 |
| 规则层打分器与护栏 | 调优过的提示词 |
| 离线 demo 适配器 | 运维配置与密钥管理 |
| 评测集与跑分脚本 | 具体客户的业务规则 |

准备往仓库里放东西前，先对照这张表确认它属于左边。

---

## 11. 当前状态

已完成：七层骨架与窗口、时间窗规划、二分递归压缩、并行调度与增量摘要、离线 demo、
分层 CI 硬检查（跨层引用、窗口纯净、纯判断层、一层一文件夹、文档清单新鲜度、窗口可导入）、
**规则层三指标打分器与达标判定**（清晰度/通顺度/完整度 + 阈值 + 单项一票否决）、
**评测集与跑分**（49 条手写考卷、指标、`vidrecap eval`、CI 基线门槛）、
**语义修正回路**（拆句→打分→计划→修正→重打分→护栏→回退，B 层考卷 15 条，四项基线达标）、
**demo 注毒与端到端评测**（确定性注毒、`--poison` 等开关、四条端到端断言）、
**阶段二：真实接入**（SRT 字幕源 `--srt`、OpenAI 兼容模型 `--llm openai`、
用户自定义提示词 `--instruction`、分片失败重试与降级、断点续跑 `--store`）、
**阶段三：JD 对齐**（后台目录取数与人物权重 `--catalog`、skill-md 技能文件与
双重提示词约束 `--skill`；画面与人物动作是外挂脚本扩展，见 ROADMAP 提交 12）。

ROADMAP 的提交 1–11 全部完成，仓库内不再有 `raise NotImplementedError` 骨架。

**更远的方向**（画面与人物动作、gRPC 服务化、监控导出、ASR 包内适配器）
见 [docs/ROADMAP.md](docs/ROADMAP.md) 与 [docs/REUSE.md](docs/REUSE.md)。

更远：真实大模型适配器、SRT/ASR 媒体源、失败重试与降级、任务持久化、gRPC 服务化；
选型与许可证红线见 [docs/REUSE.md](docs/REUSE.md)。
