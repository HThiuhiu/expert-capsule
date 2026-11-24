"""Lớp gọi LLM duy nhất: chọn backend theo tên model `<provider>/<model>`, cache đĩa theo hash(model, messages, params).

Chạy lại từ cache cho kết quả giống hệt. Không có cache và `offline=True` thì báo lỗi thay vì gọi mạng.

Provider:
- `anthropic/<model>`: SDK chính thức `anthropic` (pip install -e ".[anthropic]"). Thông tin đăng nhập theo SDK:
  ANTHROPIC_API_KEY, ANTHROPIC_AUTH_TOKEN, hoặc hồ sơ `ant auth login`. Không gửi temperature (model mới trả 400);
  `effort` trong cấu hình vai đi vào `output_config`. Opus/Sonnet 5.5 bật fallback phía server khi bị từ chối.
- `openai/<model>`: API tương thích OpenAI qua HTTP (OPENAI_API_KEY, OPENAI_BASE_URL): OpenAI, OpenRouter, LM Studio...
- `ollama/<model>`: model trên máy qua Ollama (OLLAMA_BASE_URL, mặc định http://localhost:11434/v1), không cần key.
- `relay/<model>`, `deepseek/<model>`: relay/DeepSeek tương thích OpenAI (RELAY_* hoặc DEEPSEEK_* env).
- `agent/<tên>`: không gọi API; yêu cầu vào hàng đợi cho subagent (Claude Code) trả lời.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

Backend = Callable[..., dict]  # (model, messages, **params) -> {"text", "input_tokens", "output_tokens"}

_RETRY = {408, 409, 429, 500, 502, 503, 504, 529}
_NOT_OPENAI = ("effort",)  # khoá cấu hình vai chỉ dành cho Anthropic


def _post_json(url: str, headers: dict, payload: dict, timeout: float = 300) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdr = {"content-type": "application/json", "user-agent": "expert-capsule/0.2", **headers}
    for attempt in range(5):
        req = urllib.request.Request(url, data=data, headers=hdr, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read()[:400].decode("utf-8", "replace")
            if e.code in _RETRY and attempt < 4:
                time.sleep(2 ** attempt * 2)
                continue
            raise RuntimeError(f"HTTP {e.code} từ {url}: {body}") from None
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt < 4:
                time.sleep(2 ** attempt * 2)
                continue
            raise
    raise RuntimeError("unreachable")


def _openai_compat(base: str, key: str, model: str, messages: list[dict], **params: Any) -> dict:
    params = {k: v for k, v in params.items() if k not in _NOT_OPENAI}
    hdr = {"authorization": f"Bearer {key}"} if key else {}
    r = _post_json(base.rstrip("/") + "/chat/completions", hdr, {"model": model, "messages": messages, **params})
    u = r.get("usage") or {}
    return {"text": r["choices"][0]["message"].get("content") or "",
            "input_tokens": u.get("prompt_tokens", 0) or 0, "output_tokens": u.get("completion_tokens", 0) or 0}


# Model có fallback phía server khi bị từ chối (chỉ Claude API). Haiku không có.
_FALLBACK_MODELS = ("claude-opus-5-5", "claude-sonnet-5-5", "claude-opus-5", "claude-fable-5-1", "claude-fable-5-2")
_anthropic_client = None
_anthropic_lock = threading.Lock()


def _anthropic(model: str, messages: list[dict], **params: Any) -> dict:
    try:
        import anthropic
    except ImportError:
        raise RuntimeError('Thiếu thư viện anthropic: pip install -e ".[anthropic]"') from None
    global _anthropic_client
    with _anthropic_lock:
        if _anthropic_client is None:
            _anthropic_client = anthropic.Anthropic()  # ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / `ant auth login`
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    kwargs: dict[str, Any] = {
        "model": model,
        # thinking tính vào max_tokens: để rộng tay để JSON trả về không bị cắt giữa chừng
        "max_tokens": max(16000, int(params.get("max_tokens") or 0)),
        "messages": [m for m in messages if m["role"] != "system"],
    }
    if system:
        kwargs["system"] = system
    if params.get("effort"):
        kwargs["output_config"] = {"effort": params["effort"]}
    if model in _FALLBACK_MODELS:
        r = _anthropic_client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], fallbacks="default",
                                                   **kwargs)
    else:
        r = _anthropic_client.messages.create(**kwargs)
    if r.stop_reason == "refusal":
        cat = getattr(getattr(r, "stop_details", None), "category", None)
        raise RuntimeError(f"Model từ chối yêu cầu (refusal, {cat})")
    return {"text": "".join(b.text for b in r.content if b.type == "text"),
            "input_tokens": r.usage.input_tokens or 0, "output_tokens": r.usage.output_tokens or 0}


def _env(*names: str, default: str = "") -> str:
    for n in names:
        if os.environ.get(n):
            return os.environ[n]
    return default


def _http_backend(model: str, messages: list[dict], **params: Any) -> dict:
    provider, _, name = model.partition("/")
    if provider == "anthropic":
        return _anthropic(name, messages, **params)
    if provider == "ollama":
        return _openai_compat(_env("OLLAMA_BASE_URL", default="http://localhost:11434/v1"), "", name,
                              messages, **params)
    if provider in ("openai", "relay", "deepseek"):
        names = {"openai": ("OPENAI",), "relay": ("RELAY", "DEEPSEEK"), "deepseek": ("DEEPSEEK",)}[provider]
        key = _env(*(f"{n}_API_KEY" for n in names))
        if not key:
            raise RuntimeError(f"Thiếu {names[0]}_API_KEY")
        default = {"openai": "https://api.openai.com/v1", "deepseek": "https://api.deepseek.com"}.get(provider, "")
        base = _env(*(f"{n}_BASE_URL" for n in names), default=default)
        if not base:
            raise RuntimeError(f"Thiếu {names[0]}_BASE_URL")
        return _openai_compat(base, key, name, messages, **params)
    raise RuntimeError(f"Chưa hỗ trợ provider `{provider}` (dùng anthropic/, openai/, ollama/, relay/, agent/)")


class Pending(Exception):
    """Vai dùng model `agent/...`: yêu cầu đã vào hàng đợi, chờ subagent trả lời rồi `import_answers`."""


def has_credentials(model: str) -> bool:
    provider = model.partition("/")[0]
    if provider in ("agent", "gpu", "ollama"):
        return True
    if provider == "anthropic":  # SDK còn đọc hồ sơ `ant auth login`, nên không chặn sớm
        return True
    env = {"deepseek": ("DEEPSEEK_API_KEY",), "relay": ("RELAY_API_KEY", "DEEPSEEK_API_KEY"),
           "openai": ("OPENAI_API_KEY",)}.get(provider, ())
    return any(os.environ.get(v) for v in env)


@dataclass
class Usage:
    calls: int = 0
    cache_hits: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_model: dict[str, list[int]] = field(default_factory=dict)

    def cost(self, pricing: dict[str, dict[str, float]]) -> float:
        total = 0.0
        for m, (i, o) in self.by_model.items():
            p = pricing.get(m) or {}
            total += i / 1e6 * p.get("input", 0) + o / 1e6 * p.get("output", 0)
        return total


class LLM:
    def __init__(self, cache_dir: Path, backend: Optional[Backend] = None, offline: bool = False):
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.backend = backend or _http_backend
        self.offline = offline
        self.usage = Usage()
        self._lock = threading.Lock()  # gọi song song theo phiên

    @staticmethod
    def key(model: str, messages: list[dict], params: dict) -> str:
        blob = json.dumps({"model": model, "messages": messages, "params": params},
                          sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def complete(self, role_cfg: dict, messages: list[dict], tag: str = "", **extra: Any) -> str:
        """`tag` chỉ ghi vào hàng đợi agent (không vào khoá cache): gói cho subagent không trộn tag khác nhau."""
        cfg = dict(role_cfg)
        model = cfg.pop("model")
        params = {"temperature": 0, **cfg, **extra}
        k = self.key(model, messages, params)
        path = self.cache_dir / k[:2] / f"{k}.json"
        if path.exists():
            with self._lock:
                self.usage.cache_hits += 1
            return json.loads(path.read_text(encoding="utf-8"))["text"]
        if self.offline:
            raise RuntimeError(f"cache miss ở chế độ offline: {k}")
        if model.startswith(("agent/", "gpu/")):  # gpu/: LLM local trên GPU server, xả hàng đợi bằng `pc gpu-drain`
            q = self.queue_dir / f"{k}.json"
            q.parent.mkdir(parents=True, exist_ok=True)
            if not q.exists():
                q.write_text(json.dumps({"key": k, "model": model, "messages": messages, "tag": tag,
                                         "max_tokens": int(params.get("max_tokens", 2048))}, ensure_ascii=False),
                             encoding="utf-8")
            raise Pending(k)
        out = self.backend(model, messages, **params)
        with self._lock:
            self.usage.calls += 1
            self.usage.input_tokens += out.get("input_tokens", 0)
            self.usage.output_tokens += out.get("output_tokens", 0)
            bm = self.usage.by_model.setdefault(model, [0, 0])
            bm[0] += out.get("input_tokens", 0)
            bm[1] += out.get("output_tokens", 0)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"model": model, "params": params, **out}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
        return out["text"]

    @property
    def queue_dir(self) -> Path:
        return self.cache_dir.parent / "agent_queue"

    def import_answers(self, answers: Path) -> int:
        """Nạp `{key, text}` (jsonl) do subagent viết vào cache, xoá yêu cầu tương ứng khỏi hàng đợi."""
        n = 0
        with open(answers, encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                a = json.loads(line)
                if "text" not in a and "answer" in a:  # subagent ghi object thay cho chuỗi JSON
                    a["text"] = json.dumps(a["answer"], ensure_ascii=False)
                q = self.queue_dir / f"{a['key']}.json"
                if not q.exists():
                    continue
                req = json.loads(q.read_text(encoding="utf-8"))
                path = self.cache_dir / a["key"][:2] / f"{a['key']}.json"
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps({"model": req["model"], "params": {}, "text": a["text"],
                                            "input_tokens": 0, "output_tokens": 0}, ensure_ascii=False),
                                encoding="utf-8")
                q.unlink()
                n += 1
        return n


def estimate_cost(tokens_in: int, tokens_out: int, model: str, pricing: dict) -> float:
    p = pricing.get(model) or {}
    return tokens_in / 1e6 * p.get("input", 0) + tokens_out / 1e6 * p.get("output", 0)
