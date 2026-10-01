# 多 Agent 小说写作流水线框架

> A config-driven multi-agent framework for writing novels — 7 agents + a 4-graph memory engine.

一个把「写一章小说」拆成**阶段流水线**的开源框架：7 个职责单一的 Agent
接力生产一章，中间穿插两道**质量门禁**，并用一个**四维记忆图谱**保证长篇一致性。
全部内容**配置驱动**——换一部小说只需要换一个 JSON 配置文件，不改代码。

- 🧩 7 个 Agent，各管一件事（检索 / 大纲 / 设计 / 场景 / 门禁 / 撰稿 / 评审）
- 🕸️ 四维记忆图谱（实体 / 时间 / 因果 / 语义），防角色崩、时间乱、伏笔丢
- 🚦 两道质量门禁 + 修复回路，差稿在动笔前后就被拦下
- 🔌 任意 OpenAI 兼容接口（DeepSeek / OpenAI / vLLM / Ollama）
- ✅ **不需要任何 API key 就能离线预览全流程**（`--dry-run`）

---

## 一、为什么这么设计

写长篇小说，模型能力不是主要瓶颈，**一致性**和**流程失控**才是：

| 痛点 | 本框架的解法 |
|:---|:---|
| 角色设定写着写着就崩 | 记忆图谱外置 + 每章写后吸收（p8） |
| 时间线 / 伏笔前后矛盾 | 因果图谱管理线索 `open/resolved` 状态 |
| 一个巨型 prompt 又写又评，评分虚高 | 撰稿与评审是**两个独立 Agent** |
| 一步错、步步错 | 阶段门禁 + 产物落盘 + 单步可重跑 |
| 换小说要重写代码 | 配置驱动：一部小说 = 一个 JSON |

核心思想：**把创作流程工程化**。创作（写得好看）交给 LLM，
流程（顺序、依赖、门禁、记忆）交给框架。

---

## 二、架构

```
                         ┌──────────────────────────┐
                         │   四维记忆图谱 memory.py   │
                         │ entity / temporal /       │
                         │ causal / semantic         │
                         └─────────────┬────────────┘
                    写前检索 ↑               ↓ 写后吸收
                               │               │
   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │ p1 检索    │──▶│ p2 大纲    │──▶│ p3 设计    │──▶│ p4 场景    │
   │ Context   │   │ Outline   │   │ Design    │   │ Scene     │
   └───────────┘   └───────────┘   └───────────┘   └─────┬─────┘
                                                          │
                                    ┌─────────────────────┘
                                    ▼
   ┌───────────┐   ┌───────────┐   ┌───────────┐   ┌───────────┐
   │ p8 吸收    │◀──│ p7 评审    │◀──│ p6 撰稿    │◀──│ p5 门禁    │
   │ MemoryEng │   │ Editor    │   │ Draft     │   │ Gate      │
   └───────────┘   └───────────┘   └───────────┘   └───────────┘
        │                                                 │
        └──────────▶ 更新记忆图谱（下一章更准）            └─ FAIL 则中断
```

详见 [`docs/architecture.md`](docs/architecture.md)。

---

## 三、7 个 Agent 的职责

| 阶段 | Agent | 输入 | 输出 | 职责 |
|:---:|:---|:---|:---|:---|
| p1 | `ContextAgent` | 记忆图谱 + 上章结尾 | `context_ch{N}.md` | 写前检索：方向 + 记忆 + 前情 → 上下文包 |
| p2 | `OutlineAgent` | 上下文包 + 本章配置 | `outline_ch{N}.md` | 生成含事件链 / 温度曲线的大纲 |
| p3 | `DesignAgent` | 大纲 + 记忆 | `design_ch{N}.md` | 场景分段 / 冲突推进 / 伏笔设计 |
| p4 | `SceneAgent` | 设计稿 + 大纲 | `scene_ch{N}.md` | 拆 3-5 个可写场景，控制节奏 |
| p5 | `GateAgent` | 场景 + 设计 + 大纲 | `gate_ch{N}.json` | 四维评分门禁，不达标即拦截 |
| p6 | `DraftAgent` | 全部场景 + 设计稿 | `draft_ch{N}.md` | 一次性写完整章正文 |
| p7 | `EditorAgent` | 正文初稿 | `editor_ch{N}.json` | 规则初筛 + LLM 五维评审 |

> 第 8 个阶段 `absorb`（记忆吸收）由**记忆引擎**承担，不是写作 Agent——
> 它只做结构化提取与图谱写入，不做创作。

---

## 四、记忆图谱（MAGMA 四维）

把小说记忆拆成四个**正交**图谱，各管一件事：

| 图谱 | 对应 | 解决 |
|:---|:---|:---|
| 👥 实体 entity | 人物关系网 | 角色关系 / 状态 / 设定不漂移 |
| 📅 时间 temporal | 故事时间线 | 事件先后、闪回、并行不出错 |
| 🔗 因果 causal | 伏笔 → 回收链 | 埋的线有人收、动机链不断 |
| 🎭 语义 semantic | 主题 / 世界观 / 写作约束 | 主题不跑偏、规则不被违反 |

- **写前检索**：p1 把图谱「投影」成上下文包，喂给后续所有阶段。
- **写后吸收**：p8 把新章的事件 / 角色 / 线索 / 主题写回图谱（Fast Path）。
- 存储为纯 JSON，零依赖可读写；装了 `networkx` 可做图分析。

详见 [`docs/memory-graph.md`](docs/memory-graph.md)。

---

## 五、质量门禁

两道强制门禁，**不达标即中断**：

```
综合分 = 规则引擎分 × 0.3 + LLM 五维分 × 0.7      PASS 需 ≥ 70 且 LLM ≥ 60
```

- **p5 创意门禁**：结构对齐 / 信息漏出控制 / 钩子密度 / 场景设计（动笔前拦结构问题）。
- **p7 评审门禁**：规则引擎（笔误 / 信息漏出 / 风格违规）兜机械问题，
  LLM 五维兜文学问题。

FAIL 不是终点，而是**回到上游单步重跑**（`--step design` / `--step draft`）。
详见 [`docs/quality-gates.md`](docs/quality-gates.md)。

---

## 六、跑演示（无需任何 API key）

仓库自带一个**虚构的 demo 示例小说**（`demo/demo_novel.json`，
人物 / 城市 / 剧情全部为演示自造）。离线预览全部阶段将要发送的完整提示词：

```bash
python3 pipeline.py --config demo/demo_novel.json --dry-run
```

它会打印阶段计划，然后逐阶段输出**组装好的 system / user 提示词**，退出码 0，
**不调用任何 LLM、不需要任何密钥**。

```bash
# 只看阶段与依赖
python3 pipeline.py --config demo/demo_novel.json --list-stages

# 看某章的进度
python3 pipeline.py --config demo/demo_novel.json --status
```

### 真实生成（需要密钥）

```bash
export DEEPSEEK_API_KEY=你的密钥        # 或换成你的 OpenAI 兼容服务的 key
python3 pipeline.py --config demo/demo_novel.json --chapter 1   # 跑第 1 章
python3 pipeline.py --config demo/demo_novel.json --all         # 跑配置里所有章
```

密钥**只从环境变量读取**（变量名在配置的 `llm.key_env` 里指定），
框架不写死、不读私有文件。产物写入 `<output_dir>/`（默认为配置同级 `output/`）。

---

## 七、接入你自己的小说（配置驱动）

不用改任何代码，只需要一个配置文件。最小配置长这样：

```jsonc
{
  "novel": {
    "title": "你的书名",
    "genre": "题材",
    "logline": "一句话故事",
    "pov": "第三人称有限视角，始终跟主角XX",
    "setting": { "city": "城市", "era": "年代", "tone": "基调" },
    "themes": ["主题1", "主题2"],
    "style_constraints": ["短句，段落不超过5行", "展示而非讲述，信息漏出不超30字"]
  },
  "phases":   [ { "id": 1, "name": "入局", "start_chapter": 1, "end_chapter": 3 } ],
  "characters": [ { "name": "主角", "role": "主角", "identity": "身份", "traits": "性格", "voice": "说话风格" } ],
  "relationships": [ { "a": "主角", "b": "配角", "relation": "关系", "strength": 0.8 } ],
  "chapters": {
    "1": { "title": "第一章标题", "type": "混合", "beats": ["事件1", "事件2", "章尾钩子…"] }
  },
  "llm": { "base_url": "https://api.deepseek.com/v1", "model": "deepseek-chat", "key_env": "DEEPSEEK_API_KEY" },
  "quality_gates": {
    "creative_gate": { "min_total": 60, "min_dimension": 50 },
    "review_gate":   { "min_total": 70, "min_llm_score": 60, "rule_weight": 0.3, "llm_weight": 0.7 }
  }
}
```

更完整的示例见 [`demo/demo_novel.json`](demo/demo_novel.json)，
世界观文档示例见 [`demo/demo_world.md`](demo/demo_world.md)。

章节太多时，可把章节拆到单独文件，用 `"chapters_file": "chapters.json"` 引用。
所有提示词模板都在 [`prompts/`](prompts/)，改文风 / 改约束只需改 Markdown。

---

## 八、目录结构

```
novel-agent-pipeline/
├── pipeline.py            # 编排引擎入口（p1~p8、依赖检查、进度、门禁拦截）
├── config.py              # 配置加载与默认值
├── llm.py                 # LLM 客户端封装（OpenAI 兼容；dry-run 不需密钥）
├── memory.py              # 四维记忆图谱（entity/temporal/causal/semantic）
├── gates.py               # 门禁的规则引擎 + 阈值判定 + JSON 容错解析
├── agents/
│   ├── base.py            # Agent 基类 + 运行时上下文
│   ├── context_agent.py   # p1 写前检索
│   ├── outline_agent.py   # p2 大纲
│   ├── design_agent.py    # p3 创意设计
│   ├── scene_agent.py     # p4 场景拆分
│   ├── gate_agent.py      # p5 创意门禁
│   ├── draft_agent.py     # p6 撰稿
│   └── editor_agent.py    # p7 深度评审
├── prompts/               # 8 个通用提示词模板（Markdown）
├── demo/                  # 虚构示例小说配置（demo 数据）
├── docs/                  # 方法论文档（架构 / 记忆 / 门禁）
├── requirements.txt       # 真实生成所需依赖（dry-run 零依赖）
├── LICENSE                # MIT
└── .gitignore
```

---

## 九、English

**A config-driven multi-agent framework for long-form novel writing.**

Writing a long novel is limited less by model capability than by *consistency*
and *process control*. This framework turns "writing one chapter" into a staged
pipeline: **7 single-responsibility agents** (context → outline → design → scene
→ gate → draft → editor) hand off structured artifacts, guarded by **two quality
gates**, with a **4-graph memory engine** (entity / temporal / causal / semantic)
that is queried before each chapter and updated after it.

Key properties:

- **Config-driven** — one novel = one JSON config; swap the novel without touching code.
- **Reproducible & gateable** — every stage writes to disk, so any step can be
  re-run in isolation and bad drafts are blocked before propagating.
- **Provider-agnostic** — works with any OpenAI-compatible endpoint
  (DeepSeek / OpenAI / vLLM / Ollama); keys are read only from environment variables.
- **Runs offline** — `python3 pipeline.py --config demo/demo_novel.json --dry-run`
  prints every fully-assembled prompt for all stages and exits 0 **without any API key**.

```bash
python3 pipeline.py --config demo/demo_novel.json --dry-run   # offline preview
export DEEPSEEK_API_KEY=<your-api-key>                          # then real generation
python3 pipeline.py --config demo/demo_novel.json --chapter 1
```

MIT licensed. Demo data is fictional and self-authored.

---

## 十、License

[MIT](LICENSE)
