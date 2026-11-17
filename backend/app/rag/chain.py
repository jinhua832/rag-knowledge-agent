"""RAG 主流程：改写 → 检索 → 拼 Prompt → 生成 → 回填引用。

这是整个项目的心脏。看懂这个文件，RAG 就通了。
"""
from __future__ import annotations

import re
import time
from typing import Iterator

from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_openai import ChatOpenAI

from app.config import settings
from app.rag import prompts
from app.rag.vectorstore import list_documents, search

CITATION_RE = re.compile(r"\[(\d+)\]")


def _to_messages(history: list[dict]) -> list:
    """把前端传来的历史（[{"role":"user","content":...}]）转成 LangChain 消息对象。"""
    out = []
    for m in history:
        content = (m.get("content") or "").strip()
        if not content:
            continue
        out.append(HumanMessage(content=content) if m.get("role") == "user" else AIMessage(content=content))
    return out


class RagService:
    def __init__(self) -> None:
        self._llm: ChatOpenAI | None = None
        self._answer_chain = None
        self._direct_chain = None
        self._rewrite_chain = None

    # ---------------- LangChain 组件（懒加载，避免没配 key 就启动失败）----------------
    @property
    def llm(self) -> ChatOpenAI:
        if self._llm is None:
            settings.require_llm_key()
            self._llm = ChatOpenAI(
                model=settings.llm_model,
                base_url=settings.llm_base_url,
                api_key=settings.llm_api_key,
                temperature=settings.temperature,
                max_tokens=settings.max_tokens,
                timeout=settings.timeout,
                streaming=True,
            )
        return self._llm

    @property
    def answer_chain(self):
        """Prompt | LLM | 字符串解析器 —— 这就是「LangChain 编排」。"""
        if self._answer_chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", prompts.ANSWER_SYSTEM_PROMPT),
                    MessagesPlaceholder("history"),
                    ("human", prompts.HUMAN_TEMPLATE_RAG),
                ]
            )
            self._answer_chain = prompt | self.llm | StrOutputParser()
        return self._answer_chain

    @property
    def direct_chain(self):
        """对照组：不检索、直接把问题丢给模型。用来对比 RAG 到底有没有用。"""
        if self._direct_chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", prompts.DIRECT_SYSTEM_PROMPT),
                    MessagesPlaceholder("history"),
                    ("human", prompts.HUMAN_TEMPLATE_DIRECT),
                ]
            )
            self._direct_chain = prompt | self.llm | StrOutputParser()
        return self._direct_chain

    @property
    def rewrite_chain(self):
        if self._rewrite_chain is None:
            prompt = ChatPromptTemplate.from_messages(
                [
                    ("system", prompts.REWRITE_SYSTEM_PROMPT),
                    MessagesPlaceholder("history"),
                    ("human", "{question}"),
                ]
            )
            self._rewrite_chain = prompt | self.llm | StrOutputParser()
        return self._rewrite_chain

    # ---------------- 三个原子步骤 ----------------
    def retrieve(self, question: str, top_k: int | None = None) -> list[dict]:
        """向量检索，并整理成前端能直接用的结构（带 1、2、3 编号）。"""
        hits = search(question, top_k)
        sources = []
        for idx, (doc, score) in enumerate(hits, start=1):
            sources.append(
                {
                    "id": idx,
                    "source": doc.metadata.get("source", "未知文档"),
                    "section": doc.metadata.get("section", ""),
                    "score": round(float(score), 4),
                    "content": doc.page_content,
                }
            )
        return sources

    def rewrite(self, question: str, history: list[dict]) -> str:
        """多轮场景：把「那它呢？」补全成「星尘笔记 Pro 的年费是多少？」。

        没有历史、或关掉了改写，就直接返回原问题，不多花一次 token。
        """
        if not settings.enable_rewrite or not history:
            return question
        try:
            out = self.rewrite_chain.invoke(
                {"history": _to_messages(history), "question": question}
            )
            rewritten = (out or "").strip().strip("“”\"'")
            # 兜底：改写结果明显不正常（太长、多行、答非所问）时，退回原问题。
            # 线上真实遇到过模型把「改写」写成了回答，这一行能避免整轮检索跑偏。
            if not rewritten or len(rewritten) > 80 or "\n" in rewritten:
                return question
            return rewritten
        except Exception as exc:
            print(f"[warn] 查询改写失败，直接用原问题: {exc}")
            return question

    @staticmethod
    def cited_ids(answer: str, sources: list[dict]) -> list[int]:
        """从回答里抽出 [1][3] 这类引用编号，并过滤掉不存在的编号。"""
        valid = {s["id"] for s in sources}
        ids = [int(x) for x in CITATION_RE.findall(answer)]
        seen, ordered = set(), []
        for i in ids:
            if i in valid and i not in seen:
                seen.add(i)
                ordered.append(i)
        return ordered

    # ---------------- 对外：一次性回答（评测脚本 / 非流式接口用）----------------
    def answer(
        self,
        question: str,
        history: list[dict] | None = None,
        top_k: int | None = None,
        use_rag: bool = True,
    ) -> dict:
        history = history or []
        t0 = time.perf_counter()

        standalone = self.rewrite(question, history) if use_rag else question
        sources = self.retrieve(standalone, top_k) if use_rag else []

        payload = {"history": _to_messages(history), "question": standalone}
        if use_rag:
            payload["context"] = prompts.format_context(sources)
            raw = self.answer_chain.invoke(payload)
        else:
            raw = self.direct_chain.invoke(payload)

        text = (raw or "").strip()
        return {
            "answer": text,
            "sources": sources,
            "standalone_question": standalone,
            "latency_ms": int((time.perf_counter() - t0) * 1000),
            "cited_ids": self.cited_ids(text, sources),
        }

    # ---------------- 对外：流式回答（前端打字机效果用）----------------
    def stream(
        self,
        question: str,
        history: list[dict] | None = None,
        top_k: int | None = None,
        use_rag: bool = True,
    ) -> Iterator[dict]:
        """产出事件：meta（先推检索结果）→ token（逐字）→ done（结束）。"""
        history = history or []
        t0 = time.perf_counter()
        try:
            standalone = self.rewrite(question, history) if use_rag else question
            sources = self.retrieve(standalone, top_k) if use_rag else []

            yield {
                "event": "meta",
                "data": {
                    "sources": sources,
                    "standalone_question": standalone,
                    "rewritten": standalone.strip() != question.strip(),
                    "use_rag": use_rag,
                },
            }

            payload = {"history": _to_messages(history), "question": standalone}
            chain = self.answer_chain
            if use_rag:
                payload["context"] = prompts.format_context(sources)
            else:
                chain = self.direct_chain

            buffer: list[str] = []
            for piece in chain.stream(payload):
                if not piece:
                    continue
                buffer.append(piece)
                yield {"event": "token", "data": {"text": piece}}

            text = "".join(buffer).strip()
            yield {
                "event": "done",
                "data": {
                    "answer": text,
                    "latency_ms": int((time.perf_counter() - t0) * 1000),
                    "cited_ids": self.cited_ids(text, sources),
                },
            }
        except Exception as exc:
            yield {"event": "error", "data": {"message": f"生成失败：{exc}"}}

    def stats(self) -> dict:
        docs = list_documents()
        return {
            "document_count": len(docs["documents"]),
            "chunk_count": docs["total_chunks"],
            "updated_at": docs["updated_at"],
            "embedding": docs["embedding"],
        }


service = RagService()
