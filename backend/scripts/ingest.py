"""命令行建库脚本。

用法（在 backend/ 目录下）：
    python -m scripts.ingest            # 增量：只处理新增/改动的文件
    python -m scripts.ingest --rebuild  # 全量重建（改了 CHUNK_SIZE 之后必须用这个）
    python -m scripts.ingest --search "年假有几天"   # 只测试检索，不调大模型
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 让脚本能直接 `import app.*`
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.rag import vectorstore  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description="知识库建库工具")
    parser.add_argument("--rebuild", action="store_true", help="全量重建索引")
    parser.add_argument("--search", type=str, default="", help="建完库后跑一条检索测试")
    parser.add_argument("--k", type=int, default=settings.default_top_k, help="检索片段数")
    args = parser.parse_args()

    print(f"文档目录：{settings.docs_dir}")
    print(f"向量库目录：{settings.chroma_dir}")
    print(f"Embedding：{settings.embedding_provider} / "
          f"{settings.embedding_model if settings.embedding_provider == 'api' else settings.local_embedding_model}")
    print(f"切分参数：chunk_size={settings.chunk_size}, overlap={settings.chunk_overlap}")
    print("-" * 60)

    if args.rebuild:
        result = vectorstore.reindex_all(rebuild=True)
    else:
        files = [
            p
            for p in sorted(settings.docs_dir.rglob("*"))
            if p.is_file() and p.suffix.lower() in {".md", ".markdown", ".txt", ".pdf"}
        ]
        total = 0
        for path in files:
            n = vectorstore.index_file(path)
            total += n
            print(f"  ✓ {path.name} → {n} 个片段")
        result = {"documents": len(files), "chunks": total}

    print("-" * 60)
    print(f"建库完成：{result.get('documents', 0)} 个文档，{result.get('chunks', 0)} 个片段")

    if args.search:
        print(f"\n检索测试：{args.search}")
        for i, (doc, score) in enumerate(vectorstore.search(args.search, args.k), start=1):
            print(f"\n[{i}] 相似度 {score:.3f} | {doc.metadata.get('source')} · {doc.metadata.get('section')}")
            print("    " + doc.page_content.replace("\n", " ")[:120] + "…")


if __name__ == "__main__":
    main()
