"""全局配置 — 对应 Claude Code 的 config 体系 + settings.json。

使用 pydantic-settings 从 .env 和环境变量读取。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── LLM ──
    llm_provider: str = "deepseek"
    llm_api_key: str = ""
    llm_model: str = "deepseek-v4-pro"
    llm_base_url: Optional[str] = "https://api.deepseek.com/v1"
    temperature: float = 0.0

    # ── Agent 行为 ──
    max_steps: int = 50
    permission_mode: str = "auto"  # auto | manual | plan

    # ── 项目路径 ──
    project_root: Optional[str] = None

    # ── Git ──
    auto_commit: bool = False

    # ── 沙箱 ──
    sandbox_mode: str = "off"  # off | default | strict
    sandbox_writable: str = ""  # 逗号分隔的可写路径白名单

    # ── 四脑 ──
    brain_type: str = ""  # dev_explorer | dev_validator | knowledge_explorer | deploy_planner

    # ── 知识库 ──
    knowledge_dir: str = ".mai/knowledge"
    chroma_persist_dir: str = ".mai/chroma"

    # ── 飞书 ──
    feishu_app_id: str = ""
    feishu_app_secret: str = ""

    def validate(self) -> None:
        if not self.llm_api_key:
            raise RuntimeError(
                "LLM_API_KEY 未设置。请在 .env 或环境变量中配置。"
            )


@lru_cache(maxsize=1)
def get_config() -> Config:
    """全局配置单例"""
    return Config()
