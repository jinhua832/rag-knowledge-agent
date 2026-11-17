/**
 * 所有和后端打交道的代码都收在这个文件里。
 * 好处：接口一改，只改这里；组件里只管「拿到数据怎么显示」。
 */
const BASE = import.meta.env.VITE_API_BASE ?? "";

async function request(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, options);
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || body.message || detail;
    } catch (_) {
      /* 响应不是 JSON 就保留状态码信息 */
    }
    throw new Error(detail);
  }
  return res.json();
}

export function getHealth() {
  return request("/api/health");
}

export function getDocuments() {
  return request("/api/documents");
}

export function uploadDocument(file) {
  const form = new FormData();
  form.append("file", file);
  return request("/api/documents", { method: "POST", body: form });
}

export function deleteDocument(name) {
  return request(`/api/documents/${encodeURIComponent(name)}`, { method: "DELETE" });
}

export function reindex() {
  return request("/api/reindex", { method: "POST" });
}

export function resetSession(sessionId) {
  return request(`/api/session/${encodeURIComponent(sessionId)}/reset`, { method: "POST" });
}

/**
 * SSE 流式对话。
 * 不能用 EventSource：它只支持 GET，而我们要 POST 传问题。
 * 所以用 fetch + ReadableStream 自己解析 "event: xxx\ndata: {...}\n\n"。
 */
export async function chatStream({ question, sessionId, topK, useRag }, handlers, signal) {
  const res = await fetch(`${BASE}/api/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      session_id: sessionId,
      top_k: topK,
      use_rag: useRag,
    }),
    signal,
  });

  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = await res.json();
      detail = body.detail || detail;
    } catch (_) {}
    throw new Error(detail);
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    const blocks = buffer.split("\n\n");
    buffer = blocks.pop(); // 最后一段可能不完整，留到下一轮

    for (const block of blocks) {
      let event = "message";
      let data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) event = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) continue;
      try {
        handlers.onEvent(event, JSON.parse(data));
      } catch (err) {
        console.warn("解析 SSE 失败", block, err);
      }
    }
  }
}
