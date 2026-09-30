"""Language-model providers behind one small interface.

The assistant (`apps.ai.services`) uses a model for two things only: understanding what the
customer wrote (intent, search words, budget, language) and phrasing the answer. Products,
prices, stock and delivery always come from the database; the model never sees a way to
change them. Every provider is optional: with `LLM_PROVIDER=none` (the production default on
shared hosting) the assistant runs in its rule-based "basic" mode.

Only the standard library is used for HTTP, as for maps and payments.
"""

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field


class LLMError(Exception):
    """The provider answered with an error or something that isn't usable."""


class LLMUnavailable(LLMError):
    """The provider can't be reached (not running, no key, network down). The caller falls back."""


@dataclass(frozen=True)
class LLMReply:
    content: str
    tokens_in: int = 0
    tokens_out: int = 0
    provider: str = ""
    model: str = ""

    def json(self) -> dict:
        """The reply parsed as a JSON object (models sometimes wrap it in text or fences)."""
        text = self.content.strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.startswith("json"):
                text = text[4:]
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < 0:
            raise LLMError("The model did not answer with JSON.")
        try:
            data = json.loads(text[start : end + 1])
        except ValueError as exc:
            raise LLMError("The model answered with invalid JSON.") from exc
        if not isinstance(data, dict):
            raise LLMError("The model did not answer with a JSON object.")
        return data


@dataclass
class ChatOptions:
    json: bool = False
    max_tokens: int = 400
    temperature: float = 0.2
    extra: dict = field(default_factory=dict)


class LLMProvider:
    """Interface. `chat` takes OpenAI-style messages `[{"role": "system"|"user"|"assistant", "content": str}]`."""

    name = "none"
    model = ""

    @property
    def available(self) -> bool:
        return False

    def chat(self, messages: list[dict], options: ChatOptions | None = None) -> LLMReply:
        raise LLMUnavailable("No language model is configured.")


def post_json(url: str, body: dict, *, headers: dict | None = None, timeout: float) -> dict:
    """POST JSON, return the parsed JSON body. Network problems → LLMUnavailable; HTTP errors → LLMError."""
    if not (url.startswith("https://") or url.startswith("http://localhost") or url.startswith("http://127.")):
        raise LLMError("Language-model services must use https (or a local server).")
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")  # noqa: S310 - scheme checked above
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310
            return json.loads(res.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode("utf-8", "replace")
        if exc.code in (401, 403):
            raise LLMUnavailable(f"The language model refused the credentials ({exc.code}).") from exc
        if exc.code == 404 and "model" in detail.lower():
            raise LLMUnavailable(f"The model is not available: {detail}") from exc
        raise LLMError(f"Language model error {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
        raise LLMUnavailable(str(exc)) from exc
    except ValueError as exc:
        raise LLMError("The language model answered with something that isn't JSON.") from exc
