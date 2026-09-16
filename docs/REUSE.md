# 开源复用调研（选型参考）

> 本文件是**规则层**资产：记录"哪些轮子不用自己造、哪些只许读思路、哪些碰不得"。
> 引入任何新依赖前先看这里；数据采集于 2026-09，star 与活跃度会变，**许可证结论请以仓库原文为准**。

## 一、三条总体结论

1. **核心引擎没有现成等价物**。GitHub 上的 map-reduce 摘要实现几乎都长在 LangChain / LlamaIndex
   内部——引入即背上整套框架，与本项目"运行时只依赖 pydantic、纯 asyncio"的底线冲突。
   分片 + 递归压缩 + 调度这一层自研是对的。
2. **真正能接进插座的只有两个位置**：取文本（`MediaSource`）与句子修正（`SentenceCorrector`）。
3. **中文可读性 / 摘要质量打分这个赛道几乎是空的**——最完整的工具是个没有许可证的图形界面程序。
   我们的启发式打分器不是重复造轮子，是补空缺；应继续自研并打磨。

---

## 二、可以接进插座的（许可证干净、可商用）

| 目标插座 | 候选 | 许可证 | 为什么合适 | 要注意 |
|---|---|---|---|---|
| `MediaSource` | [youtube-transcript-api](https://github.com/jdepoix/youtube-transcript-api) | MIT | 返回**带起止时间的字幕条目**，与插座形状天然吻合，纯 Python 无重依赖 | 只在视频自带字幕时可用；同步库，接 asyncio 要用线程池；有反爬风控 |
| `MediaSource` | [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | MIT（含模型权重） | 段级时间戳，CPU 用量化即可跑，中文可用 | 首次要下模型；同步库需包线程池 |
| `MediaSource` | [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) | Apache-2.0 | **纯 CPU、不依赖 PyTorch、带 VAD（判断哪段有人说话）**，最贴近"离线零 Key 可跑" | Python 绑定风格偏底层，要照抄示例 |
| `MediaSource` | [FunASR](https://github.com/modelscope/FunASR) | 代码 MIT，**权重另算（见红线）** | 中文识别质量好，自带标点恢复与说话人分离 | 商用前必须确认权重许可 |
| `SentenceCorrector` | [pycorrector](https://github.com/shibing624/pycorrector) | Apache-2.0 | 中文纠错工具箱，多档模型可按算力切换 | 会拖进 torch/transformers，**必须做成可选依赖**；轻量档只修错别字，改写能力弱 |
| `SentenceCorrector` | [ChineseErrorCorrector3-4B](https://huggingface.co/twnlp/ChineseErrorCorrector3-4B) | Apache-2.0 | 当前中文纠错效果最好的开源模型之一，且能做改写 | 慢（QPS 个位数），只适合送低分句进去——正好是我们的设计 |
| 护栏升级 | [Erlangshen-Roberta-330M-NLI](https://huggingface.co/IDEA-CCNL/Erlangshen-Roberta-330M-NLI) | Apache-2.0 | 中文"这能不能推出那"的小模型，CPU 可跑；能认"没来开会 = 缺席会议"这类合法改写，也能判"价格下降 vs 上涨"的矛盾 | 返回的是分数不是实体名单，需要外包一层转换（见第四节） |
| 护栏升级 | [mDeBERTa-v3-base-mnli-xnli](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli) | MIT | 上一条的多语言替代，许可更宽松 | 中文精细度通常不如中文单语模型，两者应同台比分数 |

引入方式：**一律做成 `external/adapters/<厂商>/` 下的适配器**，重量级依赖写进
`[project.optional-dependencies]`，主依赖保持只有 pydantic。

---

## 三、只许读思路、不许抄代码的

| 项目 | 许可证 | 借什么 |
|---|---|---|
| [LlamaIndex](https://github.com/run-llama/llama_index) | MIT | `tree_summarize` / `refine` 的提示词模板与 token 预算判断 |
| [LangChain](https://github.com/langchain-ai/langchain) | MIT | map-reduce 的经典坑：各分片互不知情会导致信息重复，看它 reduce 阶段的去重指令写法 |
| [RAPTOR](https://github.com/parthsarthi03/raptor) | **仓库无 LICENSE 文件（存疑）** | 递归抽象树：按语义聚类后再递归，比"按段落对半"更能保住相关内容 |
| [GraphRAG](https://github.com/microsoft/graphrag) | MIT | 分层归并摘要 + 摘要可回溯到来源片段 |
| [STORM](https://github.com/stanford-oval/storm) | MIT | "先出大纲再逐节写"，与本项目规划层同构 |
| [LLMLingua](https://github.com/microsoft/LLMLingua) | MIT | 长文压缩三招：问题感知压缩、关键内容位置重排、分段压缩后合并 |
| [simonw/llm](https://github.com/simonw/llm) | Apache-2.0 | 插件自动发现机制（第三方包声明自己是某个插座的实现），以及 SQLite 记录每次调用 |
| [openai-cookbook](https://github.com/openai/openai-cookbook) | MIT | 长文档摘要 notebook，**许可证干净，可放心抄代码** |

---

## 四、调研发现的三个设计问题（待处理）

1. **打分器插座的文档自相矛盾（已修）**：原先既要求"确定性、不调模型"，又说"将来可换模型实现"。
   模型推理有浮点噪声，做不到逐字节可复现。现按三档口径定稿：插座允许任意实现且是**异步**的
   （慢实现自己在线程池里跑，包装责任在适配器）；**默认实现（规则层启发式）必须确定性**，
   供 CI 与评测集复现；模型实现放外部层，只在"对比报告"里跑，不进 CI 门槛。
   同时把跑分器 `run_scorer_eval` 改成异步，以对齐插座。
2. **护栏的函数签名吞不下分数**：`check_faithfulness` 返回的是"越界实体名单"，
   而模型类判官输出的是 0~1 的分数。接模型时必须外面包一层：
   先按标点切块 → 逐块判 → 把不合格的块转成名单返回。
   可参考 RAGAS 的"先拆主张、再逐条验证、最后算比例"三段式。
3. **实体抽取不能留在纯判断层**：HanLP / jieba 这类要读词典文件，而 `rules` 层被 CI 禁止做 I/O。
   真要用它们，得把"抽取"挪到外部层，`rules` 只保留"拿到实体列表后做比对"的纯逻辑。

---

## 五、评测：不需要第三方框架

实测结论：我们要的指标**全部能用标准库手写**，真正卡人的只有"中文怎么切句"，不是算法。

| 指标 | 零依赖实现 |
|---|---|
| 阈值准确率 | 二分类计数，3 行 |
| 好句坏句排序正确率 | 秩和 / AUC 手算约 15 行（注意同分并列） |
| 修正成功率 | `difflib.SequenceMatcher` 字符级相似度，约 10 行 |
| 无幻觉率 | 复用"必须保留的实体"清单做集合覆盖比对，约 20 行 |
| 中文切句 | 正则 `[。！？；…!?;]` 切分，约 5 行；**别引入分词器**，否则分数不可复现 |

将来真要接大模型做裁判，再评估 deepeval（pytest 原生）或 inspect_ai（工程化扎实）；
两者都会拖进较多依赖，且要单独校准，不能直接信模型的分数。

---

## 六、路线图上"失败重试"与"监控指标"的建议

| 需求 | 建议 | 依赖成本 |
|---|---|---|
| 失败重试与降级 | [tenacity](https://github.com/jd/tenacity)（Apache-2.0） | **0 个传递依赖**；asyncio 下必须用异步 API；只重试限流/超时，不重试参数错误 |
| 任务持久化 / 断点续跑 | **标准库 sqlite3 自己写**几十行；其次 diskcache | 前者零依赖，且更符合本项目洁癖 |
| 监控指标导出 | [prometheus-client](https://github.com/prometheus/client_python)（Apache-2.0） | 0 个依赖；别把视频 ID 当标签，会造成指标爆炸 |

---

## 七、许可证红线（商业场景必看）

**本项目以 MIT 开源且面向商业客户，以下一律不要引入依赖树，也不要把代码复制进来：**

| 项目 | 问题 |
|---|---|
| whisper-timestamped | **AGPL-3.0**：一旦对外提供服务就可能被要求公开全部源码。用 MIT 的 stable-ts 替代 |
| HKUDS/VideoRAG | 打包了受限模型，**整体仅限非商用** |
| SenseVoice / FunASR 的**模型权重** | GitHub 标着 MIT，但**权重是 ModelScope 自定义协议**（"仅供参考学习"，商用不明确）。这是最容易踩的坑——代码许可不等于权重许可 |
| NVIDIA 视频搜索摘要蓝图 | 主许可宽松，但内含 SSPL / AGPL 组件，且本地推理要企业授权 |
| textflint、language_tool_python | GPL-3.0，传染 |
| LTP、Lynx、AlphaReadabilityChinese、CSL 等 | **根本没有许可证文件**——法律上默认保留所有权利，不可复制分发 |
| RAPTOR | 页面标 MIT，但仓库里找不到 LICENSE 文件，引入前必须找作者确认 |
| 各类 YouTube 摘要小项目 | 多为 GPL-3.0，只能读不能抄 |

**通用提醒**：没有许可证文件 ≠ 可以随便用；模型仓库（HuggingFace / ModelScope）的许可与
GitHub 代码仓库的许可是两套东西，都要看。

**落地记录（2026-09）**：按上表结论，"视频 → 字幕"这一步用外挂脚本
`scripts/video2recap.py` 实现：默认走 faster-whisper（MIT，含模型权重），
由使用者按需自装、不进 vidrecap 依赖树；whisper-timestamped（AGPL）不引入。
脚本只产 SRT，概括链路仍由包内 `SrtSource` + `vidrecap demo` 完成。

---

## 八、阶段三复用清单（2026-09 调研，对应 ROADMAP 提交 9–12）

原则不变：**格式抄标准、模型走外挂、策略自己写**。

| 阶段三组件 | 复用什么 | 许可证结论 | 用法 |
|---|---|---|---|
| skill-md 技能配置 | [Agent Skills 开放标准](https://agentskills.io/specification)（SKILL.md + frontmatter + Markdown 正文，2025-12 起开放） | 规范公开出版 | **遵循格式、自写解析**：frontmatter 用受限平铺键值（不引 PyYAML），字段与标准兼容 |
| 人物标签来源 | [pyannote](https://github.com/pyannote/pyannote-audio)（说话人分离事实标准） | 代码 MIT；模型 HF 门禁，接受协议后免费商用 | 外挂工具（同 faster-whisper 先例），产"谁在何时说话"，不进包依赖 |
| 说话人+对齐一条龙 | [WhisperX](https://github.com/m-bain/whisperX)（ASR+词级时间戳+分离） | **BSD-4-Clause**（可用，含"不得用作者名义背书"条款）；分离部分实际依赖 pyannote | 备选外挂；许可证比 MIT 多一条注意项 |
| 场景切换检测 | [PySceneDetect](https://github.com/breakthrough/pyscenedetect) | BSD-3-Clause，完全宽松 | 外挂脚本抽帧加密触发 |
| 画面识字 | [PaddleOCR](https://github.com/PaddlePaddle/PaddleOCR) / RapidOCR | 均 Apache-2.0，商用无忧 | 外挂件，中文强 |
| 画面描述 | 无需复用代码：视觉模型走 OpenAI 兼容 API（Qwen-VL 系） | — | 复用现有 `OpenAICompatibleLLM` 模式加图片消息 |
| 人物权重策略 | **无可复用项目** | — | 自研卖点：规划层纯函数 + 考卷先行 |
| Function Calling 骨架 | LiteLLM 等统一网关 | MIT 但违背零依赖铁律 | 不引——现有插座已覆盖 |

不进依赖树的红线照旧（见第七节）；新增结论：pyannote 模型门禁接受即可免费商用，
但"留联系方式换授权"这步要写进部署文档，别在客户环境里卡壳。
