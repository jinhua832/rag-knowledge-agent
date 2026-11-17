"""会话历史存储。

新手版：放在进程内存里，重启就清空。
生产版：换成 Redis / Postgres，接口保持一样即可。
"""
from __future__ import annotations

import threading
from collections import OrderedDict


class SessionStore:
    def __init__(self, max_turns: int = 4, max_sessions: int = 200) -> None:
        self.max_turns = max_turns
        self.max_sessions = max_sessions
        self._data: OrderedDict[str, list[dict]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> list[dict]:
        with self._lock:
            return list(self._data.get(session_id, []))

    def append(self, session_id: str, question: str, answer: str) -> None:
        with self._lock:
            history = self._data.get(session_id, [])
            history.append({"role": "user", "content": question})
            history.append({"role": "assistant", "content": answer})
            # 只保留最近 N 轮，防止 Prompt 无限变长、token 越烧越多
            history = history[-self.max_turns * 2 :]
            self._data[session_id] = history
            self._data.move_to_end(session_id)
            while len(self._data) > self.max_sessions:
                self._data.popitem(last=False)

    def clear(self, session_id: str) -> None:
        with self._lock:
            self._data.pop(session_id, None)

    def count(self) -> int:
        with self._lock:
            return len(self._data)
