"""创意门禁 Agent（阶段 p5）。

职责：对「场景设计 + 设计稿」做四维评分（结构对齐 / 信息漏出控制 / 钩子密度 /
场景设计），判定 PASS / FAIL。任一维度或总分不达标即拦截，禁止进入撰稿。
"""

from __future__ import annotations

from agents.base import BaseAgent
from gates import evaluate_creative_gate, parse_llm_json


class GateAgent(BaseAgent):
    stage_id = "gate"
    name = "创意门禁（四维评分）"
    prompt_name = "gate"

    def user_prompt(self, chapter: int) -> str:
        parts = [f"## 第 {chapter} 章场景设计"]
        parts.append(self.ctx.load_upstream("scene", chapter, limit=2500))
        parts.append("")
        parts.append("## 第 %d 章设计稿" % chapter)
        parts.append(self.ctx.load_upstream("design", chapter, limit=2000))
        parts.append("")
        parts.append("## 第 %d 章大纲" % chapter)
        parts.append(self.ctx.load_upstream("outline", chapter, limit=1500))
        parts.append("")
        parts.append("请对以上材料做四维评分并输出 JSON。")
        return "\n".join(parts)

    def postprocess(self, raw: str, chapter: int) -> dict:
        data = parse_llm_json(raw)
        dims = {}
        for name, info in (data.get("dimensions") or {}).items():
            if isinstance(info, dict) and isinstance(info.get("score"), (int, float)):
                dims[name] = info["score"]
        if not dims:
            return {"gate": {"passed": None, "reason": "LLM 输出未含可解析维度"}}
        result = evaluate_creative_gate(dims, self.ctx.cfg["quality_gates"]["creative_gate"])
        result["dimensions"] = dims
        return {"gate": result}
