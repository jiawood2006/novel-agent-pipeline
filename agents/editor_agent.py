"""深度评审 Agent（阶段 p7）。

职责：两级评审
  1. 确定性规则引擎初筛（语法 / 错别字 / 信息漏出 / 风格违规）
  2. LLM 五维质量评审（叙事节奏 / 对话真实感 / 场景画面感 / 人物一致性 / 信息漏出控制）
综合分 = 规则 × rule_weight + LLM × llm_weight；阈值见配置。

若综合门禁不通过，流水线会中断，正文不进入记忆吸收。
"""

from __future__ import annotations

from agents.base import BaseAgent
from gates import evaluate_review_gate, parse_llm_json, rule_score


class EditorAgent(BaseAgent):
    stage_id = "editor"
    name = "深度评审（规则 + LLM 五维）"
    prompt_name = "review"

    def user_prompt(self, chapter: int) -> str:
        parts = [f"## 第 {chapter} 章 · 正文评审\n"]
        parts.append("### 正文内容\n")
        parts.append(self.ctx.load_upstream("draft", chapter, limit=6000))

        prev = chapter - 1
        if prev >= 1:
            prev_text = (self.ctx.read_output("editor", prev)
                         or self.ctx.read_output("draft", prev))
            if prev_text:
                parts.append(f"\n### 上一章（第 {prev} 章）结尾（衔接参考）\n{prev_text[-500:]}\n")
        return "\n".join(parts)

    def postprocess(self, raw: str, chapter: int) -> dict:
        # 规则引擎初筛：对「正文初稿」打分
        draft_text = self.ctx.read_output("draft", chapter) or ""
        rule = rule_score(draft_text)

        data = parse_llm_json(raw)
        llm_score = data.get("total_score")
        if not isinstance(llm_score, (int, float)):
            return {"gate": {"passed": None, "reason": "LLM 输出未含可解析总分"},
                    "rule": rule}
        gate = evaluate_review_gate(rule["score"], llm_score,
                                    self.ctx.cfg["quality_gates"]["review_gate"])
        gate["dimensions"] = {k: v.get("score") for k, v in
                              (data.get("dimensions") or {}).items() if isinstance(v, dict)}
        return {"gate": gate, "rule": rule}
