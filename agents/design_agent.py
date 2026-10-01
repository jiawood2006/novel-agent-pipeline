"""创意设计 Agent（阶段 p3）。

职责：基于大纲产出「场景分段 + 冲突推进 + 结尾钩子 + 伏笔设计」的结构化设计稿。
对应原始实现的 LLM 创意引擎 design 模式。
"""

from __future__ import annotations

import json

from agents.base import BaseAgent


class DesignAgent(BaseAgent):
    stage_id = "design"
    name = "创意设计（场景/冲突/伏笔）"
    prompt_name = "design"

    def user_prompt(self, chapter: int) -> str:
        mem = self.ctx.memory.query_for_chapter(chapter, self.ctx.cfg)

        parts = [f"## 第 {chapter} 章大纲"]
        parts.append(self.ctx.load_upstream("outline", chapter))
        parts.append("")

        parts.append("## 记忆图谱上下文")
        parts.append(f"- 相关角色：{json.dumps(mem['characters'], ensure_ascii=False)}")
        parts.append(f"- 未闭合线索：{json.dumps([t['name'] for t in mem['open_threads']], ensure_ascii=False)}")
        parts.append(f"- 活跃主题：{json.dumps(mem['active_themes'], ensure_ascii=False)}")
        parts.append("")

        parts.append(f"请为第 {chapter} 章产出场景与冲突设计（JSON）。")
        return "\n".join(parts)
