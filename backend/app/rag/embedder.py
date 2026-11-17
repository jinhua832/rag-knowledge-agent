"""把「文本」变成「向量」的组件。

为什么单独抽出来：因为它是整个 RAG 里最容易被换掉的一环。
换模型只要改 .env，不动业务代码。
"""
from __future__ import annotations

from langchain_core.embeddings import Embeddings

from app.config import settings

_cache: dict[str, Embeddings] = {}


def _build_api_embeddings() -> Embeddings:
    from langchain_openai import OpenAIEmbeddings

    if not settings.embedding_api_key:
        raise RuntimeError(
            "EMBEDDING_PROVIDER=api 但没有可用的 key。"
            "请在 backend/.env 里填 EMBEDDING_API_KEY，"
            "或改用 EMBEDDING_PROVIDER=local 走本地模型。"
        )
    # check_embedding_ctx_length=False 很关键：
    # 默认 True 时 LangChain 会先把文本切成 token 数组再发出去，
    # 而通义/智谱/硅基流动这些兼容接口只接受字符串，不改就会报 400。
    return OpenAIEmbeddings(
        model=settings.embedding_model,
        base_url=settings.embedding_base_url,
        api_key=settings.embedding_api_key,
        check_embedding_ctx_length=False,
        chunk_size=32,
    )


def _build_local_embeddings() -> Embeddings:
    try:
        from langchain_huggingface import HuggingFaceEmbeddings
    except ImportError:
        try:
            from langchain_community.embeddings import HuggingFaceEmbeddings  # 旧版路径
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "本地向量化需要额外的依赖："
                "pip install -r requirements-local.txt"
            ) from exc

    return HuggingFaceEmbeddings(
        model_name=settings.local_embedding_model,
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )


def get_embeddings() -> Embeddings:
    """单例缓存：模型只加载一次，否则每次请求都会重新初始化，慢到没法用。"""
    key = f"{settings.embedding_provider}:{settings.embedding_model}:{settings.local_embedding_model}"
    if key not in _cache:
        if settings.embedding_provider == "local":
            _cache[key] = _build_local_embeddings()
        else:
            _cache[key] = _build_api_embeddings()
    return _cache[key]
