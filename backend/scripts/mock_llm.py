"""⚠️ 本地联调用的「假模型」服务（Mock LLM）——不是真实回答，也不能当产品用。

它是干什么的：
    没有 API Key 的时候，用来把「前端 → 后端 → LangChain → 流式返回」这条链路跑通，
    确认接口、SSE、引用编号都没问题。它只是把收到的【参考资料】回声出来。

怎么用（两个终端，都在 backend/ 目录）：
    # 终端 1：启动假模型，监听 9999
    .venv/bin/python -m scripts.mock_llm

    # 终端 2：让后端指向假模型
    LLM_BASE_URL=http://127.0.0.1:9999/v1 LLM_API_KEY=mock LLM_MODEL=mock-model \
    uvicorn app.main:app --reload --port 8000

    配好真实 key 之后，把 .env 里的 LLM_BASE_URL 改回官方地址即可，本文件不需要删。
"""
from __future__ import annotations

import json
import re
import time

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, StreamingResponse

app = FastAPI(title="Mock LLM")


def _extract_context(text: str) -> list[str]:
    """从 Prompt 里撬出【参考资料】段落，取出每一块的内容前 70 个字。"""
    if "【参考资料】" not in text:
        return []
    part = text.split("【参考资料】", 1)[1]
    part = part.split("【用户问题】", 1)[0]
    blocks = re.split(r"\n\n(?=\[)", part.strip())
    out = []
    for block in blocks:
        lines = block.strip().split("\n")
        body = " ".join(lines[1:]).strip() if len(lines) > 1 else block.strip()
        out.append(body[:70])
    return [b for b in out if b]


def build_answer(body: dict) -> str:
    messages = body.get("messages") or []
    system = " ".join(
        (m.get("content") or "") for m in messages if m.get("role") == "system"
    )
    last_user = ""
    for m in reversed(messages):
        if m.get("role") == "user":
            last_user = m.get("content") or ""
            break

    # 查询改写那一步：假模型不会做指代消解，原样返回问题即可（不会污染检索）
    if "改写" in system and "查询" in system:
        return last_user.strip()

    question = last_user.split("【用户问题】")[-1].strip() if "【用户问题】" in last_user else "你的问题"
    snippets = _extract_context(last_user)

    if not snippets:
        return (
            "（模拟回答，非真实模型输出）\n"
            "当前没有提供任何参考资料，我无法回答这个问题。"
        )

    lines = [
        "（模拟回答，非真实模型输出，仅用于验证链路）",
        "",
        f"关于「{question[:40]}」，根据检索到的资料可以这样回答：",
    ]
    for i, s in enumerate(snippets[:3], start=1):
        lines.append(f"- {s}…… [{i}]")
    lines.append("")
    lines.append("以上内容仅来自知识库片段，具体以原文为准。")
    return "\n".join(lines)


@app.get("/v1/models")
def models() -> dict:
    return {"object": "list", "data": [{"id": "mock-model", "object": "model"}]}


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    answer = build_answer(body)
    model = body.get("model", "mock-model")
    created = int(time.time())
    cid = f"chatcmpl-mock-{created}"

    if not body.get("stream"):
        return JSONResponse(
            {
                "id": cid,
                "object": "chat.completion",
                "created": created,
                "model": model,
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": answer},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            }
        )

    def event_stream():
        # 逐块吐出，模拟真实模型的打字机效果
        for i in range(0, len(answer), 6):
            chunk = answer[i : i + 6]
            payload = {
                "id": cid,
                "object": "chat.completion.chunk",
                "created": created,
                "model": model,
                "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}],
            }
            yield f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
            time.sleep(0.01)
        final = {
            "id": cid,
            "object": "chat.completion.chunk",
            "created": created,
            "model": model,
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
        yield f"data: {json.dumps(final, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=9999)
