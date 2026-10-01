"""写前检索 Agent（阶段 p1）。

职责：把「整体方向 + 记忆图谱状态 + 上章结尾」压缩成一个有针对性的上下文包，
供后续所有阶段复用。对应原始实现的 LLM MAGMA 写前检索。
"""

from __future__ import annotations

import json

from agents.base import BaseAgent, truncate


class ContextAgent(BaseAgent):
    stage_id = "context"
    name = "写前检索（记忆召回）"
    prompt_name = "context"

    def user_prompt(self, chapter: int) -> str:
        cfg = self.ctx.cfg
        mem = self.ctx.memory.query_for_chapter(chapter, cfg)

        parts = [f"## 第 {chapter} 章 · 待检索材料\n"]

        # 1. 记忆图谱（四维）当前状态
        parts.append("### 记忆图谱状态（四维）")
        parts.append(json.dumps(self.ctx.memory.summary(), ensure_ascii=False))
        parts.append("")

        # 2. 本章检索结果
        parts.append("### 本章检索结果")
        parts.append(f"- 相关角色：{json.dumps(mem['characters'], ensure_ascii=False)}")
        parts.append(f"- 角色关系：{json.dumps(mem['relationships'], ensure_ascii=False)}")
        parts.append(f"- 时间线节点：{json.dumps([e['name'] for e in mem['recent_events']], ensure_ascii=False)}")
        parts.append(f"- 未闭合线索：{json.dumps([t['name'] for t in mem['open_threads']], ensure_ascii=False)}")
        parts.append(f"- 活跃主题：{json.dumps(mem['active_themes'], ensure_ascii=False)}")
        parts.append(f"- 生效写作约束：{json.dumps(mem['rules'], ensure_ascii=False)}")
        parts.append("")

        # 3. 上一章结尾（衔接）
        prev = chapter - 1
        if prev >= 1:
            prev_text = (self.ctx.read_output("editor", prev)
                         or self.ctx.read_output("draft", prev))
            if prev_text:
                parts.append(f"### 上一章（第 {prev} 章）结尾（衔接参考）")
                parts.append(prev_text[-500:])
            else:
                parts.append(f"### 上一章（第 {prev} 章）结尾\n（未找到，dry-run 占位）")
        else:
            parts.append("### 上一章结尾\n（第一章，无上一章）")

        parts.append(f"\n请根据以上材料，为第 {chapter} 章生成写前上下文包。")
        return "\n".join(parts)
