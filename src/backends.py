"""One conversation with a model, behind the same small interface for each provider.

  chat = AnthropicChat(client, model, system, prompt, effort="medium")
  turn = chat.step()                 # one model response; final=True forbids tool calls
  chat.add_results([(id, output, is_error), ...])
"""
import json
import os
import re
import uuid
from dataclasses import dataclass, field

from tools import TOOL_DEFS

MAX_TOKENS = 32000  # per response; reasoning counts against it on most providers
# OpenAI-compatible endpoints. Go is the subscription plan; Zen is the separate
# pay-as-you-go service, which also lists some free models. Both take the same key.
BASE_URLS = {
    "opencode-go": "https://opencode.ai/zen/go/v1",
    "opencode-zen": "https://opencode.ai/zen/v1",
}
GO_KEY_ENV = "OPENCODE_API_KEY"
# OpenCode Go asks clients to name themselves and to send a stable id per conversation.
USER_AGENT = "seq-in-context-harness/0.1"
PROVIDERS = ("anthropic", *BASE_URLS)


@dataclass
class Turn:
    status: str  # "tool_use", "end_turn", "max_tokens", "refusal", or the provider's own value
    text: str = ""
    tool_calls: list = field(default_factory=list)  # (id, name, input dict or None if unparseable)
    refusal_category: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cached_tokens: int = 0  # part of input_tokens served from the provider's cache, where reported
    request_id: str | None = None
    served_model: str | None = None  # what the server says answered, which may differ from the request


def _plain(block):
    if isinstance(block, dict):
        return block
    return block.model_dump() if hasattr(block, "model_dump") else vars(block)


class AnthropicChat:
    def __init__(self, client, model, system, prompt, effort="medium", tool_defs=None, max_tokens=MAX_TOKENS):
        self.client, self.model, self.system, self.effort = client, model, system, effort
        self.max_tokens = max_tokens
        self.messages = [{"role": "user", "content": prompt}]
        self.tools = TOOL_DEFS if tool_defs is None else tool_defs

    def step(self, final=False):
        r = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=self.system,
            thinking={"type": "adaptive", "display": "summarized"},
            output_config={"effort": self.effort},
            tools=self.tools,
            tool_choice={"type": "none" if final else "auto"},
            messages=self.messages,
        )
        self.messages.append({"role": "assistant", "content": r.content})
        details = getattr(r, "stop_details", None)
        return Turn(
            status=r.stop_reason,
            text="\n".join(b.text for b in r.content if b.type == "text"),
            tool_calls=[(b.id, b.name, b.input) for b in r.content if b.type == "tool_use"],
            refusal_category=details.category if details else None,
            input_tokens=r.usage.input_tokens,
            output_tokens=r.usage.output_tokens,
            cached_tokens=getattr(r.usage, "cache_read_input_tokens", 0) or 0,
            request_id=r._request_id,
            served_model=getattr(r, "model", None),
        )

    def transcript(self):
        """The whole conversation as plain JSON, including summarised thinking."""
        return [
            {**m, "content": [_plain(b) for b in m["content"]]}
            if isinstance(m["content"], list)
            else m
            for m in self.messages
        ]

    def add_results(self, results, note=None):
        content = [
            {"type": "tool_result", "tool_use_id": i, "content": out, "is_error": err}
            for i, out, err in results
        ]
        if note:
            content.append({"type": "text", "text": note})
        self.messages.append({"role": "user", "content": content})


_FINISH = {"tool_calls": "tool_use", "stop": "end_turn", "length": "max_tokens", "content_filter": "refusal"}


class OpenAIChat:
    """Any OpenAI-compatible /chat/completions endpoint."""

    def __init__(self, client, model, system, prompt, effort=None, tool_defs=None, max_tokens=MAX_TOKENS):
        self.client, self.model = client, model
        self.max_tokens = max_tokens
        # Only sent when asked for: models differ in which reasoning levels they accept.
        self.extra = {"reasoning_effort": effort} if effort else {}
        self.session = str(uuid.uuid4())
        self.messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        self.tools = [
            {
                "type": "function",
                "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]},
            }
            for t in (TOOL_DEFS if tool_defs is None else tool_defs)
        ]

    def step(self, final=False):
        r = self.client.chat.completions.create(
            model=self.model,
            max_tokens=self.max_tokens,
            tools=self.tools,
            tool_choice="none" if final else "auto",
            messages=self.messages,
            extra_headers={"x-opencode-session": self.session},
            **self.extra,
        )
        choice = r.choices[0]
        message = choice.message
        # Keep provider-specific fields (e.g. reasoning content) that some models need replayed.
        self.messages.append(message.model_dump(exclude_none=True))

        calls = []
        for call in message.tool_calls or []:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = None
            calls.append((call.id, call.function.name, args if isinstance(args, dict) else None))
        status = "tool_use" if calls else _FINISH.get(choice.finish_reason, choice.finish_reason)
        details = getattr(r.usage, "prompt_tokens_details", None)
        return Turn(
            status=status,
            text=message.content or "",
            tool_calls=calls,
            input_tokens=r.usage.prompt_tokens if r.usage else 0,
            output_tokens=r.usage.completion_tokens if r.usage else 0,
            cached_tokens=getattr(details, "cached_tokens", 0) or 0,
            request_id=r.id,
            served_model=getattr(r, "model", None),
        )

    def transcript(self):
        """The whole conversation as plain JSON, including any reasoning the provider returned."""
        return self.messages

    def add_results(self, results, note=None):
        for i, out, _ in results:
            self.messages.append({"role": "tool", "tool_call_id": i, "content": out})
        if note:
            self.messages.append({"role": "user", "content": note})


def make_client(provider):
    if provider == "anthropic":
        import anthropic

        return anthropic.Anthropic(max_retries=5)
    import openai

    key = os.environ.get(GO_KEY_ENV)
    if not key:
        raise SystemExit(f"set {GO_KEY_ENV} to your OpenCode API key")
    return openai.OpenAI(
        base_url=BASE_URLS[provider], api_key=key, max_retries=5, timeout=1800, default_headers={"User-Agent": USER_AGENT}
    )


def chat_class(provider):
    return AnthropicChat if provider == "anthropic" else OpenAIChat


def api_errors(provider):
    """(auth error, other API errors) for the provider's SDK."""
    sdk = __import__("anthropic" if provider == "anthropic" else "openai")
    return sdk.AuthenticationError, (sdk.APIStatusError, sdk.APIConnectionError)


def extract_json(text):
    """The first {...} object in a model reply, tolerating code fences and prose around it."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group() if m else None
