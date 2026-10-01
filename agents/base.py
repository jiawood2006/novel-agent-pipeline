"""Agent 基类与流水线运行时上下文。

所有 Agent 都遵守同一套契约：
  - `stage_id`  对应流水线阶段（context / outline / …）
  - `build(chapter)` 返回组装好的 `(system_prompt, user_prompt)`
  - `run(chapter, dry_run)` 在 dry-run 下只返回组装好的提示词；
    在真实运行时才调用 LLM，并可 `postprocess()` 写图谱 / 判定门禁。
"""

from __future__ import annotations

import os
from string import Template

from config import get_chapter, resolve_phase

# 阶段产物的文件扩展名（结构化输出的阶段用 json）
_JSON_STAGES = {"gate", "absorb"}


def output_name(stage_id: str, chapter: int) -> str:
    ext = "json" if stage_id in _JSON_STAGES else "md"
    return f"{stage_id}_ch{chapter}.{ext}"


def truncate(text: str, limit: int) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（已截断，共 {len(text)} 字符）"


class PipelineContext:
    """贯穿一次流水线运行的共享上下文。"""

    def __init__(self, cfg: dict, llm, memory, prompts_dir: str,
                 output_dir: str, dry_run: bool = False):
        self.cfg = cfg
        self.llm = llm
        self.memory = memory
        self.prompts_dir = prompts_dir
        self.output_dir = output_dir
        self.dry_run = dry_run
        os.makedirs(self.output_dir, exist_ok=True)

    # ── 产物读写 ──
    def output_path(self, stage_id: str, chapter: int) -> str:
        return os.path.join(self.output_dir, output_name(stage_id, chapter))

    def read_output(self, stage_id: str, chapter: int):
        path = self.output_path(stage_id, chapter)
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    def load_upstream(self, stage_id: str, chapter: int, limit: int = 2500) -> str:
        """读取上游产物；不存在时返回占位说明（dry-run 友好）。"""
        text = self.read_output(stage_id, chapter)
        if text:
            return truncate(text, limit)
        return f"（上游产物 {output_name(stage_id, chapter)} 尚未生成——dry-run 占位）"

    def write_output(self, stage_id: str, chapter: int, text: str):
        path = self.output_path(stage_id, chapter)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read_prompt(self, name: str) -> str:
        path = os.path.join(self.prompts_dir, f"{name}.md")
        with open(path, "r", encoding="utf-8") as f:
            return f.read()


class BaseAgent:
    """所有 Agent 的基类。"""

    stage_id = ""
    name = ""
    prompt_name = ""

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    # ── 模板变量 ──
    def template_vars(self, chapter: int) -> dict:
        cfg = self.ctx.cfg
        novel = cfg.get("novel", {})
        setting = novel.get("setting", {})
        phase = resolve_phase(cfg, chapter)
        ch_cfg = get_chapter(cfg, chapter)
        gates = cfg.get("quality_gates", {})
        creative = gates.get("creative_gate", {})
        review = gates.get("review_gate", {})
        return {
            "novel_title": novel.get("title", "未命名"),
            "genre": novel.get("genre", ""),
            "logline": novel.get("logline", ""),
            "pov": novel.get("pov", "第三人称有限视角"),
            "city": setting.get("city", ""),
            "era": setting.get("era", ""),
            "tone": setting.get("tone", ""),
            "themes": "、".join(novel.get("themes", [])) or "（未指定）",
            "style_constraints": "；".join(novel.get("style_constraints", [])) or "（未指定）",
            "chapter": chapter,
            "chapter_title": ch_cfg.get("title", f"第{chapter}章"),
            "phase_name": phase.get("name", ""),
            # 门禁/评审参数
            "min_dimension": creative.get("min_dimension", 50),
            "creative_min_total": creative.get("min_total", 60),
            "min_total": review.get("min_total", 70),
            "min_llm_score": review.get("min_llm_score", 60),
            "rule_weight": review.get("rule_weight", 0.3),
            "llm_weight": review.get("llm_weight", 0.7),
        }

    def system_prompt(self, chapter: int) -> str:
        tpl = Template(self.ctx.read_prompt(self.prompt_name))
        return tpl.safe_substitute(self.template_vars(chapter))

    def user_prompt(self, chapter: int) -> str:  # pragma: no cover - 由子类实现
        raise NotImplementedError

    def build(self, chapter: int):
        return self.system_prompt(chapter), self.user_prompt(chapter)

    # 采样参数
    def temperature(self) -> float:
        return self.ctx.cfg["llm"]["temperature"].get(self.stage_id, 0.5)

    def max_tokens(self) -> int:
        return self.ctx.cfg["llm"]["max_tokens"].get(self.stage_id, 2000)

    # 真实运行后的钩子（子类可覆写：写图谱 / 判定门禁）
    def postprocess(self, raw: str, chapter: int) -> dict:
        return {}

    def describe(self) -> dict:
        return {"id": self.stage_id, "name": self.name}

    # ── 统一运行入口 ──
    def run(self, chapter: int, dry_run: bool) -> dict:
        system, user = self.build(chapter)
        base = {
            "stage": self.stage_id,
            "name": self.name,
            "system": system,
            "user": user,
        }
        if dry_run:
            base["dry_run"] = True
            return base

        raw = self.ctx.llm.chat(system, user,
                                temperature=self.temperature(),
                                max_tokens=self.max_tokens())
        self.ctx.write_output(self.stage_id, chapter, raw)
        hooks = self.postprocess(raw, chapter) or {}
        base["dry_run"] = False
        base["raw"] = raw
        base.update(hooks)
        return base
