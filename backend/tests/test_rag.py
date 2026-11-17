"""核心链路的单元测试。

跑法（在 backend/ 目录）：
    python -m pytest -v
    python -m pytest -v -m "not slow"   # 跳过需要加载向量模型的慢用例
"""
from __future__ import annotations

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from app.rag import chain as chain_module
from app.rag.loader import load_corpus
from app.rag.prompts import format_context
from app.session import SessionStore


# ---------------------------------------------------------------- 切分
def test_split_keeps_source_and_section():
    """每个片段都要带上「文件名 + 章节」，这是引用可回溯的前提。"""
    chunks = load_corpus()
    assert chunks, "没有切出任何片段"
    for c in chunks:
        assert c.metadata["source"].endswith(".md")
        assert "chunk_index" in c.metadata
    # 至少有一部分片段带章节标题（Markdown 文档应该都有）
    assert sum(1 for c in chunks if c.metadata.get("section")) > 0


def test_chunk_size_is_bounded():
    chunks = load_corpus()
    # 允许 overlap 带来的少量溢出，但不应该出现整篇文档当一块的情况
    assert max(len(c.page_content) for c in chunks) < 1200


# ---------------------------------------------------------------- Prompt
def test_context_format_has_numbered_sources():
    sources = [
        {"id": 1, "source": "员工手册.md", "section": "二、假期制度 > 2.1 年假", "content": "满 3 年 10 天"},
        {"id": 2, "source": "产品FAQ.md", "section": "", "content": "Pro 版 68 元/年"},
    ]
    text = format_context(sources)
    assert "[1] 来源：《员工手册.md》 · 二、假期制度 > 2.1 年假" in text
    assert "[2] 来源：《产品FAQ.md》" in text
    assert "满 3 年 10 天" in text


def test_empty_context_has_explicit_hint():
    assert "没有检索到" in format_context([])


# ---------------------------------------------------------------- 引用
def test_cited_ids_filters_unknown_and_dedupes():
    sources = [{"id": 1, "source": "a.md", "content": "x"}, {"id": 2, "source": "b.md", "content": "y"}]
    assert chain_module.RagService.cited_ids("结论 A[1]，结论 B[2][1]，还有个不存在的[9]", sources) == [1, 2]
    assert chain_module.RagService.cited_ids("没有任何引用", sources) == []


# ---------------------------------------------------------------- 会话
def test_session_store_trims_history():
    store = SessionStore(max_turns=2)
    for i in range(3):
        store.append("s1", f"q{i}", f"a{i}")
    history = store.get("s1")
    assert len(history) == 4  # 2 轮 = 4 条消息
    assert history[0]["content"] == "q1"
    store.clear("s1")
    assert store.get("s1") == []


# ---------------------------------------------------------------- 端到端（用假模型，不花 token）
class _FakeLLM(FakeListChatModel):
    pass


def test_answer_pipeline_with_fake_llm(monkeypatch):
    """固定检索结果 + 假模型，验证「检索 → 拼 Prompt → 生成 → 回填引用」的接线是否正确。"""
    fake_docs = [
        (
            Document(
                page_content="累计工龄满 3 年不满 5 年的员工，年假 10 天。",
                metadata={"source": "员工手册.md", "section": "二、假期制度 > 2.1 年假"},
            ),
            0.82,
        )
    ]
    monkeypatch.setattr(chain_module, "search", lambda q, k=None: fake_docs)

    svc = chain_module.RagService()
    fake = _FakeLLM(responses=["满 3 年的员工有 10 天年假[1]。"])
    monkeypatch.setattr(type(svc), "llm", property(lambda self: fake))

    result = svc.answer("入职满 3 年有几天年假？", history=[], top_k=1, use_rag=True)
    assert "10 天" in result["answer"]
    assert len(result["sources"]) == 1
    assert result["sources"][0]["source"] == "员工手册.md"
    assert result["sources"][0]["section"].startswith("二、假期制度")
    assert result["cited_ids"] == [1]
    assert result["latency_ms"] >= 0


def test_direct_mode_has_no_sources(monkeypatch):
    svc = chain_module.RagService()
    fake = _FakeLLM(responses=["我不知道。"] * 6)
    monkeypatch.setattr(type(svc), "llm", property(lambda self: fake))
    result = svc.answer("随便问点啥", history=[], use_rag=False)
    assert result["sources"] == []
    assert result["cited_ids"] == []


# ---------------------------------------------------------------- 接口
def test_health_endpoint():
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app)  # 不进入 with，跳过 startup 建库，保持测试快速
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
    assert "llm_model" in resp.json()["config"]


# ---------------------------------------------------------------- 真实检索
@pytest.mark.slow
def test_retrieval_hits_expected_document():
    """真实向量检索：这个用例会加载本地向量模型，第一次跑需要下载模型。"""
    from app.rag.vectorstore import ensure_index, search

    ensure_index()
    hits = search("年假有几天", 4)
    assert hits, "检索没有返回任何片段"
    assert any(d.metadata.get("source") == "员工手册.md" for d, _ in hits)
