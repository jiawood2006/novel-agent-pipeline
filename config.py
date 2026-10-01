"""配置加载与默认值补全。

本框架是「配置驱动」的：一部小说 = 一个 JSON 配置文件（+ 可选的世界观/人物补充文档）。
`load_config()` 负责读取配置、递归补全默认值、并解析输出目录。
"""

from __future__ import annotations

import copy
import json
import os

# ── 默认配置（配置文件里没写的项会自动使用这里的值） ──
DEFAULTS = {
    "output_dir": "output",
    "llm": {
        # 任何 OpenAI 兼容接口都可以：DeepSeek / OpenAI / 本地 vLLM / Ollama 等
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        # 只从「环境变量」读取密钥，绝不写死在仓库里
        "key_env": "DEEPSEEK_API_KEY",
        # 逐阶段的采样参数：结构化输出用低温，创作输出用高温
        "temperature": {
            "context": 0.5,
            "outline": 0.5,
            "design": 0.6,
            "scene": 0.5,
            "gate": 0.3,
            "draft": 0.8,
            "editor": 0.3,
            "absorb": 0.3,
        },
        "max_tokens": {
            "context": 3000,
            "outline": 2500,
            "design": 3000,
            "scene": 3000,
            "gate": 2000,
            "draft": 4000,
            "editor": 2000,
            "absorb": 2500,
        },
    },
    "quality_gates": {
        # 创意门禁（p5）：四维评分
        "creative_gate": {"min_total": 60, "min_dimension": 50},
        # 评审门禁（p7）：规则引擎 × 权重 + LLM 评分 × 权重
        "review_gate": {
            "min_total": 70,
            "min_llm_score": 60,
            "rule_weight": 0.3,
            "llm_weight": 0.7,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """把 override 递归合并进 base 的副本（override 优先）。"""
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def load_config(path: str) -> dict:
    """读取小说配置并补全默认值。

    返回的 dict 一定包含：novel / chapters / llm / quality_gates / output_dir。
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"找不到配置文件：{path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    cfg = _deep_merge(DEFAULTS, raw)

    # novel 段的必填校验
    if "novel" not in cfg:
        raise ValueError("配置缺少 `novel` 段（小说元信息）")
    if "chapters" not in cfg and "chapters_file" not in cfg:
        raise ValueError("配置缺少 `chapters` 段或 `chapters_file` 指向的章节文件")

    # 支持把章节单独放一个文件（方便长篇维护）
    if "chapters" not in cfg and "chapters_file" in cfg:
        chapters_path = os.path.join(os.path.dirname(os.path.abspath(path)), cfg["chapters_file"])
        with open(chapters_path, "r", encoding="utf-8") as f:
            cfg["chapters"] = json.load(f)

    # 输出目录：相对配置文件所在目录解析
    base_dir = os.path.dirname(os.path.abspath(path))
    if not os.path.isabs(cfg["output_dir"]):
        cfg["output_dir"] = os.path.normpath(os.path.join(base_dir, cfg["output_dir"]))

    cfg["_config_path"] = os.path.abspath(path)
    return cfg


def chapter_numbers(cfg: dict) -> list:
    """返回配置中声明的章节号（升序整数列表）。"""
    return sorted(int(k) for k in cfg.get("chapters", {}).keys())


def get_chapter(cfg: dict, chapter: int) -> dict:
    """取某一章的配置块（不存在时返回空 dict）。"""
    return cfg.get("chapters", {}).get(str(chapter), {})


def resolve_phase(cfg: dict, chapter: int) -> dict:
    """根据阶段表把章节号映射到阶段（入局/深潜/…）。"""
    for phase in cfg.get("phases", []):
        if phase.get("start_chapter", 1) <= chapter <= phase.get("end_chapter", 0):
            return phase
    return {"id": 0, "name": "未划分", "start_chapter": chapter, "end_chapter": chapter}
