"""pytest 公共配置：保证测试里能 import app.*，并且默认不依赖外部 API。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

# 测试默认走本地向量模型，避免 CI 里没有云端 key
os.environ.setdefault("EMBEDDING_PROVIDER", "local")
os.environ.setdefault("CHROMA_DIR", str(BACKEND_DIR / ".pytest_chroma"))
