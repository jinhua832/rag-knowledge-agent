import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "./api";
import Sidebar from "./components/Sidebar";
import MessageItem from "./components/MessageItem";
import SourcePanel from "./components/SourcePanel";
import Composer from "./components/Composer";

const SUGGESTIONS = [
  "入职满 3 年的员工，一年有几天年假？",
  "去北京出差，住宿标准一晚最多多少钱？",
  "星尘笔记 Pro 版一年多少钱？",
  "接口限流了会返回什么状态码？",
  "星尘科技的 CEO 是谁？",
];

function newSessionId() {
  return "s_" + Math.random().toString(36).slice(2, 10);
}

export default function App() {
  const [sessionId] = useState(() => {
    const saved = localStorage.getItem("rag_session_id");
    if (saved) return saved;
    const id = newSessionId();
    localStorage.setItem("rag_session_id", id);
    return id;
  });

  const [messages, setMessages] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [focusSource, setFocusSource] = useState(null);
  const [docs, setDocs] = useState({ documents: [], total_chunks: 0, updated_at: "" });
  const [docsLoaded, setDocsLoaded] = useState(false);
  const [health, setHealth] = useState(null);
  const [config, setConfig] = useState({ topK: 4, useRag: true });
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState(null);

  const abortRef = useRef(null);
  const bottomRef = useRef(null);

  // ---------------------------------------------------------------- 数据
  const loadAll = useCallback(async () => {
    try {
      const [docData, healthData] = await Promise.all([api.getDocuments(), api.getHealth()]);
      setDocs(docData);
      setDocsLoaded(true);
      setHealth(healthData);
    } catch (err) {
      setNotice({ type: "error", text: `加载失败：${err.message}` });
    }
  }, []);

  useEffect(() => {
    loadAll();
  }, [loadAll]);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages]);

  const updateMessage = useCallback((id, patch) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...patch(m) } : m)));
  }, []);

  // ---------------------------------------------------------------- 对话
  const send = useCallback(
    async (raw) => {
      const question = (raw || "").trim();
      if (!question || busy) return;

      const uid = `u_${Date.now()}`;
      const aid = `a_${Date.now()}`;
      setMessages((prev) => [
        ...prev,
        { id: uid, role: "user", content: question },
        {
          id: aid,
          role: "assistant",
          content: "",
          sources: [],
          citedIds: [],
          streaming: true,
          useRag: config.useRag,
        },
      ]);
      setActiveId(aid);
      setFocusSource(null);
      setBusy(true);

      const controller = new AbortController();
      abortRef.current = controller;

      try {
        await api.chatStream(
          { question, sessionId, topK: config.topK, useRag: config.useRag },
          {
            onEvent: (event, data) => {
              if (event === "meta") {
                updateMessage(aid, (m) => ({
                  ...m,
                  sources: data.sources || [],
                  standalone: data.standalone_question,
                  rewritten: data.rewritten,
                }));
              } else if (event === "token") {
                updateMessage(aid, (m) => ({ ...m, content: m.content + data.text }));
              } else if (event === "done") {
                updateMessage(aid, (m) => ({
                  ...m,
                  content: data.answer || m.content,
                  citedIds: data.cited_ids || [],
                  latency: data.latency_ms,
                  streaming: false,
                }));
              } else if (event === "error") {
                updateMessage(aid, (m) => ({ ...m, error: data.message, streaming: false }));
              }
            },
          },
          controller.signal
        );
      } catch (err) {
        if (err.name === "AbortError") {
          updateMessage(aid, (m) => ({ ...m, streaming: false, stopped: true }));
        } else {
          updateMessage(aid, (m) => ({ ...m, error: err.message, streaming: false }));
        }
      } finally {
        setBusy(false);
        abortRef.current = null;
      }
    },
    [busy, config, sessionId, updateMessage]
  );

  const stop = () => abortRef.current?.abort();

  const resetSession = async () => {
    try {
      await api.resetSession(sessionId);
    } catch (_) {
      /* 后端没起来也不影响本地清空 */
    }
    setMessages([]);
    setActiveId(null);
    setNotice({ type: "info", text: "已开始新会话，多轮上下文已清空" });
  };

  // ---------------------------------------------------------------- 知识库操作
  const handleUpload = async (file) => {
    try {
      const data = await api.uploadDocument(file);
      setDocs(data);
      setNotice({ type: "success", text: `已索引《${file.name}》，共 ${data.chunks} 个片段` });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  };

  const handleDelete = async (name) => {
    try {
      const data = await api.deleteDocument(name);
      setDocs(data);
      setNotice({ type: "success", text: `已移除《${name}》` });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  };

  const handleReindex = async () => {
    try {
      const data = await api.reindex();
      await loadAll();
      setNotice({ type: "success", text: `重建完成：${data.documents} 篇 / ${data.chunks} 个片段` });
    } catch (err) {
      setNotice({ type: "error", text: err.message });
    }
  };

  // ---------------------------------------------------------------- 渲染
  const activeMessage = messages.find((m) => m.id === activeId && m.role === "assistant") || null;
  const lastAssistant = [...messages].reverse().find((m) => m.role === "assistant") || null;
  const shownSources = (activeMessage || lastAssistant)?.sources || [];

  const keyMissing = health && health.config && !health.config.llm_key_configured;

  return (
    <div className="layout">
      <Sidebar
        docs={docs}
        docsLoaded={docsLoaded}
        health={health}
        config={config}
        onChange={setConfig}
        onUpload={handleUpload}
        onDelete={handleDelete}
        onReindex={handleReindex}
        onReset={resetSession}
        busy={busy}
      />

      <main className="main">
        <header className="topbar">
          <div>
            <h1>知识库问答</h1>
            <p>
              {config.useRag
                ? `RAG 模式 · 召回 ${config.topK} 个片段 · 共 ${docs.total_chunks} 个片段`
                : "对比模式 · 不检索、直接提问（用来验证 RAG 到底有没有用）"}
            </p>
          </div>
          <span className={`mode-chip ${config.useRag ? "on" : "off"}`}>
            {config.useRag ? "RAG" : "直接回答"}
          </span>
        </header>

        {keyMissing && (
          <div className="banner warn">
            还没填 LLM_API_KEY，检索能用但无法生成回答。请在 backend/.env 里配置后重启服务。
          </div>
        )}

        {notice && (
          <div className={`banner ${notice.type}`} onClick={() => setNotice(null)}>
            {notice.text}
            <span className="banner-close">×</span>
          </div>
        )}

        <section className="chat" ref={null}>
          {messages.length === 0 ? (
            <div className="empty">
              <div className="empty-icon">✦</div>
              <h2>问点什么吧</h2>
              <p>答案只来自左侧知识库里的 4 份文档，每条结论都带引用编号，点编号可以跳到右侧查原文。</p>
              <div className="suggestions">
                {SUGGESTIONS.map((s) => (
                  <button key={s} onClick={() => send(s)}>
                    {s}
                  </button>
                ))}
              </div>
            </div>
          ) : (
            <div className="message-list">
              {messages.map((m) => (
                <MessageItem
                  key={m.id}
                  message={m}
                  active={m.id === activeId}
                  onSelect={() => {
                    if (m.role === "assistant") {
                      setActiveId(m.id);
                      setFocusSource(null);
                    }
                  }}
                  onCite={(id) => {
                    setActiveId(m.id);
                    setFocusSource(id);
                  }}
                />
              ))}
              <div ref={bottomRef} />
            </div>
          )}
        </section>

        <Composer busy={busy} onSend={send} onStop={stop} />
      </main>

      <SourcePanel
        sources={shownSources}
        message={activeMessage || lastAssistant}
        focusSource={focusSource}
        useRag={config.useRag}
      />
    </div>
  );
}
