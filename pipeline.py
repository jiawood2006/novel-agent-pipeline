#!/usr/bin/env python3
"""多 Agent 小说写作流水线 — 编排引擎入口。

一条命令驱动一章的完整生产：

    p1 context → p2 outline → p3 design → p4 scene
    → p5 gate → p6 draft → p7 editor → p8 absorb(记忆吸收)

7 个 Agent 承担 p1~p7；p8 由四维记忆图谱引擎承担。
引擎本身负责：阶段依赖检查、进度持久化、门禁拦截、dry-run 提示词预览。

用法
----
    # 离线预览：不配置任何 API key，打印每阶段将发送的完整提示词，退出码 0
    python3 pipeline.py --config demo/demo_novel.json --dry-run

    # 真实运行第 1 章（需环境变量 DEEPSEEK_API_KEY 或配置指定的 api_key_env）
    python3 pipeline.py --config demo/demo_novel.json --chapter 1

    # 其它
    python3 pipeline.py --config demo/demo_novel.json --list-stages
    python3 pipeline.py --config demo/demo_novel.json --status
    python3 pipeline.py --config demo/demo_novel.json --chapter 1 --step gate
    python3 pipeline.py --config demo/demo_novel.json --all
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

# 保证从任意目录运行时都能 import 本仓库模块
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import chapter_numbers, get_chapter, load_config, resolve_phase  # noqa: E402
from llm import LLMClient  # noqa: E402
from memory import NovelMemory  # noqa: E402
from agents import (ContextAgent, DesignAgent, DraftAgent, EditorAgent,  # noqa: E402
                    GateAgent, OutlineAgent, SceneAgent)
from agents.base import PipelineContext  # noqa: E402
from gates import parse_llm_json  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(HERE, "prompts")


# ══════════════════════════════════════════════════════
# 阶段定义（p1~p8）
# ══════════════════════════════════════════════════════
STAGES = [
    {"id": "context", "name": "写前检索", "deps": [],
     "output": "context_ch{ch}.md", "agent": ContextAgent,
     "desc": "读整体方向 + 记忆图谱 + 上章结尾 → 生成写前上下文包"},
    {"id": "outline", "name": "章节大纲", "deps": ["context"],
     "output": "outline_ch{ch}.md", "agent": OutlineAgent,
     "desc": "读上下文包 + 本章配置 → 生成含事件链/温度曲线的大纲"},
    {"id": "design", "name": "创意设计", "deps": ["outline"],
     "output": "design_ch{ch}.md", "agent": DesignAgent,
     "desc": "产出场景分段 + 冲突推进 + 伏笔设计（JSON）"},
    {"id": "scene", "name": "场景拆分", "deps": ["design"],
     "output": "scene_ch{ch}.md", "agent": SceneAgent,
     "desc": "拆成 3-5 个场景，标注时间/地点/温度/功能/核心事件"},
    {"id": "gate", "name": "创意门禁", "deps": ["scene"],
     "output": "gate_ch{ch}.json", "agent": GateAgent,
     "desc": "四维评分（结构/漏出/钩子/场景），不达标即拦截"},
    {"id": "draft", "name": "正文初稿", "deps": ["gate"],
     "output": "draft_ch{ch}.md", "agent": DraftAgent,
     "desc": "一次 LLM 调用写完整章所有场景正文"},
    {"id": "editor", "name": "深度评审", "deps": ["draft"],
     "output": "editor_ch{ch}.json", "agent": EditorAgent,
     "desc": "规则引擎初筛 + LLM 五维评审 → 综合评分门禁"},
    {"id": "absorb", "name": "记忆吸收", "deps": ["editor"],
     "output": "absorb_ch{ch}.json", "agent": None, "memory": True,
     "desc": "从正文提取事件/角色/线索/主题，写回四维记忆图谱"},
]
STAGE_BY_ID = {s["id"]: s for s in STAGES}


# ══════════════════════════════════════════════════════
# 记忆吸收阶段（由记忆引擎承担，不是「写作 Agent」）
# ══════════════════════════════════════════════════════
class MemoryAbsorbStage:
    """p8：把第 N 章正文结构化吸收进四维记忆图谱。"""

    stage_id = "absorb"
    name = "记忆吸收"
    prompt_name = "absorb"

    def __init__(self, ctx: PipelineContext):
        self.ctx = ctx

    def _system_prompt(self, chapter: int) -> str:
        from string import Template
        novel = self.ctx.cfg.get("novel", {})
        tpl = Template(self.ctx.read_prompt(self.prompt_name))
        return tpl.safe_substitute(novel_title=novel.get("title", "未命名"),
                                   chapter=chapter)

    def _user_prompt(self, chapter: int) -> str:
        text = self.ctx.read_output("editor", chapter) or self.ctx.read_output("draft", chapter)
        if text:
            body = text[:6000]
        else:
            body = f"（上游产物 draft_ch{chapter}.md 尚未生成——dry-run 占位）"
        return f"## 第 {chapter} 章全文\n{body}\n\n请提取并分析以上内容。"

    def build(self, chapter: int):
        return self._system_prompt(chapter), self._user_prompt(chapter)

    def run(self, chapter: int, dry_run: bool) -> dict:
        system, user = self.build(chapter)
        out = {"stage": self.stage_id, "name": self.name, "system": system, "user": user}
        if dry_run:
            out["dry_run"] = True
            return out

        raw = self.ctx.llm.chat(system, user,
                                temperature=self.ctx.cfg["llm"]["temperature"]["absorb"],
                                max_tokens=self.ctx.cfg["llm"]["max_tokens"]["absorb"])
        data = parse_llm_json(raw)
        self.ctx.write_output(self.stage_id, chapter, json.dumps(data, ensure_ascii=False, indent=2))
        self.ingest(data, chapter)
        out["dry_run"] = False
        out["raw"] = raw
        return out

    def ingest(self, data: dict, chapter: int):
        """Fast Path 写入：事件→时间图谱，线索→因果图谱，角色/主题→实体/语义图谱。"""
        mem = self.ctx.memory
        for ev in data.get("events", []) or []:
            nid = f"Ch{chapter}·{ev.get('order', '?')}"
            mem["temporal"].add_node(nid, type="event", chapter=chapter,
                                     description=ev.get("description", ""),
                                     location=ev.get("location", ""))
        for thread in data.get("open_threads", []) or []:
            mem["causal"].add_node(thread, type="plot_thread", status="open",
                                   opened_in=chapter)
        for name in data.get("new_characters", []) or []:
            mem["entity"].add_node(name, type="character", first_seen=chapter)
        for theme in data.get("themes", []) or []:
            mem["semantic"].add_node(theme, type="theme", chapter=chapter)
        mem.save(os.path.join(self.ctx.output_dir, "memory.json"))


# ══════════════════════════════════════════════════════
# 进度持久化
# ══════════════════════════════════════════════════════
def progress_path(output_dir: str) -> str:
    return os.path.join(output_dir, "progress.json")


def load_progress(output_dir: str) -> dict:
    path = progress_path(output_dir)
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_progress(output_dir: str, data: dict):
    with open(progress_path(output_dir), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def mark(output_dir: str, chapter: int, stage_id: str, status: str, info: dict = None):
    data = load_progress(output_dir)
    data.setdefault(str(chapter), {})[stage_id] = {
        "status": status,
        "at": datetime.now().isoformat(timespec="seconds"),
        "info": info or {},
    }
    save_progress(output_dir, data)


def stage_output_path(output_dir: str, stage: dict, chapter: int) -> str:
    return os.path.join(output_dir, stage["output"].replace("{ch}", str(chapter)))


def deps_satisfied(output_dir: str, chapter: int, stage: dict) -> tuple:
    for dep_id in stage.get("deps", []):
        dep = STAGE_BY_ID.get(dep_id)
        if not dep:
            continue
        if os.path.exists(stage_output_path(output_dir, dep, chapter)):
            continue
        return False, dep_id
    return True, None


# ══════════════════════════════════════════════════════
# 运行一章
# ══════════════════════════════════════════════════════
def run_chapter(ctx: PipelineContext, chapter: int, dry_run: bool,
                only_step: str = None, from_step: str = None) -> bool:
    cfg = ctx.cfg
    out_dir = ctx.output_dir

    print("\n" + "#" * 68)
    title = get_chapter(cfg, chapter).get("title", f"第{chapter}章")
    print(f"# 第 {chapter} 章《{title}》 · 阶段：{resolve_phase(cfg, chapter).get('name', '')}")
    print("#" * 68)

    start_idx = 0
    if from_step:
        if from_step not in STAGE_BY_ID:
            print(f"[错误] 未知阶段 '{from_step}'")
            return False
        start_idx = [s["id"] for s in STAGES].index(from_step)

    stages = STAGES[start_idx:]
    if only_step:
        if only_step not in STAGE_BY_ID:
            print(f"[错误] 未知阶段 '{only_step}'")
            return False
        stages = [STAGE_BY_ID[only_step]]

    ok = True
    for stage in stages:
        if not ok:
            print("  [中断] 上游失败，流水线终止")
            break

        sid = stage["id"]
        agent = (MemoryAbsorbStage(ctx) if stage.get("memory")
                 else stage["agent"](ctx))

        print("\n" + "─" * 68)
        print(f">>> [{sid}] {stage['name']}")
        print(f"    {stage['desc']}")
        print(f"    产出 → {os.path.basename(stage_output_path(out_dir, stage, chapter))}")

        # 依赖检查（dry-run 跳过，方便单独预览）
        if not dry_run:
            ok_dep, missing = deps_satisfied(out_dir, chapter, stage)
            if not ok_dep:
                print(f"    [BLOCKED] 依赖未满足：'{missing}' 的产出不存在")
                ok = False
                continue

        try:
            result = agent.run(chapter, dry_run)
        except Exception as exc:  # noqa: BLE001
            print(f"    [FAIL] {type(exc).__name__}: {exc}")
            if not dry_run:
                mark(out_dir, chapter, sid, "failed", {"error": str(exc)})
            ok = False
            continue

        # ── dry-run：打印组装好的完整提示词 ──
        if dry_run:
            print(f"\n    ┌─ SYSTEM PROMPT（{len(result['system'])} 字符）")
            for line in result["system"].rstrip().splitlines():
                print(f"    │ {line}")
            print(f"    └─")
            print(f"\n    ┌─ USER PROMPT（{len(result['user'])} 字符）")
            for line in result["user"].rstrip().splitlines():
                print(f"    │ {line}")
            print(f"    └─")
            print("    [DRY-RUN] 未调用 LLM —— 以上即真实运行时会发送的完整提示词")
            continue

        # ── 真实运行：回报结果 / 门禁 ──
        gate = result.get("gate")
        if gate and gate.get("passed") is False:
            print(f"    [门禁 FAIL] {gate.get('reason', '')}")
            mark(out_dir, chapter, sid, "failed", gate)
            ok = False
            continue
        if gate and gate.get("passed") is True:
            print(f"    [门禁 PASS] 综合分 {gate.get('combined_score', gate.get('total_score'))}")
        mark(out_dir, chapter, sid, "done",
             {"bytes": len(result.get("raw", ""))})
        print(f"    [OK] 完成（{len(result.get('raw', ''))} 字符）")

    # 汇总
    if not dry_run:
        progress = load_progress(out_dir).get(str(chapter), {})
        done = sum(1 for s in STAGES if progress.get(s["id"], {}).get("status") == "done")
        print("\n" + "=" * 68)
        print(f"  第 {chapter} 章：{done}/{len(STAGES)} 阶段完成")
        print(f"  状态：{'全流程完成 ✅' if done == len(STAGES) else '部分完成'}")
        print("=" * 68)
    return ok


def print_stage_plan(cfg: dict):
    print("\n【阶段计划】")
    print(f"  {'阶段':<4}{'Agent/引擎':<22}{'依赖':<14}{'产出'}")
    print("  " + "-" * 62)
    for i, s in enumerate(STAGES, 1):
        who = s.get("agent").__name__ if s.get("agent") else "MemoryEngine"
        deps = ",".join(s["deps"]) if s["deps"] else "—"
        print(f"  p{i:<3}{s['name'] + '（' + who + '）':<22}{deps:<14}{s['output']}")


def show_status(cfg: dict):
    out_dir = cfg["output_dir"]
    progress = load_progress(out_dir)
    print(f"\n进度文件：{progress_path(out_dir)}")
    for ch in chapter_numbers(cfg):
        state = progress.get(str(ch), {})
        print(f"\n  [第 {ch} 章]")
        for s in STAGES:
            st = state.get(s["id"], {}).get("status", "待执行")
            icon = {"done": "OK ", "failed": "FAIL"}.get(st, "  ..")
            print(f"    [{icon}] {s['id']:<10} {st}")


# ══════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(
        description="多 Agent 小说写作流水线（配置驱动，支持离线 dry-run）")
    parser.add_argument("--config", "-c", required=True, help="小说配置文件路径")
    parser.add_argument("--chapter", type=int, help="指定章节号")
    parser.add_argument("--chapters", help="章节号列表，如 1,2,3")
    parser.add_argument("--all", action="store_true", help="跑配置中所有章节")
    parser.add_argument("--step", help="只跑某个阶段（如 gate）")
    parser.add_argument("--from", dest="from_step", help="从某阶段开始")
    parser.add_argument("--dry-run", action="store_true", help="只打印将要发送的提示词，不调用 LLM")
    parser.add_argument("--list-stages", action="store_true", help="列出阶段与依赖")
    parser.add_argument("--status", action="store_true", help="查看进度")
    args = parser.parse_args()

    cfg = load_config(args.config)
    novel = cfg.get("novel", {})
    out_dir = cfg["output_dir"]

    # 初始化记忆图谱（从配置播种；如已有 memory.json 则加载）
    memory = NovelMemory()
    memory.seed_from_config(cfg)
    mem_file = os.path.join(out_dir, "memory.json")
    if os.path.exists(mem_file):
        memory.load(mem_file)

    llm = LLMClient(cfg["llm"])

    print("=" * 68)
    print(" 多 Agent 小说写作流水线" + ("（DRY-RUN 预览）" if args.dry_run else ""))
    print("=" * 68)
    print(f" 书名   : {novel.get('title', '未命名')}")
    print(f" 类型   : {novel.get('genre', '')}    视角：{novel.get('pov', '')}")
    print(f" 配置   : {cfg['_config_path']}")
    print(f" 输出   : {out_dir}")
    print(f" 模型   : {cfg['llm']['model']} @ {cfg['llm']['base_url']}")
    print(f" 记忆图谱 : {json.dumps(memory.summary(), ensure_ascii=False)}")

    # ── 只列出阶段 ──
    if args.list_stages:
        print_stage_plan(cfg)
        return 0

    # ── 查看进度 ──
    if args.status:
        show_status(cfg)
        return 0

    # 决定要跑哪些章节
    if args.chapter:
        targets = [args.chapter]
    elif args.chapters:
        targets = [int(x) for x in args.chapters.split(",") if x.strip()]
    elif args.all:
        targets = chapter_numbers(cfg)
    else:
        targets = chapter_numbers(cfg)[:1]  # 默认：配置里的第一章

    ctx = PipelineContext(cfg, llm, memory, PROMPTS_DIR, out_dir, dry_run=args.dry_run)

    if not args.dry_run and not llm.available():
        print("\n[提示] 未检测到可用 LLM：" + llm.unavailable_reason())
        print("       如需离线预览请加 --dry-run；真实运行需配置密钥。")

    print_stage_plan(cfg)

    all_ok = True
    for ch in targets:
        ok = run_chapter(ctx, ch, args.dry_run, only_step=args.step, from_step=args.from_step)
        all_ok = all_ok and ok

    if args.dry_run:
        print("\n" + "=" * 68)
        print("  DRY-RUN 完成：以上为各阶段将发送的完整提示词，未调用任何 LLM。")
        print("=" * 68)
        return 0

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
