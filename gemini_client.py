import os
from pathlib import Path
from google import genai

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.1-flash-lite")
MAX_HISTORY_MESSAGES = int(os.environ.get("MAX_HISTORY_MESSAGES", "20"))
SYSTEM_PROMPT_PATH = Path(__file__).parent / "system_prompt.txt"

def _load_system_prompt() -> str:
    try:
        text = SYSTEM_PROMPT_PATH.read_text(encoding="utf-8").strip()
        return text or "You are a helpful, concise personal assistant."
    except FileNotFoundError:
        return "You are a helpful, concise personal assistant."

class GeminiAssistant:
    def __init__(self, model: str | None = None):
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is not set.")
        self.client = genai.Client(api_key=api_key)
        self.model = model or DEFAULT_MODEL
        self.system_prompt = _load_system_prompt()
        self._history: dict[str, list[dict]] = {}

    def _get_history(self, user_id: str) -> list[dict]:
        return self._history.setdefault(user_id, [])

    def reset_history(self, user_id: str) -> None:
        self._history[user_id] = []

    def active_conversation_count(self) -> int:
        return len(self._history)

    def chat(self, user_id: str, message: str) -> str:
        history = self._get_history(user_id)
        contents = history + [{"role": "user", "parts": [{"text": message}]}]

        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=contents,
                config={"system_instruction": self.system_prompt},
            )
        except Exception as exc:
            raise RuntimeError(str(exc)) from exc

        reply_text = (response.text or "").strip() or "(Gemini returned an empty response.)"
        
        history.append({"role": "user", "parts": [{"text": message}]})
        history.append({"role": "model", "parts": [{"text": reply_text}]})

        overflow = len(history) - MAX_HISTORY_MESSAGES
        if overflow > 0:
            del history[:overflow]

        return reply_text