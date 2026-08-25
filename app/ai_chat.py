import json
import urllib.request
import urllib.error
from pathlib import Path
from PySide6.QtCore import QThread, Signal

from .update_utils import get_assets_dir
from .agent import TOOLS, execute_tool, MemoryManager


CONTACT_TO_PROMPT = {
    "Arona": "arona",
    "Plana": "plana",
}


def _prompt_path(contact_key: str) -> Path:
    name = CONTACT_TO_PROMPT.get(contact_key, contact_key.lower())
    return get_assets_dir() / "Chat" / name / f"{name}.md"


def _history_path(contact_key: str) -> Path:
    name = CONTACT_TO_PROMPT.get(contact_key, contact_key.lower())
    return get_assets_dir() / "Chat" / "ChatHistory" / f"{name}.md"


def load_system_prompt(contact_key: str) -> str:
    p = _prompt_path(contact_key)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return "You are a helpful assistant."


def load_history(contact_key: str) -> list[dict]:
    p = _history_path(contact_key)
    if not p.exists():
        return []
    raw = p.read_text(encoding="utf-8").strip()
    if not raw:
        return []
    messages = []
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("[user|") and "] " in line:
            ts_end = line.index("] ")
            ts = line[6:ts_end]
            messages.append({"role": "user", "content": line[ts_end+2:], "timestamp": ts})
        elif line.startswith("[user] "):
            messages.append({"role": "user", "content": line[7:]})
        elif line.startswith("[assistant|") and "] " in line:
            ts_end = line.index("] ")
            ts = line[11:ts_end]
            messages.append({"role": "assistant", "content": line[ts_end+2:], "timestamp": ts})
        elif line.startswith("[assistant] "):
            messages.append({"role": "assistant", "content": line[12:]})
    return messages


def write_history(contact_key: str, messages: list[dict]):
    p = _history_path(contact_key)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for m in messages:
        role = m["role"]
        content = m["content"]
        ts = m.get("timestamp", "")
        if role in ("user", "assistant"):
            if ts:
                lines.append(f"[{role}|{ts}] {content}")
            else:
                lines.append(f"[{role}] {content}")
    p.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def save_history(contact_key: str, messages: list[dict]):
    p = _history_path(contact_key)
    p.parent.mkdir(parents=True, exist_ok=True)

    existing = load_history(contact_key)
    existing_set = {(m["role"], m["content"], m.get("timestamp", "")) for m in existing}
    merged = list(existing)

    for m in messages:
        key = (m["role"], m["content"], m.get("timestamp", ""))
        if key not in existing_set:
            merged.append(m)
            existing_set.add(key)

    lines = []
    for m in merged:
        role = m["role"]
        content = m["content"]
        ts = m.get("timestamp", "")
        if role in ("user", "assistant"):
            if ts:
                lines.append(f"[{role}|{ts}] {content}")
            else:
                lines.append(f"[{role}] {content}")
    p.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")


def _api_call(url: str, api_key: str, payload: dict) -> dict:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body_text = resp.read().decode("utf-8", errors="replace")
    if not body_text.strip():
        raise ValueError("API 返回空响应")
    return json.loads(body_text)


class AIWorker(QThread):
    finished = Signal(str)
    error = Signal(str)
    tool_execution = Signal(str)

    def __init__(self, contact_key: str, user_text: str,
                 history: list[dict], parent=None):
        super().__init__(parent)
        self._contact_key = contact_key
        self._user_text = user_text
        self._history = list(history)

    def run(self):
        try:
            from .config import get_ai_settings
            ai_cfg = get_ai_settings()
            api_key = ai_cfg.get("api_key", "")
            base_url = ai_cfg.get("base_url", "https://api.openai.com/v1")
            model = ai_cfg.get("model", "gpt-4o-mini")

            if not api_key:
                self.error.emit("未配置 API Key，请在设置中填写")
                return

            base_url = base_url.rstrip("/")
            url = f"{base_url}/chat/completions"

            system_prompt = load_system_prompt(self._contact_key)

            memories = MemoryManager.load(self._contact_key)
            if memories:
                recent = memories[-10:]
                memory_text = "\n".join(
                    f"- [{m.get('category', '其他')}] {m.get('content', '')}"
                    for m in recent
                )
                system_prompt += f"\n\n## 长期记忆\n{memory_text}"

            messages = [{"role": "system", "content": system_prompt}]
            messages.extend(self._history)
            messages.append({"role": "user", "content": self._user_text})

            for _ in range(5):
                payload = {
                    "model": model,
                    "messages": messages,
                    "tools": TOOLS,
                    "temperature": 0.9,
                    "max_tokens": 512,
                    "stream": False,
                }

                data = _api_call(url, api_key, payload)
                msg = data["choices"][0]["message"]
                content = (msg.get("content") or "").strip()

                if not msg.get("tool_calls"):
                    self.finished.emit(content or "（无回复）")
                    return

                messages.append(msg)

                for tc in msg["tool_calls"]:
                    fn_name = tc["function"]["name"]
                    fn_args = json.loads(tc["function"]["arguments"])

                    self.tool_execution.emit(fn_name)
                    result = execute_tool(fn_name, fn_args, self._contact_key)

                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "content": result,
                    })

            payload_final = {
                "model": model,
                "messages": messages,
                "temperature": 0.9,
                "max_tokens": 512,
                "stream": False,
            }
            data_final = _api_call(url, api_key, payload_final)
            reply = (data_final["choices"][0]["message"].get("content") or "").strip()
            self.finished.emit(reply or "（任务已完成）")

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                pass

            code = e.code
            if code == 401:
                msg = "API Key 无效或已过期"
            elif code == 404:
                msg = "API 地址或模型不存在 (HTTP 404)"
            elif code == 429:
                msg = "API 请求频率过高或余额不足 (HTTP 429)"
            elif code == 402:
                msg = "API 余额不足 (HTTP 402)"
            else:
                msg = f"API 错误 (HTTP {code})"

            if body:
                preview = body[:300]
                msg = f"{msg}\n{preview}"
            self.error.emit(msg)

        except urllib.error.URLError as e:
            self.error.emit(f"无法连接到 API 服务器: {e.reason}")

        except Exception as e:
            self.error.emit(f"请求失败: {type(e).__name__}: {e}")
