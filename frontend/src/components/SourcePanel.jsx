import { useEffect, useRef } from "react";

export default function SourcePanel({ sources, message, focusSource, useRag }) {
  const refs = useRef({});

  useEffect(() => {
    if (focusSource && refs.current[focusSource]) {
      refs.current[focusSource].scrollIntoView({ behavior: "smooth", block: "nearest" });
    }
  }, [focusSource]);

  const cited = new Set(message?.citedIds || []);
  const empty = (sources || []).length === 0;

  return (
    <aside className="sources">
      <header className="sources-head">
        <div>
          <h2>检索片段</h2>
          <p>
            {useRag
              ? `本次召回 ${sources?.length || 0} 条，编号与回答里的 [n] 一一对应`
              : "对比模式下不检索知识库"}
          </p>
        </div>
      </header>

      {empty ? (
        <div className="sources-empty">
          <span>◎</span>
          <p>{useRag ? "提问后这里会显示命中的原文片段" : "当前是直接提问模式，没有检索结果"}</p>
        </div>
      ) : (
        <div className="source-list">
          {sources.map((s) => (
            <article
              key={s.id}
              ref={(el) => (refs.current[s.id] = el)}
              className={`source-card ${focusSource === s.id ? "focus" : ""} ${
                cited.has(s.id) ? "cited" : ""
              }`}
            >
              <header>
                <span className="src-id">{s.id}</span>
                <div className="src-title">
                  <h3>{s.source}</h3>
                  <p>{s.section || "（无章节信息）"}</p>
                </div>
                <span className="src-score">{Math.round((s.score || 0) * 100)}%</span>
              </header>
              <div className="score-bar">
                <i style={{ width: `${Math.max(0, Math.min(1, s.score || 0)) * 100}%` }} />
              </div>
              <p className="src-content">{s.content}</p>
              {cited.has(s.id) && <span className="cited-tag">已被引用</span>}
            </article>
          ))}
        </div>
      )}
    </aside>
  );
}
