from collections import Counter

from pc.ingest.scrub import scrub
from pc.llm import LLM
from pc.textutil import approx_tokens, detect_lang, has_code, is_substring


def test_scrub_secrets_and_pii():
    c = Counter()
    txt = ("key sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123 và sk-proj-ABCDEFGHIJKLMNOPQRSTUV12 "
           "AKIAABCDEFGHIJKLMNOP password: hunter22 mật khẩu: 12345678 "
           "mail an@example.vn gọi 0912 345 678 hoặc +84 912345678")
    out = scrub(txt, c)
    for leak in ("sk-ant-api03", "sk-proj-ABC", "AKIAABC", "hunter22", "12345678", "an@", "0912", "912345678"):
        assert leak not in out, leak
    assert "password: [SECRET]" in out
    assert c["API_KEY"] == 3 and c["EMAIL"] == 1 and c["PHONE"] == 2


def test_scrub_keeps_normal_numbers():
    s = "Doanh thu 2025 tăng 12,5% lên 1.200 tỷ, năm 2024 là 1.067 tỷ"
    assert scrub(s) == s


def test_is_substring_normalizes_whitespace():
    assert is_substring("thiếu   phí\ngiao dịch", "Không phải, thiếu phí giao dịch nhé")
    assert not is_substring("thừa phí", "thiếu phí giao dịch")
    assert not is_substring("   ", "abc")


def test_detect_lang():
    assert detect_lang("Viết cho tôi một hàm tính lãi kép, không dùng thư viện") == "vi"
    assert detect_lang("Write a function that computes compound interest for the user") == "en"
    assert detect_lang("Giải thích giúp tôi the difference between DCF and the multiples approach in valuation") == "mixed"
    assert detect_lang("```python\nprint('xin chào')\n```") == "en"  # bỏ code


def test_tokens_and_code():
    assert approx_tokens("Không phải, sai rồi!") == 6
    assert has_code("```\nx=1\n```")
    assert not has_code("chỉ là chữ")


def test_llm_cache_is_deterministic(tmp_path):
    calls = []

    def fake(model, messages, **params):
        calls.append(1)
        return {"text": f"out-{len(calls)}", "input_tokens": 100, "output_tokens": 10}

    llm = LLM(tmp_path, backend=fake)
    cfg = {"model": "m", "temperature": 0}
    msgs = [{"role": "user", "content": "x"}]
    a = llm.complete(cfg, msgs)
    b = llm.complete(cfg, msgs)
    assert a == b == "out-1" and len(calls) == 1
    assert llm.usage.cache_hits == 1
    assert abs(llm.usage.cost({"m": {"input": 1.0, "output": 5.0}}) - (100 / 1e6 + 50 / 1e6)) < 1e-12
    # LLM mới, offline, đọc lại từ cache
    assert LLM(tmp_path, backend=fake, offline=True).complete(cfg, msgs) == "out-1"
