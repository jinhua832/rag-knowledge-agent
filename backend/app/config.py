"""
集中配置：所有环境变量都在这里读，其它文件不要直接 os.getenv。
这样做的好处是——想改参数只改 .env，不用去翻代码。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# backend/ 目录（本文件在 backend/app/config.py）
BACKEND_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = BACKEND_DIR.parent

# 读取 backend/.env，没有这个文件也不会报错
load_dotenv(BACKEND_DIR / ".env", override=False)


def _path(env_key: str, default: Path) -> Path:
    """支持相对路径：相对 backend/ 目录解析。"""
    raw = os.getenv(env_key)
    p = Path(raw).expanduser() if raw else default
    return p if p.is_absolute() else (BACKEND_DIR / p).resolve()


class Settings:
    def __init__(self) -> None:
        # ---------- 大模型（任何 OpenAI 兼容接口）----------
        self.llm_base_url = os.getenv("LLM_BASE_URL", "https://api.siliconflow.cn/v1").rstrip("/")
        self.llm_api_key = os.getenv("LLM_API_KEY", "")
        self.llm_model = os.getenv("LLM_MODEL", "Qwen/Qwen2.5-7B-Instruct")
        self.temperature = float(os.getenv("LLM_TEMPERATURE", "0.2"))
        self.max_tokens = int(os.getenv("LLM_MAX_TOKENS", "1024"))
        self.timeout = float(os.getenv("LLM_TIMEOUT", "60"))

        # ---------- 向量化 ----------
        # api   = 调用云端 Embedding 接口（默认，一个 key 搞定，不占本地磁盘）
        # local = 本地 sentence-transformers 模型（免费、可离线，需另装依赖）
        self.embedding_provider = os.getenv("EMBEDDING_PROVIDER", "api").strip().lower()
        self.embedding_base_url = os.getenv("EMBEDDING_BASE_URL", self.llm_base_url).rstrip("/")
        self.embedding_api_key = os.getenv("EMBEDDING_API_KEY") or self.llm_api_key
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.embedding_dim = int(os.getenv("EMBEDDING_DIM", "0"))  # 0 = 自动
        self.local_embedding_model = os.getenv(
            "LOCAL_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"
        )

        # ---------- 切分 ----------
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "400"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "80"))

        # ---------- 检索 ----------
        self.default_top_k = int(os.getenv("TOP_K", "4"))
        self.score_threshold = float(os.getenv("SCORE_THRESHOLD", "0"))

        # ---------- 多轮 ----------
        self.history_turns = int(os.getenv("HISTORY_TURNS", "4"))
        self.enable_rewrite = os.getenv("ENABLE_QUERY_REWRITE", "true").lower() in {
            "1",
            "true",
            "yes",
        }

        # ---------- 目录 ----------
        self.docs_dir = _path("DOCS_DIR", BACKEND_DIR / "data" / "docs")
        self.chroma_dir = _path("CHROMA_DIR", BACKEND_DIR / "chroma_db")
        self.collection_name = os.getenv("COLLECTION_NAME", "knowledge_base")
        self.frontend_dist = _path("FRONTEND_DIST", PROJECT_DIR / "frontend" / "dist")

        # 自动建目录
        self.docs_dir.mkdir(parents=True, exist_ok=True)
        self.chroma_dir.mkdir(parents=True, exist_ok=True)

    # 供 /api/health 展示，注意不要把 key 打出来
    def public_view(self) -> dict:
        return {
            "llm_base_url": self.llm_base_url,
            "llm_model": self.llm_model,
            "llm_key_configured": bool(self.llm_api_key),
            "embedding_provider": self.embedding_provider,
            "embedding_model": (
                self.embedding_model
                if self.embedding_provider == "api"
                else self.local_embedding_model
            ),
            "embedding_key_configured": bool(self.embedding_api_key),
            "chunk_size": self.chunk_size,
            "chunk_overlap": self.chunk_overlap,
            "top_k": self.default_top_k,
        }

    def require_llm_key(self) -> None:
        if not self.llm_api_key:
            raise RuntimeError(
                "没有配置 LLM_API_KEY。请复制 backend/.env.example 为 backend/.env，"
                "然后填入你在模型平台申请的 API Key。"
            )


# 全局唯一实例：其它模块 `from app.config import settings` 直接用
settings = Settings()
