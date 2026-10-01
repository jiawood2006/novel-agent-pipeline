"""场景/节奏 Agent（阶段 p4）。

职责：把设计稿拆成 3-5 个可写的场景，每个场景标注时间 / 地点 / 温度 / 功能 /
出场角色 / 核心事件 / 氛围，控制整章节奏曲线。
"""

from __future__ import annotations

from agents.base import BaseAgent


class SceneAgent(BaseAgent):
    stage_id = "scene"
    name = "场景拆分与节奏设计"
    prompt_name = "scene"

    def user_prompt(self, chapter: int) -> str:
        parts = [f"## 第 {chapter} 章设计稿（优先级最高）"]
        parts.append(self.ctx.load_upstream("design", chapter))
        parts.append("")

        parts.append("## 第 %d 章大纲（核心事件链）" % chapter)
        parts.append(self.ctx.load_upstream("outline", chapter))
        parts.append("")

        parts.append("## 写前检索上下文（参考）")
        parts.append(self.ctx.load_upstream("context", chapter, limit=1500))
        parts.append("")

        parts.append(f"请为第 {chapter} 章生成场景拆分方案。")
        return "\n".join(parts)
