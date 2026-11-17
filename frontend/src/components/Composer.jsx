import { useRef, useState } from "react";

export default function Composer({ busy, onSend, onStop }) {
  const [value, setValue] = useState("");
  const taRef = useRef(null);

  const submit = () => {
    if (!value.trim() || busy) return;
    onSend(value);
    setValue("");
    if (taRef.current) taRef.current.style.height = "auto";
  };

  return (
    <footer className="composer">
      <div className="composer-box">
        <textarea
          ref={taRef}
          rows={2}
          value={value}
          placeholder="问点什么…（Enter 发送，Shift + Enter 换行）"
          onChange={(e) => {
            setValue(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = `${Math.min(e.target.scrollHeight, 160)}px`;
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
              e.preventDefault();
              submit();
            }
          }}
        />
        {busy ? (
          <button className="stop-btn" onClick={onStop}>
            停止
          </button>
        ) : (
          <button className="send-btn" onClick={submit} disabled={!value.trim()}>
            发送
          </button>
        )}
      </div>
      <p className="composer-hint">
        回答由模型生成，仅依据左侧文档；重要信息请点引用编号核对原文。
      </p>
    </footer>
  );
}
