"""质量门禁的规则引擎部分。

两道门禁
--------
- 创意门禁（p5）：结构对齐 / 信息漏出控制 / 钩子密度 / 场景设计，四维打分。
  阈值：总分 ≥ min_total，且任一维度 ≥ min_dimension。
- 评审门禁（p7）：规则引擎初筛 × rule_weight + LLM 五维评审 × llm_weight。
  阈值：综合分 ≥ min_total，且 LLM 分 ≥ min_llm_score。

本模块只实现**确定性规则**（语法/错别字/信息漏出/style 违规），
LLM 维度的打分由 Agent 调用后回填。规则可被任意小说复用，与题材无关。
"""

from __future__ import annotations

import re

# ── 常见笔误/混用检查（体裁无关） ──
TYPO_RULES = [
    (r"的的", "重复的"),
    (r"了了", "重复了"),
    (r"在再", "\"在/再\"可能混用"),
    (r"的地得", "\"的/地/得\"用法检查"),
    (r"后候", "\"后/候\"可能混用"),
    (r"象像", "\"象/像\"可能混用"),
    (r"那哪", "\"那/哪\"可能混用"),
    (r"即既", "\"即/既\"可能混用"),
    (r"已己", "\"已/己\"可能混用"),
]

# ── 「信息漏出」检查：把身世背景直接写出来=违反展示原则 ──
INFO_LEAK_RULES = [
    (r"他的(父亲|母亲|哥哥|姐姐|弟弟|妹妹|爷爷|奶奶|外公|外婆)", "亲属介绍"),
    (r"他(出生|生长|长大)在", "出生地交代"),
    (r"他(曾经|以前|过去|当年|那时候)", "过去经历"),
    (r"(提起|说起|提到|聊到|谈到)当年", "回忆触发"),
    (r"他的(背景|来历|出身|身份)", "背景交代"),
    (r"原来他", "解释性揭示"),
]

# ── 风格违规：维度 -> [(标签, 正则, 单次扣分系数)] ──
STYLE_RULES = {
    "语法/标点": [
        ("连续逗号", r"，{2,}", 0.4),
        ("感叹号滥用", r"！{2,}", 0.3),
    ],
    "风格一致性": [
        ("小说腔", r"(嘴角[^\w]*扬起|微微一笑|不易察觉|冷笑一声|暗自)", 0.3),
        ("过度修辞", r"(宛如|仿佛|好似|犹如|如同)", 0.2),
        ("上帝视角", r"(他(知道|明白|意识到)(了)?)", 0.1),
        ("解释性叙述", r"(原来|其实|实际上|要知道)", 0.2),
    ],
}

RULE_BASE_SCORE = 90.0   # 规则引擎满分起点
PENALTY_SCALE = 40.0     # 扣分缩放


def check_typos(text: str) -> list:
    hits = []
    for pattern, desc in TYPO_RULES:
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"label": desc, "count": n})
    return hits


def check_info_leak(text: str) -> list:
    hits = []
    for pattern, label in INFO_LEAK_RULES:
        n = len(re.findall(pattern, text))
        if n:
            hits.append({"label": label, "count": n})
    return hits


def check_style(text: str) -> dict:
    result = {}
    for dim, rules in STYLE_RULES.items():
        issues = []
        for label, pattern, penalty in rules:
            n = len(re.findall(pattern, text))
            if n:
                issues.append({"label": label, "count": n, "penalty": penalty})
        if issues:
            result[dim] = issues
    return result


def rule_score(text: str) -> dict:
    """确定性规则打分（满分 100）。返回分数 + 明细。"""
    violations = check_style(text)
    penalty = 0.0
    for issues in violations.values():
        for v in issues:
            penalty += v["penalty"] * min(v["count"], 5)
    penalty += len(check_info_leak(text)) * 0.3

    score = max(0.0, RULE_BASE_SCORE - penalty * PENALTY_SCALE)
    return {
        "score": round(score, 1),
        "typos": check_typos(text),
        "info_leaks": check_info_leak(text),
        "style_violations": violations,
    }


def evaluate_creative_gate(dimensions: dict, gate_cfg: dict) -> dict:
    """创意门禁判定。

    dimensions: {"结构对齐": 78, "信息漏出控制": 82, "钩子密度": 65, "场景设计": 70}
    """
    min_total = gate_cfg.get("min_total", 60)
    min_dim = gate_cfg.get("min_dimension", 50)

    scored = [v for v in dimensions.values() if isinstance(v, (int, float))]
    total = round(sum(scored) / len(scored), 1) if scored else 0.0
    failed_dims = [k for k, v in dimensions.items()
                   if isinstance(v, (int, float)) and v < min_dim]
    passed = total >= min_total and not failed_dims

    return {
        "total_score": total,
        "passed": passed,
        "failed_dimensions": failed_dims,
        "reason": "" if passed else (
            f"总分 {total} < {min_total}" if total < min_total
            else f"维度低于 {min_dim}：{', '.join(failed_dims)}"),
    }


def evaluate_review_gate(rule_score_value: float, llm_score_value: float,
                         review_cfg: dict) -> dict:
    """评审门禁判定。综合分 = 规则×权重 + LLM×权重。"""
    rw = review_cfg.get("rule_weight", 0.3)
    lw = review_cfg.get("llm_weight", 0.7)
    min_total = review_cfg.get("min_total", 70)
    min_llm = review_cfg.get("min_llm_score", 60)

    combined = round(rule_score_value * rw + llm_score_value * lw, 1)
    llm_pass = llm_score_value >= min_llm
    passed = combined >= min_total and llm_pass

    reasons = []
    if not llm_pass:
        reasons.append(f"LLM 分 {llm_score_value} < {min_llm}")
    if combined < min_total:
        reasons.append(f"综合分 {combined} < {min_total}")

    return {
        "combined_score": combined,
        "llm_score": llm_score_value,
        "rule_score": rule_score_value,
        "passed": passed,
        "reason": "；".join(reasons),
    }


def parse_llm_json(raw: str) -> dict:
    """健壮地解析 LLM 返回的 JSON（去掉 ```json 围栏、容错提取）。"""
    import json
    text = re.sub(r"^```(?:json)?\s*\n?", "", raw or "", flags=re.MULTILINE)
    text = re.sub(r"\n?```\s*$", "", text, flags=re.MULTILINE)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
    return {"raw": raw}
