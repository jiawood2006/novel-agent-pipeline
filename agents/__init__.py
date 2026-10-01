"""7 个流水线 Agent。

对照流水线阶段：
    context  → 写前检索（记忆召回）
    outline  → 章节大纲
    design   → 创意设计（场景/冲突/伏笔）
    scene    → 场景拆分 / 节奏
    gate     → 创意门禁（四维评分）
    draft    → 正文初稿
    editor   → 深度评审（规则 + LLM 五维）

第 8 个阶段 `absorb`（记忆吸收）由 memory 子系统承担，见 pipeline.py。
"""

from agents.base import BaseAgent, PipelineContext, output_name, truncate  # noqa: F401
from agents.context_agent import ContextAgent
from agents.outline_agent import OutlineAgent
from agents.design_agent import DesignAgent
from agents.scene_agent import SceneAgent
from agents.gate_agent import GateAgent
from agents.draft_agent import DraftAgent
from agents.editor_agent import EditorAgent

# 按流水线顺序注册
ALL_AGENTS = [
    ContextAgent,
    OutlineAgent,
    DesignAgent,
    SceneAgent,
    GateAgent,
    DraftAgent,
    EditorAgent,
]

__all__ = [
    "BaseAgent", "PipelineContext", "output_name", "truncate",
    "ContextAgent", "OutlineAgent", "DesignAgent", "SceneAgent",
    "GateAgent", "DraftAgent", "EditorAgent", "ALL_AGENTS",
]
