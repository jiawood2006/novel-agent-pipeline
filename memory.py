"""MAGMA 四维图谱记忆体（Novel Memory Graph）。

设计灵感来自 MAGMA 论文（多图记忆架构）：把小说记忆拆成四个**正交**图谱，
各管一件事，互相不污染——

    图谱        小说里对应什么             解决的一致性问题
    ──────────────────────────────────────────────────────
    实体图谱    人物关系网                 角色关系/状态/设定不漂移
    时间图谱    故事时间线                 事件先后、闪回、并行不出错
    因果图谱    伏笔 → 回收链路            埋的线有人收、动机链不断
    语义图谱    主题/世界观/写作约束       主题不跑偏、设定规则不被违反

存储
----
纯 JSON（`{nodes, edges}`），**零第三方依赖即可读写**；装了 `networkx`
时可用 `to_networkx()` 做图分析。这样保证离线 `--dry-run` 也能跑。

写入时机
--------
- 「Fast Path」：每章吸收（p8）后立即写入事件/实体/线索（确定性、快）。
- 「Slow Path」：空闲时由 LLM 做因果推理、主题提炼（可选、异步）。
本模块只提供数据结构与读写/检索接口，不负责调用 LLM。
"""

from __future__ import annotations

import json
import os


class Graph:
    """极简有向图：节点是 dict，边是带 relation 的列表。"""

    def __init__(self, kind: str):
        self.kind = kind
        self.nodes = {}   # id -> {attrs}
        self.edges = []   # [{source, target, relation, ...}]

    def add_node(self, node_id: str, **attrs):
        node = self.nodes.setdefault(node_id, {})
        node.update(attrs)

    def add_edge(self, source: str, target: str, relation: str = "", **attrs):
        self.edges.append({"source": source, "target": target,
                           "relation": relation, **attrs})

    def neighbors(self, node_id: str):
        """返回与 node_id 直接相连的 (对方节点, 关系, 方向) 列表。"""
        out = []
        for e in self.edges:
            if e["source"] == node_id:
                out.append((e["target"], e.get("relation", ""), "out"))
            elif e["target"] == node_id:
                out.append((e["source"], e.get("relation", ""), "in"))
        return out

    def to_dict(self):
        return {"kind": self.kind, "nodes": self.nodes, "edges": self.edges}

    @classmethod
    def from_dict(cls, data: dict) -> "Graph":
        g = cls(data.get("kind", "graph"))
        g.nodes = data.get("nodes", {})
        g.edges = data.get("edges", [])
        return g


class NovelMemory:
    """四维图谱记忆体。"""

    GRAPHS = ("entity", "temporal", "causal", "semantic")

    def __init__(self):
        self.graphs = {k: Graph(k) for k in self.GRAPHS}

    # ── 便捷访问 ──
    def __getitem__(self, kind: str) -> Graph:
        return self.graphs[kind]

    # ── 从小说配置播种初始记忆 ──
    def seed_from_config(self, cfg: dict):
        """把配置里的角色/主题/世界观播种进图谱。

        这只是让演示能跑起来的「最小种子」。真实项目应在建库阶段
        从完整的人物卡、世界观文档、已写章节正文批量吸收。
        """
        novel = cfg.get("novel", {})

        # 实体图谱：角色 + 关系
        for ch in cfg.get("characters", []):
            name = ch.get("name")
            if not name:
                continue
            self["entity"].add_node(
                name,
                type="character",
                role=ch.get("role", ""),
                identity=ch.get("identity", ""),
                traits=ch.get("traits", ""),
                voice=ch.get("voice", ""),
            )
        for rel in cfg.get("relationships", []):
            self["entity"].add_edge(
                rel.get("a", ""), rel.get("b", ""),
                relation=rel.get("relation", ""),
                strength=rel.get("strength", 0.5),
            )

        # 语义图谱：主题 + 写作约束 + 世界观
        for theme in novel.get("themes", []):
            self["semantic"].add_node(theme, type="theme")
        for rule in novel.get("style_constraints", []):
            self["semantic"].add_node(rule, type="writing_rule")
        setting = novel.get("setting", {})
        if setting.get("city"):
            self["semantic"].add_node(
                f"地点·{setting['city']}", type="worldbuilding",
                era=setting.get("era", ""), tone=setting.get("tone", ""))

        # 时间图谱：阶段划分
        for phase in cfg.get("phases", []):
            self["temporal"].add_node(
                f"阶段{phase.get('id')}·{phase.get('name')}", type="phase",
                start_chapter=phase.get("start_chapter"),
                end_chapter=phase.get("end_chapter"))

    # ── 写前检索 ──
    def query_for_chapter(self, chapter: int, cfg: dict) -> dict:
        """给「写第 N 章」返回一个记忆摘要包。

        真实实现会按章做图遍历（出场角色/近期事件/未闭合线索/活跃主题）；
        这里给出与四维图谱一一对应的稳定结构。
        """
        return {
            "characters": [
                {"name": n, "role": a.get("role", ""), "identity": a.get("identity", "")}
                for n, a in self["entity"].nodes.items() if a.get("type") == "character"
            ],
            "relationships": [
                {"a": e["source"], "b": e["target"], "relation": e.get("relation", "")}
                for e in self["entity"].edges
            ],
            "recent_events": [
                {"name": n, "attrs": a}
                for n, a in self["temporal"].nodes.items()
            ],
            "open_threads": [
                {"name": n, "attrs": a}
                for n, a in self["causal"].nodes.items() if a.get("status") == "open"
            ],
            "active_themes": [
                n for n, a in self["semantic"].nodes.items() if a.get("type") == "theme"
            ],
            "rules": [
                n for n, a in self["semantic"].nodes.items() if a.get("type") == "writing_rule"
            ],
        }

    def summary(self) -> dict:
        return {
            kind: {"nodes": len(g.nodes), "edges": len(g.edges)}
            for kind, g in self.graphs.items()
        }

    # ── 持久化 ──
    def save(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({k: g.to_dict() for k, g in self.graphs.items()},
                      f, ensure_ascii=False, indent=2)

    def load(self, path: str) -> bool:
        if not os.path.exists(path):
            return False
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for kind in self.GRAPHS:
            if kind in data:
                self.graphs[kind] = Graph.from_dict(data[kind])
        return True

    # ── 可选：转 networkx 做图分析 ──
    def to_networkx(self):
        """装了 networkx 时，把四个图谱各自转成 nx.DiGraph（高级分析用）。"""
        try:
            import networkx as nx
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("需要 networkx：pip install networkx") from exc
        result = {}
        for kind, g in self.graphs.items():
            dg = nx.DiGraph()
            for n, a in g.nodes.items():
                dg.add_node(n, **a)
            for e in g.edges:
                dg.add_edge(e["source"], e["target"], relation=e.get("relation", ""))
            result[kind] = dg
        return result
