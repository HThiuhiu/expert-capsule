"""Backend LLM (không gọi mạng) và gộp config.local.yaml."""
import sys
import types

import pytest

import pc.llm as llm
from pc.config import load_config


def _fake_anthropic(calls, stop="end_turn"):
    def make(kind):
        def create(**kw):
            calls.append((kind, kw))
            blocks = [types.SimpleNamespace(type="thinking", thinking=""),
                      types.SimpleNamespace(type="text", text='{"ok": 1}')]
            return types.SimpleNamespace(stop_reason=stop, content=blocks, stop_details=None,
                                         usage=types.SimpleNamespace(input_tokens=10, output_tokens=3))
        return create

    class Anthropic:
        def __init__(self):
            self.messages = types.SimpleNamespace(create=make("messages"))
            self.beta = types.SimpleNamespace(messages=types.SimpleNamespace(create=make("beta")))
    return types.SimpleNamespace(Anthropic=Anthropic)


@pytest.fixture
def fake_sdk(monkeypatch):
    calls = []
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic(calls))
    monkeypatch.setattr(llm, "_anthropic_client", None)
    return calls


def test_anthropic_backend_params(fake_sdk):
    msgs = [{"role": "system", "content": "SYS"}, {"role": "user", "content": "hi"}]
    out = llm._http_backend("anthropic/claude-haiku-5-5", msgs, temperature=0, effort="low", max_tokens=4096)
    kind, kw = fake_sdk[-1]
    assert out == {"text": '{"ok": 1}', "input_tokens": 10, "output_tokens": 3}
    assert kind == "messages" and "temperature" not in kw  # model mới trả 400 nếu gửi temperature
    assert kw["system"] == "SYS" and kw["messages"] == [{"role": "user", "content": "hi"}]
    assert kw["output_config"] == {"effort": "low"} and kw["max_tokens"] >= 16000
    llm._http_backend("anthropic/claude-opus-5-5", msgs)
    kind, kw = fake_sdk[-1]
    assert kind == "beta" and kw["fallbacks"] == "default" and kw["betas"] == ["server-side-fallback-2026-07-01"]


def test_anthropic_refusal_raises(monkeypatch):
    monkeypatch.setitem(sys.modules, "anthropic", _fake_anthropic([], stop="refusal"))
    monkeypatch.setattr(llm, "_anthropic_client", None)
    with pytest.raises(RuntimeError, match="refusal"):
        llm._http_backend("anthropic/claude-haiku-5-5", [{"role": "user", "content": "x"}])


def test_openai_compat_and_ollama(monkeypatch):
    seen = []
    monkeypatch.setattr(llm, "_post_json", lambda url, hdr, payload, timeout=300: seen.append((url, hdr, payload)) or {
        "choices": [{"message": {"content": "ok"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 2}})
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    out = llm._http_backend("ollama/qwen3:14b", [{"role": "user", "content": "x"}], temperature=0, effort="low")
    url, hdr, payload = seen[-1]
    assert out["text"] == "ok" and url == "http://localhost:11434/v1/chat/completions" and hdr == {}
    assert "effort" not in payload and payload["temperature"] == 0
    monkeypatch.setenv("OPENAI_API_KEY", "k")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://openrouter.example/api/v1")
    llm._http_backend("openai/some-model", [{"role": "user", "content": "x"}], max_tokens=4096)
    assert seen[-1][0] == "https://openrouter.example/api/v1/chat/completions"
    assert seen[-1][1] == {"authorization": "Bearer k"}
    assert seen[-1][2]["max_tokens"] == 4096 and "max_completion_tokens" not in seen[-1][2]  # bên thứ ba: giữ nguyên
    monkeypatch.delenv("OPENAI_BASE_URL")
    llm._http_backend("openai/gpt-5-mini", [{"role": "user", "content": "x"}], max_tokens=4096, effort="low")
    url, _, payload = seen[-1]
    assert url == "https://api.openai.com/v1/chat/completions"
    assert "max_tokens" not in payload and payload["max_completion_tokens"] >= 16000  # GPT-5 trả 400 với max_tokens
    assert payload["reasoning_effort"] == "low" and "effort" not in payload


def test_config_local_overrides(tmp_path):
    (tmp_path / "config.yaml").write_text(
        "models:\n  cheap: {model: anthropic/a, effort: low}\n  strong: {model: anthropic/b}\n"
        "capsule:\n  owner_name: X\n  turns: 300\n", encoding="utf-8")
    (tmp_path / "config.local.yaml").write_text(
        "models:\n  cheap: {model: agent/h}\ncapsule:\n  owner_name: An\n", encoding="utf-8")
    c = load_config(tmp_path / "config.yaml")
    assert c.raw["models"]["cheap"] == {"model": "agent/h"}  # vai thay nguyên cụm (không dính effort)
    assert c.raw["models"]["strong"] == {"model": "anthropic/b"}
    assert c.raw["capsule"] == {"owner_name": "An", "turns": 300}


def test_prefilter_embed_off_no_numpy_needed(tmp_path):
    from capsule.prefilter import _cos_lookup
    from pc.config import Config
    cos = _cos_lookup(Config(root=tmp_path, raw={"capsule": {"embed": "off"}}), ["a", "b"])
    assert cos("a", "b") is None
