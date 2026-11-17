"""文档加载 + 切分。

RAG 效果好不好，60% 取决于这一步。
切得太碎 → 一句话没有上下文，模型答不出；
切得太大 → 检索精度下降，还浪费 token。
"""
from __future__ import annotations

from pathlib import Path

from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter, RecursiveCharacterTextSplitter

from app.config import settings

SUPPORTED_SUFFIXES = {".md", ".markdown", ".txt", ".pdf"}

# 中文必须加这些分隔符，否则 RecursiveCharacterTextSplitter 会按空格乱切
SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", "，", " ", ""]

_HEADERS = [("#", "h1"), ("##", "h2"), ("###", "h3")]


def _markdown_docs(path: Path) -> list[Document]:
    """按标题切段，顺手把「章节标题」记进 metadata。

    这样回答时就能显示「出处：《员工手册》· 三、假期制度」，
    而不是干巴巴一句“来自员工手册.md”。
    """
    text = path.read_text(encoding="utf-8", errors="ignore")
    splitter = MarkdownHeaderTextSplitter(headers_to_split_on=_HEADERS, strip_headers=False)
    sections = splitter.split_text(text)

    docs: list[Document] = []
    for sec in sections:
        meta = sec.metadata or {}
        section = " > ".join(v for v in (meta.get("h1"), meta.get("h2"), meta.get("h3")) if v)
        docs.append(
            Document(
                page_content=sec.page_content,
                metadata={"source": path.name, "section": section},
            )
        )
    return docs


def _plain_docs(path: Path) -> list[Document]:
    text = path.read_text(encoding="utf-8", errors="ignore")
    return [Document(page_content=text, metadata={"source": path.name, "section": ""})]


def _pdf_docs(path: Path) -> list[Document]:
    from langchain_community.document_loaders import PyPDFLoader

    loader = PyPDFLoader(str(path))
    docs = loader.load()
    for d in docs:
        page = d.metadata.get("page", 0)
        d.metadata = {"source": path.name, "section": f"第 {int(page) + 1} 页"}
    return docs


def load_file(path: Path) -> list[Document]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".markdown"}:
        return _markdown_docs(path)
    if suffix == ".pdf":
        return _pdf_docs(path)
    return _plain_docs(path)


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        separators=SEPARATORS,
        keep_separator=True,
        add_start_index=True,
    )
    chunks = splitter.split_documents(docs)
    # 丢掉纯空白块，它们只会污染检索结果
    chunks = [c for c in chunks if c.page_content.strip()]
    for i, c in enumerate(chunks):
        c.metadata["chunk_index"] = i
    return chunks


def load_corpus(docs_dir: Path | None = None) -> list[Document]:
    """把 data/docs 下所有支持的文档读进来并切好。"""
    docs_dir = docs_dir or settings.docs_dir
    raw: list[Document] = []
    for path in sorted(docs_dir.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            try:
                raw.extend(load_file(path))
            except Exception as exc:  # 单个文件坏了不影响整体
                print(f"[warn] 解析失败 {path.name}: {exc}")
    if not raw:
        return []
    return split_documents(raw)
