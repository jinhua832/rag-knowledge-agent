"""20 条测试问答的效果评测脚本。

两种用法：
    python -m scripts.eval --retrieval-only   # 没配 key 也能跑：只测「检索命中率」
    python -m scripts.eval                    # 完整评测：直接提问 vs RAG，需要 LLM_API_KEY

产物写到 backend/output/ 下：
    eval_result.csv     每道题的明细（可直接用 Excel 打开）
    eval_report.md      汇总报告，能直接贴进 README
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.rag.chain import service  # noqa: E402

QUESTIONS_PATH = Path(__file__).resolve().parents[1] / "data" / "questions.json"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "output"

REFUSAL_MARKERS = ("没有找到", "没有相关", "未找到", "知识库中没有", "超出", "无法回答", "不确定")


def load_questions() -> list[dict]:
    data = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    return data["questions"] if isinstance(data, dict) else data


def judge_keyword(answer: str, keywords: list[str]) -> bool:
    return any(k and k in answer for k in keywords)


def judge_refusal(answer: str) -> bool:
    return any(m in answer for m in REFUSAL_MARKERS)


def run(retrieval_only: bool = False, top_k: int | None = None, limit: int | None = None) -> None:
    questions = load_questions()
    if limit:
        questions = questions[:limit]
    k = top_k or settings.default_top_k
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    rows = []
    print(f"评测开始：{len(questions)} 条问题，top_k={k}，retrieval_only={retrieval_only}")
    for q in questions:
        t0 = time.perf_counter()
        sources = service.retrieve(q["question"], k)
        retrieved = [s["source"] for s in sources]
        retrieval_hit = q["source"] in retrieved
        top1_hit = bool(retrieved) and retrieved[0] == q["source"]

        row = {
            "id": q["id"],
            "问题": q["question"],
            "类型": q.get("type", "answerable"),
            "期望来源": q["source"] or "-",
            "检索命中": "是" if retrieval_hit else "否",
            "Top1命中": "是" if top1_hit else "否",
            "召回文档": " / ".join(retrieved),
            "最高相似度": f"{sources[0]['score']:.3f}" if sources else "-",
            "检索耗时(ms)": int((time.perf_counter() - t0) * 1000),
        }

        if not retrieval_only:
            rag = service.answer(q["question"], history=[], top_k=k, use_rag=True)
            direct = service.answer(q["question"], history=[], top_k=k, use_rag=False)
            expect_refusal = q.get("type") == "unanswerable"

            row.update(
                {
                    "RAG回答": rag["answer"].replace("\n", " ")[:400],
                    "RAG引用数": len(rag["cited_ids"]),
                    "RAG延迟(ms)": rag["latency_ms"],
                    "直接回答": direct["answer"].replace("\n", " ")[:400],
                    "直接延迟(ms)": direct["latency_ms"],
                }
            )
            if expect_refusal:
                row["RAG正确"] = "是" if judge_refusal(rag["answer"]) else "否"
                row["直接正确"] = "是" if judge_refusal(direct["answer"]) else "否"
            else:
                row["RAG正确"] = "是" if judge_keyword(rag["answer"], q.get("keywords", [])) else "否"
                row["直接正确"] = "是" if judge_keyword(direct["answer"], q.get("keywords", [])) else "否"

        rows.append(row)
        print(f"  [{row['id']:>2}] 检索{'命中' if retrieval_hit else '未命中'} | {q['question']}")

    # ---------------- CSV ----------------
    csv_path = OUTPUT_DIR / "eval_result.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    # ---------------- 报告 ----------------
    total = len(rows)
    answerable = [r for r in rows if r["类型"] != "unanswerable"]
    retrieval_hits = sum(1 for r in answerable if r["检索命中"] == "是")
    top1_hits = sum(1 for r in answerable if r["Top1命中"] == "是")
    n_answerable = max(len(answerable), 1)

    lines = [
        "# 20 条测试问答效果报告",
        "",
        f"- 生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        f"- 向量模型：{settings.embedding_model if settings.embedding_provider == 'api' else settings.local_embedding_model}",
        f"- 切分参数：chunk_size={settings.chunk_size}, overlap={settings.chunk_overlap}",
        f"- 检索 top_k={k}，共 {total} 条问题（{len(answerable)} 条有标准答案，{total - len(answerable)} 条故意无答案，用于检验是否会编造）",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 检索命中率（有答案的 {len(answerable)} 条里，期望文档出现在 top{k}） | {retrieval_hits}/{len(answerable)} = {retrieval_hits / n_answerable:.0%} |",
        f"| Top1 命中率（期望文档排第一） | {top1_hits}/{len(answerable)} = {top1_hits / n_answerable:.0%} |",
    ]
    if not retrieval_only:
        rag_ok = sum(1 for r in answerable if r.get("RAG正确") == "是")
        direct_ok = sum(1 for r in answerable if r.get("直接正确") == "是")
        unans = [r for r in rows if r["类型"] == "unanswerable"]
        rag_refuse = sum(1 for r in unans if r.get("RAG正确") == "是")
        direct_refuse = sum(1 for r in unans if r.get("直接正确") == "是")
        lines += [
            f"| RAG 回答正确率（关键词命中） | {rag_ok}/{len(answerable)} = {rag_ok / n_answerable:.0%} |",
            f"| 直接提问正确率（对照组） | {direct_ok}/{len(answerable)} = {direct_ok / n_answerable:.0%} |",
            f"| 无答案题：RAG 正确拒答 | {rag_refuse}/{len(unans)} |",
            f"| 无答案题：直接提问正确拒答 | {direct_refuse}/{len(unans)} |",
        ]
        lines += [
            "",
            f"**结论：RAG 相比直接提问，正确率提升 {(rag_ok - direct_ok) / n_answerable:.0%} 个百分点**"
            f"（{direct_ok}/{len(answerable)} → {rag_ok}/{len(answerable)}）。",
        ]
    else:
        lines += [
            "",
            f"注：本次只跑了检索（--retrieval-only），没有调用大模型。"
            f"剩下 {total - len(answerable)} 条「知识库里没有答案」的问题，检索层本来就不该命中，"
            "它们的正确与否由回答是否拒答来判定，需要配好 LLM_API_KEY 后跑完整评测。",
        ]

    lines += ["", "## 逐题明细", "", "| # | 问题 | 期望来源 | 检索命中 | 备注 |", "| --- | --- | --- | --- | --- |"]
    for r in rows:
        note = ""
        if not retrieval_only:
            note = f"RAG {'✓' if r.get('RAG正确') == '是' else '✗'} / 直接 {'✓' if r.get('直接正确') == '是' else '✗'}"
        lines.append(f"| {r['id']} | {r['问题']} | {r['期望来源']} | {r['检索命中']} | {note} |")

    if retrieval_hits < total * 0.8:
        lines += ["", "## 改进建议", "", "- 检索命中率偏低：优先检查切分粒度（chunk_size 过大/过小），再考虑换向量模型或加关键词混合检索。"]

    report_path = OUTPUT_DIR / "eval_report.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")

    print("-" * 60)
    print(f"检索命中 {retrieval_hits}/{len(answerable)}（有标准答案的题目），Top1 命中 {top1_hits}/{len(answerable)}")
    print(f"明细：{csv_path}")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--retrieval-only", action="store_true", help="只测检索，不调用大模型")
    parser.add_argument("--top-k", type=int, default=None)
    parser.add_argument("--limit", type=int, default=None, help="只跑前 N 条，调试用")
    args = parser.parse_args()
    run(retrieval_only=args.retrieval_only, top_k=args.top_k, limit=args.limit)
