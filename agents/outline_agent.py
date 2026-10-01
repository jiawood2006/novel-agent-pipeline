"""大纲 Agent（阶段 p2）。

职责：读取「写前上下文包 + 本章配置（标题 / 事件骨架 / 约束）」，
生成含核心事件链、出场角色、温度曲线的章节大纲。
"""

from __future__ import annotations

import json

from agents.base import BaseAgent
from config import get_chapter


class OutlineAgent(BaseAgent):
    stage_id = "outline"
    name = "章节大纲生成"
    prompt_name = "outline"

    def user_prompt(self, chapter: int) -> str:
        ch_cfg = get_chapter(self.ctx.cfg, chapter)

        parts = [f"## 第 {chapter} 章配置信息\n"]
        parts.append(json.dumps(ch_cfg, ensure_ascii=False, indent=2))
        parts.append("")

        parts.append("## 写前上下文包")
        parts.append(self.ctx.load_upstream("context", chapter))
        parts.append("")

        prev = chapter - 1
        if prev >= 1:
            prev_text = (self.ctx.read_output("editor", prev)
                         or self.ctx.read_output("draft", prev))
            parts.append(f"## 上一章（第 {prev} 章）结尾（衔接参考）")
            parts.append(prev_text[-500:] if prev_text else "（未找到，dry-run 占位）")
        else:
            parts.append("## 上一章结尾\n（第一章，无上一章）")

        parts.append(f"\n请生成第 {chapter} 章的详细大纲。")
        return "\n".join(parts)
