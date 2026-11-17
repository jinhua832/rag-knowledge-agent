"""FastAPI 入口：把 RAG 能力暴露成 HTTP 接口。

启动方式（在 backend/ 目录）：
    uvicorn app.main:app --reload --port 8000
接口文档：http://localhost:8000/docs
"""
from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.rag import vectorstore
from app.rag.chain import service
from app.rag.loader import SUPPORTED_SUFFIXES
from app.schemas import ChatRequest
from app.session import SessionStore

sessions = SessionStore(max_turns=settings.history_turns)
MAX_UPLOAD_BYTES = 15 * 1024 * 1024


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        manifest = vectorstore.ensure_index()
        print(
            f"[startup] 知识库就绪：{len(manifest.get('documents', []))} 个文档 / "
            f"{manifest.get('total_chunks', 0)} 个片段"
        )
    except Exception as exc:
        # 建库失败不阻断启动，方便先看接口文档、再补配置
        print(f"[startup] 建库失败（修好配置后调用 /api/reindex 即可）：{exc}")
    yield


app = FastAPI(title="个人知识库问答 Agent", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==========================================================================
# 基础信息
# ==========================================================================
@app.get("/api/health")
def health() -> dict:
    return {
        "status": "ok",
        "config": settings.public_view(),
        "index": service.stats(),
        "sessions": sessions.count(),
    }


@app.get("/api/documents")
def documents() -> dict:
    return vectorstore.list_documents()


# ==========================================================================
# 对话：流式（前端用）
# ==========================================================================
@app.post("/api/chat")
def chat(req: ChatRequest):
    history = sessions.get(req.session_id) if req.session_id else []

    def event_stream():
        for ev in service.stream(
            question=req.question,
            history=history,
            top_k=req.top_k,
            use_rag=req.use_rag,
        ):
            yield f"event: {ev['event']}\ndata: {json.dumps(ev['data'], ensure_ascii=False)}\n\n"
            if ev["event"] == "done" and req.session_id:
                sessions.append(req.session_id, req.question, ev["data"].get("answer", ""))

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # 关掉 nginx 缓冲，否则流式会被憋住
        },
    )


# ==========================================================================
# 对话：一次性返回（写评测脚本、curl 调试用）
# ==========================================================================
@app.post("/api/chat/sync")
def chat_sync(req: ChatRequest) -> dict:
    history = sessions.get(req.session_id) if req.session_id else []
    result = service.answer(req.question, history, req.top_k, req.use_rag)
    if req.session_id:
        sessions.append(req.session_id, req.question, result["answer"])
    return result


# ==========================================================================
# 检索调试：只跑检索，不调大模型（调切分策略时非常有用）
# ==========================================================================
@app.get("/api/search")
def search_only(q: str, k: int = 4) -> dict:
    if not q.strip():
        raise HTTPException(status_code=400, detail="q 不能为空")
    return {"query": q, "sources": service.retrieve(q, k)}


# ==========================================================================
# 知识库管理
# ==========================================================================
@app.post("/api/reindex")
def reindex() -> dict:
    try:
        result = vectorstore.reindex_all(rebuild=True)
        return {"ok": True, **result}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"重建索引失败：{exc}") from exc


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)) -> dict:
    name = Path(file.filename or "").name
    suffix = Path(name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"只支持 {sorted(SUPPORTED_SUFFIXES)} 格式")

    content = await file.read()
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="文件超过 15MB，请先拆分")

    target = settings.docs_dir / name
    target.write_bytes(content)
    try:
        chunks = vectorstore.index_file(target)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"索引失败：{exc}") from exc
    return {"ok": True, "source": name, "chunks": chunks, **vectorstore.list_documents()}


@app.delete("/api/documents/{name}")
def remove_document(name: str) -> dict:
    safe = Path(name).name
    if not (settings.docs_dir / safe).exists():
        raise HTTPException(status_code=404, detail=f"文档不存在：{safe}")
    vectorstore.delete_document(safe)
    return {"ok": True, **vectorstore.list_documents()}


@app.post("/api/session/{session_id}/reset")
def reset_session(session_id: str) -> dict:
    sessions.clear(session_id)
    return {"ok": True}


# ==========================================================================
# 生产模式：把前端构建产物（frontend/dist）直接由后端托管，一条命令跑全栈
# ==========================================================================
_dist = settings.frontend_dist
if _dist.exists() and (_dist / "index.html").exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")
    print(f"[startup] 已托管前端静态文件：{_dist}")
