"""撰稿 Agent（阶段 p6）。

职责：全局撰稿模式 —— 一次性拿到本章全部场景描述 + 设计稿的语气/氛围/冲突提示，
一次 LLM 调用写完整章所有场景正文（避免逐场景调用导致的跨场景断裂）。
"""

from __future__ import annotations

import re

from agents.base import BaseAgent


class DraftAgent(BaseAgent):
    stage_id = "draft"
    name = "正文初稿（全局撰稿）"
    prompt_name = "draft"

    # ── 从场景设计稿中提取场景块 ──
    @staticmethod
    def extract_scenes(scene_text: str) -> list:
        if not scene_text:
            return []
        scenes = []
        for block in re.split(r"(?=###\s*场景\s*\d)", scene_text):
            if not block.strip():
                continue
            m = re.search(r"###\s*场景\s*\d[：:]\s*(.+?)(?:\n)", block)
            if not m:
                continue
            def grab(label: str) -> str:
                mm = re.search(rf"\*\*{label}\*\*[：:]\s*(.+?)(?:\n|$)", block)
                return mm.group(1).strip() if mm else ""
            scenes.append({
                "name": m.group(1).strip(),
                "time": grab("时间"),
                "location": grab("地点"),
                "temperature": grab("温度"),
                "function": grab("功能"),
                "characters": grab("出场"),
                "core_event": grab("核心事件"),
                "atmosphere": grab("氛围"),
            })
        return scenes

    def user_prompt(self, chapter: int) -> str:
        scene_text = self.ctx.read_output("scene", chapter)
        scenes = self.extract_scenes(scene_text or "")

        parts = []
        if scenes:
            parts.append(f"## 第 {chapter} 章 · 全章场景列表（{len(scenes)} 场）\n")
            for i, sc in enumerate(scenes, 1):
                parts.append(f"### 场景{i}：{sc['name']}")
                for label, key in [("时间", "time"), ("地点", "location"), ("温度", "temperature"),
                                   ("功能", "function"), ("出场", "characters"),
                                   ("核心事件", "core_event"), ("氛围", "atmosphere")]:
                    if sc.get(key):
                        parts.append(f"**{label}**：{sc[key]}")
                parts.append("")
        else:
            parts.append(f"## 第 {chapter} 章 · 场景列表")
            parts.append(self.ctx.load_upstream("scene", chapter, limit=2500))

        parts.append("## 设计稿提示（语气 / 氛围 / 冲突 / 钩子）")
        parts.append(self.ctx.load_upstream("design", chapter, limit=1500))
        parts.append("")

        parts.append("## 大纲写作约束")
        parts.append(self.ctx.load_upstream("outline", chapter, limit=1500))
        parts.append("")

        prev = chapter - 1
        if prev >= 1:
            prev_text = (self.ctx.read_output("editor", prev)
                         or self.ctx.read_output("draft", prev))
            if prev_text:
                parts.append(f"## 上一章（第 {prev} 章）结尾（衔接参考）")
                parts.append(prev_text[-400:])
                parts.append("")

        parts.append(f"请为第 {chapter} 章写出全部场景的正文，直接写，不要额外解释。")
        return "\n".join(parts)
