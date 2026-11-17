"""Chroma 向量库的封装：建库、增量索引、删除、文档清单。

索引层只做一件事：让「一句中文问题」能快速找到「最相关的几个片段」。
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings
from app.rag.embedder import get_embeddings
from app.rag.loader import SUPPORTED_SUFFIXES, load_corpus, load_file, split_documents

_store: Chroma | None = None
MANIFEST_NAME = "manifest.json"


# --------------------------------------------------------------------------
# 向量库单例
# --------------------------------------------------------------------------
def get_vectorstore() -> Chroma:
    global _store
    if _store is None:
        _store = Chroma(
            collection_name=settings.collection_name,
            embedding_function=get_embeddings(),
            persist_directory=str(settings.chroma_dir),
            # 用余弦相似度：文本向量经过归一化后，余弦是最合适的度量
            collection_metadata={"hnsw:space": "cosine"},
        )
    return _store


def reset_store() -> None:
    """删掉整个集合，下次调用时重新创建（重建索引时用）。"""
    global _store
    store = get_vectorstore()
    try:
        store._client.delete_collection(settings.collection_name)
    except Exception:
        pass
    _store = None


# --------------------------------------------------------------------------
# 文档清单 manifest.json：给前端展示「知识库里有什么」
# --------------------------------------------------------------------------
def manifest_path() -> Path:
    return settings.chroma_dir / MANIFEST_NAME


def load_manifest() -> dict[str, Any]:
    p = manifest_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"updated_at": "", "documents": [], "total_chunks": 0, "embedding": {}}


def save_manifest(data: dict[str, Any]) -> None:
    manifest_path().write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _manifest_doc(path: Path, chunks: int) -> dict[str, Any]:
    stat = path.stat()
    return {
        "source": path.name,
        "size": stat.st_size,
        "chunks": chunks,
        "updated_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
    }


# --------------------------------------------------------------------------
# 索引
# --------------------------------------------------------------------------
def _delete_source(source: str) -> None:
    """同一份文件重新索引前，先删旧片段，避免内容重复/陈旧。"""
    store = get_vectorstore()
    try:
        existing = store.get(where={"source": source}, include=["metadatas"])
        ids = existing.get("ids") or []
        if ids:
            store.delete(ids=ids)
    except Exception as exc:  # 空集合时某些 Chroma 版本会抛异常
        print(f"[warn] 清理旧片段失败 {source}: {exc}")


def index_file(path: Path) -> int:
    """索引单个文件，返回切出的片段数。"""
    docs = split_documents(load_file(path))
    if not docs:
        return 0
    _delete_source(path.name)
    store = get_vectorstore()
    ids = [f"{path.name}::{d.metadata.get('chunk_index', i)}" for i, d in enumerate(docs)]
    store.add_documents(documents=docs, ids=ids)

    manifest = load_manifest()
    docs_meta = manifest.get("documents", [])
    entry = _manifest_doc(path, len(docs))
    docs_meta = [d for d in docs_meta if d["source"] != path.name] + [entry]
    manifest["documents"] = sorted(docs_meta, key=lambda x: x["source"])
    manifest["total_chunks"] = sum(d["chunks"] for d in manifest["documents"])
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["embedding"] = {
        "provider": settings.embedding_provider,
        "model": settings.embedding_model
        if settings.embedding_provider == "api"
        else settings.local_embedding_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }
    save_manifest(manifest)
    return len(docs)


def reindex_all(rebuild: bool = True) -> dict[str, Any]:
    """把 data/docs 整个目录重建一遍。"""
    if rebuild:
        reset_store()
        save_manifest({"updated_at": "", "documents": [], "total_chunks": 0, "embedding": {}})

    files = [p for p in sorted(settings.docs_dir.rglob("*")) if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    total = 0
    manifest = load_manifest()
    entries: list[dict[str, Any]] = []
    for path in files:
        try:
            docs = split_documents(load_file(path))
            if not docs:
                continue
            ids = [f"{path.name}::{d.metadata.get('chunk_index', i)}" for i, d in enumerate(docs)]
            # 分批写入，避免一次请求过大（也方便看进度）
            store = get_vectorstore()
            batch = 64
            for start in range(0, len(docs), batch):
                store.add_documents(documents=docs[start : start + batch], ids=ids[start : start + batch])
            total += len(docs)
            entries.append(_manifest_doc(path, len(docs)))
        except Exception as exc:
            print(f"[error] 索引失败 {path.name}: {exc}")

    manifest["documents"] = entries
    manifest["total_chunks"] = total
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    manifest["embedding"] = {
        "provider": settings.embedding_provider,
        "model": settings.embedding_model
        if settings.embedding_provider == "api"
        else settings.local_embedding_model,
        "chunk_size": settings.chunk_size,
        "chunk_overlap": settings.chunk_overlap,
    }
    save_manifest(manifest)
    return {"documents": len(entries), "chunks": total, "files": [e["source"] for e in entries]}


def delete_document(source: str) -> bool:
    _delete_source(source)
    manifest = load_manifest()
    docs_meta = [d for d in manifest.get("documents", []) if d["source"] != source]
    manifest["documents"] = docs_meta
    manifest["total_chunks"] = sum(d["chunks"] for d in docs_meta)
    manifest["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_manifest(manifest)
    path = settings.docs_dir / source
    if path.exists():
        path.unlink()
    return True


def ensure_index() -> dict[str, Any]:
    """启动时调用：如果库是空的但文档目录有文件，就自动建库（新手少踩一个坑）。"""
    manifest = load_manifest()
    if manifest.get("documents"):
        return manifest
    files = [p for p in settings.docs_dir.rglob("*") if p.is_file() and p.suffix.lower() in SUPPORTED_SUFFIXES]
    if not files:
        return manifest
    print(f"[index] 首次启动，正在为 {len(files)} 个文档建库…")
    reindex_all(rebuild=True)
    return load_manifest()


def list_documents() -> dict[str, Any]:
    m = load_manifest()
    return {
        "documents": m.get("documents", []),
        "total_chunks": m.get("total_chunks", 0),
        "updated_at": m.get("updated_at", ""),
        "embedding": m.get("embedding", {}),
    }


def search(query: str, top_k: int | None = None) -> list[tuple[Document, float]]:
    """向量检索，返回 (片段, 相似度) 列表。"""
    store = get_vectorstore()
    k = top_k or settings.default_top_k
    try:
        return store.similarity_search_with_relevance_scores(
            query,
            k=k,
            score_threshold=settings.score_threshold or None,
        )
    except Exception as exc:
        # 某些 Chroma 版本对 relevance score 支持不好，降级为纯相似度检索
        print(f"[warn] relevance score 不可用，降级检索: {exc}")
        docs = store.similarity_search(query, k=k)
        return [(d, 0.0) for d in docs]
