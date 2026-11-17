import { useRef, useState } from "react";

function formatSize(bytes) {
  if (!bytes) return "0 KB";
  return bytes > 1024 * 1024
    ? `${(bytes / 1024 / 1024).toFixed(1)} MB`
    : `${Math.max(1, Math.round(bytes / 1024))} KB`;
}

export default function Sidebar({
  docs,
  docsLoaded,
  health,
  config,
  onChange,
  onUpload,
  onDelete,
  onReindex,
  onReset,
  busy,
}) {
  const fileRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  const pickFile = async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      await onUpload(file);
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  const model = health?.config?.llm_model || "未连接";
  const embedding = health?.config?.embedding_model || "-";

  return (
    <aside className="sidebar">
      <div className="brand">
        <span className="logo">星</span>
        <div>
          <h1>星尘知识库</h1>
          <p>RAG 问答 · 个人项目</p>
        </div>
      </div>

      <section className="panel">
        <header className="panel-head">
          <h2>知识库</h2>
          <span>{docsLoaded ? `${docs.documents.length} 篇 / ${docs.total_chunks} 片段` : "加载中…"}</span>
        </header>

        <ul className="doc-list">
          {!docsLoaded && <li className="doc-empty">正在读取知识库…</li>}
          {docsLoaded && docs.documents.length === 0 && (
            <li className="doc-empty">还没有文档，先上传一份 .md / .txt / .pdf</li>
          )}
          {docs.documents.map((d) => (
            <li key={d.source}>
              <span className={`file-type ${d.source.split(".").pop()}`}>
                {d.source.split(".").pop().toUpperCase()}
              </span>
              <div className="doc-meta">
                <strong title={d.source}>{d.source}</strong>
                <small>{d.chunks} 片段 · {formatSize(d.size)}</small>
              </div>
              <button
                className="icon-btn"
                title={`移除 ${d.source}`}
                onClick={() => {
                  if (window.confirm(`确定从知识库移除《${d.source}》吗？文件也会一并删除。`)) {
                    onDelete(d.source);
                  }
                }}
              >
                ×
              </button>
            </li>
          ))}
        </ul>

        <div className="panel-actions">
          <button className="ghost" onClick={() => fileRef.current?.click()} disabled={uploading}>
            {uploading ? "上传中…" : "＋ 上传文档"}
          </button>
          <button className="ghost" onClick={onReindex} disabled={busy}>
            重建索引
          </button>
          <input
            ref={fileRef}
            type="file"
            accept=".md,.markdown,.txt,.pdf"
            onChange={pickFile}
            hidden
          />
        </div>
      </section>

      <section className="panel">
        <header className="panel-head">
          <h2>检索设置</h2>
        </header>

        <label className="field">
          <span>召回片段数 <b>{config.topK}</b></span>
          <input
            type="range"
            min="1"
            max="10"
            value={config.topK}
            onChange={(e) => onChange({ ...config, topK: Number(e.target.value) })}
          />
        </label>

        <label className="switch-row">
          <div>
            <strong>对比模式</strong>
            <small>关闭检索，直接问模型（对照组）</small>
          </div>
          <input
            type="checkbox"
            checked={!config.useRag}
            onChange={(e) => onChange({ ...config, useRag: !e.target.checked })}
          />
        </label>

        <button className="ghost wide" onClick={onReset}>
          清空多轮上下文
        </button>
      </section>

      <footer className="side-foot">
        <div className="kv"><span>模型</span><b title={model}>{model}</b></div>
        <div className="kv"><span>向量</span><b title={embedding}>{embedding}</b></div>
        <div className="kv"><span>更新</span><b>{docs.updated_at ? docs.updated_at.replace("T", " ") : "—"}</b></div>
      </footer>
    </aside>
  );
}
