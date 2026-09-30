"""Concrete providers.

- `NoLLMProvider`: never calls out. The assistant answers from its rules (basic mode).
- `OllamaProvider`: a model running locally through Ollama (free, open source, no key).
  Local development default; too heavy for shared hosting.
- `OpenAICompatibleProvider`: any server that speaks the OpenAI chat-completions API. That
  covers self-hosted servers (vLLM, LM Studio, llama.cpp, Ollama's own `/v1`), the free tiers
  of hosted services, and paid ones. Nothing is subscribed by the project; the owner sets
  the URL and key.
- `AnthropicProvider`: Anthropic's Messages API. Optional and paid; the owner opts in.
"""

from django.conf import settings

from .base import ChatOptions, LLMError, LLMProvider, LLMReply, LLMUnavailable, post_json


class NoLLMProvider(LLMProvider):
    name = "none"


class OllamaProvider(LLMProvider):
    name = "ollama"

    def __init__(self, base_url: str = "", model: str = ""):
        self.base_url = (base_url or settings.OLLAMA_BASE_URL).rstrip("/")
        self.model = model or settings.LLM_MODEL or "qwen2.5:3b"

    @property
    def available(self) -> bool:
        return bool(self.model)

    def chat(self, messages: list[dict], options: ChatOptions | None = None) -> LLMReply:
        options = options or ChatOptions()
        body = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "think": False,  # reasoning models (qwen3, deepseek) answer directly; ignored by others
            "keep_alive": settings.OLLAMA_KEEP_ALIVE,
            "options": {"temperature": options.temperature, "num_predict": options.max_tokens},
        }
        if options.json:
            body["format"] = "json"
        data = post_json(f"{self.base_url}/api/chat", body, timeout=settings.LLM_TIMEOUT_SECONDS)
        if "error" in data:
            message = str(data["error"])
            if "not found" in message.lower():
                raise LLMUnavailable(f"Ollama: {message}. Run `ollama pull {self.model}`.")
            raise LLMError(f"Ollama: {message}")
        content = (data.get("message") or {}).get("content") or ""
        return LLMReply(
            content=content,
            tokens_in=int(data.get("prompt_eval_count") or 0),
            tokens_out=int(data.get("eval_count") or 0),
            provider=self.name,
            model=self.model,
        )


class OpenAICompatibleProvider(LLMProvider):
    name = "openai_compatible"

    def __init__(self, base_url: str = "", api_key: str = "", model: str = ""):
        self.base_url = (base_url or settings.OPENAI_COMPATIBLE_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.OPENAI_COMPATIBLE_API_KEY
        self.model = model or settings.LLM_MODEL

    @property
    def available(self) -> bool:
        return bool(self.base_url and self.model)

    def chat(self, messages: list[dict], options: ChatOptions | None = None) -> LLMReply:
        options = options or ChatOptions()
        if not self.available:
            raise LLMUnavailable("OPENAI_COMPATIBLE_BASE_URL and LLM_MODEL are not set.")
        body = {
            "model": self.model,
            "messages": messages,
            "max_tokens": options.max_tokens,
            "temperature": options.temperature,
        }
        if options.json:
            body["response_format"] = {"type": "json_object"}
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        data = post_json(
            f"{self.base_url}/chat/completions", body, headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS
        )
        choices = data.get("choices") or []
        if not choices:
            raise LLMError(f"No answer from the model: {str(data)[:200]}")
        usage = data.get("usage") or {}
        return LLMReply(
            content=(choices[0].get("message") or {}).get("content") or "",
            tokens_in=int(usage.get("prompt_tokens") or 0),
            tokens_out=int(usage.get("completion_tokens") or 0),
            provider=self.name,
            model=self.model,
        )


class AnthropicProvider(LLMProvider):
    name = "anthropic"

    def __init__(self, api_key: str = "", model: str = ""):
        self.api_key = api_key or settings.ANTHROPIC_API_KEY
        self.model = model or settings.LLM_MODEL or "claude-haiku-4-5-20251001"

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def chat(self, messages: list[dict], options: ChatOptions | None = None) -> LLMReply:
        options = options or ChatOptions()
        if not self.available:
            raise LLMUnavailable("ANTHROPIC_API_KEY is not set.")
        system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
        turns = [m for m in messages if m["role"] != "system"]
        if options.json:
            system += "\n\nAnswer with a single JSON object and nothing else."
        body = {
            "model": self.model,
            "max_tokens": options.max_tokens,
            "temperature": options.temperature,
            "system": system,
            "messages": turns,
        }
        headers = {"x-api-key": self.api_key, "anthropic-version": "2023-06-01"}
        data = post_json(
            "https://api.anthropic.com/v1/messages", body, headers=headers, timeout=settings.LLM_TIMEOUT_SECONDS
        )
        blocks = data.get("content") or []
        text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
        usage = data.get("usage") or {}
        return LLMReply(
            content=text,
            tokens_in=int(usage.get("input_tokens") or 0),
            tokens_out=int(usage.get("output_tokens") or 0),
            provider=self.name,
            model=self.model,
        )
