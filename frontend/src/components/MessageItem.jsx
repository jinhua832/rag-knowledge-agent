import React from "react";

/** 把回答里的 **粗体** 和 [1] 引用编号渲染成可点击的元素。 */
function renderInline(text, sources, onCite) {
  const parts = text.split(/(\*\*[^*]+\*\*|\[\d+\])/g).filter((p) => p !== "");
  return parts.map((part, i) => {
    const bold = part.match(/^\*\*([^*]+)\*\*$/);
    if (bold) return <strong key={i}>{bold[1]}</strong>;

    const cite = part.match(/^\[(\d+)\]$/);
    if (cite) {
      const id = Number(cite[1]);
      const exists = (sources || []).some((s) => s.id === id);
      if (!exists) {
        return <span key={i} className="cite missing">[{id}]</span>;
      }
      return (
        <button
          key={i}
          type="button"
          className="cite"
          title={`查看第 ${id} 条原文`}
          onClick={(e) => {
            e.stopPropagation();
            onCite(id);
          }}
        >
          {id}
        </button>
      );
    }
    return <React.Fragment key={i}>{part}</React.Fragment>;
  });
}

function renderBody(message, onCite) {
  const lines = message.content.split("\n");
  return lines.map((line, idx) => {
    const trimmed = line.trim();
    if (!trimmed) return <div key={idx} className="line-gap" />;
    if (/^[-•·]\s+/.test(trimmed)) {
      return (
        <div key={idx} className="bullet">
          <i>•</i>
          <span>{renderInline(trimmed.replace(/^[-•·]\s+/, ""), message.sources, onCite)}</span>
        </div>
      );
    }
    if (/^\d+\.\s+/.test(trimmed)) {
      const [, num, rest] = trimmed.match(/^(\d+)\.\s+(.*)$/);
      return (
        <div key={idx} className="bullet">
          <i>{num}</i>
          <span>{renderInline(rest, message.sources, onCite)}</span>
        </div>
      );
    }
    if (trimmed.startsWith("###")) {
      return <h4 key={idx}>{trimmed.replace(/^#+\s*/, "")}</h4>;
    }
    return <p key={idx}>{renderInline(trimmed, message.sources, onCite)}</p>;
  });
}

export default function MessageItem({ message, active, onSelect, onCite }) {
  if (message.role === "user") {
    return (
      <div className="msg user">
        <div className="bubble">{message.content}</div>
      </div>
    );
  }

  const hasSources = (message.sources || []).length > 0;

  return (
    <div
      className={`msg assistant ${active ? "active" : ""}`}
      onClick={onSelect}
      title="点击查看本次检索到的片段"
    >
      <div className="msg-head">
        <span className="avatar">AI</span>
        <span className="who">回答</span>
        {message.useRag ? (
          <span className="badge">{hasSources ? `${message.sources.length} 条依据` : "无依据"}</span>
        ) : (
          <span className="badge off">未检索</span>
        )}
      </div>

      {message.error ? (
        <div className="error-text">{message.error}</div>
      ) : (
        <div className="answer">
          {message.content ? (
            renderBody(message, onCite)
          ) : message.streaming ? (
            <span className="typing">正在检索知识库…</span>
          ) : (
            <span className="typing">没有内容</span>
          )}
          {message.streaming && message.content && <span className="caret" />}
        </div>
      )}

      <div className="msg-foot">
        {typeof message.latency === "number" && <span>{message.latency} ms</span>}
        {message.citedIds?.length > 0 && <span>引用 {message.citedIds.join("、")}</span>}
        {message.stopped && <span>已手动停止</span>}
        {message.useRag && message.rewritten && message.standalone && (
          <span className="rewrite" title="多轮对话中用于检索的独立问题">
            检索词：{message.standalone}
          </span>
        )}
      </div>
    </div>
  );
}
