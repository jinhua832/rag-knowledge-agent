"""接口的请求/响应模型（Pydantic 会自动做校验和类型转换）。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=2000, description="用户问题")
    session_id: str | None = Field(default=None, description="会话 ID，用于多轮上下文")
    top_k: int | None = Field(default=None, ge=1, le=10, description="检索片段数量")
    use_rag: bool = Field(default=True, description="false 时走「直接提问」对照组")


class SourceItem(BaseModel):
    id: int
    source: str
    section: str = ""
    score: float = 0.0
    content: str


class ChatResponse(BaseModel):
    answer: str
    sources: list[SourceItem] = []
    standalone_question: str = ""
    latency_ms: int = 0
    cited_ids: list[int] = []
