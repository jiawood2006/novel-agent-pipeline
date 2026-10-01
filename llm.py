"""LLM 客户端封装（OpenAI 兼容接口）。

设计原则
--------
1. 密钥只从环境变量读取（配置项 `llm.key_env` 指定变量名），绝不写死、绝不读私有文件。
2. 未安装 `openai` 或未设置密钥时，`available()` 返回 False；
   `--dry-run` 模式完全不需要真实调用，因此零依赖即可运行。
3. 上层（Agent）只依赖 `chat(system, user, ...)` 这一个方法，方便替换后端。
"""

from __future__ import annotations

import os


class LLMClient:
    """极薄的 OpenAI 兼容客户端。"""

    def __init__(self, llm_cfg: dict):
        self.base_url = llm_cfg.get("base_url")
        self.model = llm_cfg.get("model")
        self.key_env = llm_cfg.get("key_env", "OPENAI_KEY")
        self._client = None

    # ── 可用性检查 ──
    @property
    def key(self) -> str:
        return os.environ.get(self.key_env, "")

    @staticmethod
    def _sdk():
        try:
            import openai  # noqa: F401
            return openai
        except ImportError:
            return None

    def available(self) -> bool:
        """有密钥、且装了 openai SDK 时才算可用。"""
        return bool(self.key) and self._sdk() is not None

    def unavailable_reason(self) -> str:
        if self._sdk() is None:
            return "未安装 openai SDK（pip install -r requirements.txt）"
        if not self.key:
            return f"未设置环境变量 {self.key_env}"
        return ""

    # ── 真实调用 ──
    def chat(self, system: str, user: str, temperature: float = 0.5,
             max_tokens: int = 2000) -> str:
        sdk = self._sdk()
        if sdk is None:
            raise RuntimeError("未安装 openai SDK，请先 `pip install -r requirements.txt`")
        if not self.key:
            raise RuntimeError(f"未设置环境变量 {self.key_env}（真实运行需要密钥）")
        if self._client is None:
            self._client = sdk.OpenAI(api_key=self.key, base_url=self.base_url)
        resp = self._client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content
