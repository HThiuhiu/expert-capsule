"""Chạy trọn chế độ Lite như người mới clone repo: ingest -> domains -> build -> package -> install.

Model giả đọc prompt của từng bước và trả JSON đúng dạng; không gọi mạng. Bắt lỗi nối các bước, thư mục còn thiếu,
và kiểm tra capsule ra đủ file, không lộ private/.
"""
import json
import re
import shutil
import zipfile
from pathlib import Path

import pc.llm
from capsule.cli import main
from fixtures import chatgpt_branched, chatgpt_merge, chatgpt_short, claude_flat, claude_tree

ROOT = Path(__file__).resolve().parents[1]


def _J(o):
    return {"text": json.dumps(o, ensure_ascii=False), "input_tokens": 1, "output_tokens": 1}


def fake_backend(model, messages, **params):
    p = messages[-1]["content"]
    data = p.split("<data>\n", 1)[1].split("\n</data>", 1)[0] if "<data>" in p else ""
    if p.startswith("For each chat session below"):
        n = len(re.findall(r"^\[s\d+\]", data, re.M))
        return _J({"sessions": [{"id": f"s{i + 1}", "domain": "software testing", "task_type": "debug code"}
                                for i in range(n)]})
    if p.startswith("Below are raw labels"):
        dom, task = data.split("TASK_TYPE LABELS:")
        lab = lambda s: re.findall(r"^- (.+) \(\d+\)$", s, re.M)
        return _J({"domains": [{"slug": "kiem-thu", "name": "Kiểm thử", "members": lab(dom)}],
                   "task_types": [{"slug": "sua-loi", "name": "Sửa lỗi", "members": lab(task)}]})
    if p.startswith("Each item is one USER_TURN"):
        items = []
        for m in re.finditer(r"\[t(\d+)\]\n(.*?)(?=\n\n\[t\d+\]\n|\Z)", data, re.S):
            user = m.group(2).split("USER_TURN:\n", 1)[1].strip()
            items.append({"id": f"t{m.group(1)}", "type": "correct_with_fix", "aspects": ["correctness"],
                          "level": "personal", "quote": user[:8], "want": "Làm đúng yêu cầu.", "issue": "AI sai.",
                          "reusable": True})
        return _J({"items": items})
    if "give the MOVE of every user turn" in p:
        n = [int(x) for x in re.findall(r"\((\d+) user turns\)", data)]
        return _J({"sessions": [{"id": f"s{i + 1}", "moves": ["probe"] * k} for i, k in enumerate(n)]})
    if p.startswith("Below are feedback events"):
        ids = re.findall(r"^(E\w+) \|", data, re.M)
        return _J({"rules": [{"when": "người dùng báo lỗi", "do": "Sửa đúng chỗ được chỉ ra.", "because": "(suy luận)",
                              "scope": "", "exceptions": "", "level": "personal", "events": ids}],
                   "conflicts": [], "cases": [{"event": ids[0], "context": "c", "cue": "q", "judgment": "j",
                                               "action": "a", "exception": "", "outcome": "o"}]})
    if p.startswith("These are move sequences"):
        return _J({"playbooks": [{"task_type": t, "steps": ["Đọc lỗi"], "stop_when": "x", "when_ai_fails": "y"}
                                 for t in re.findall(r"^TASK_TYPE (\S+)", data, re.M)]})
    if p.startswith("Below: statistics"):
        sample = re.search(r"SAMPLE MESSAGES:\n- (.+)", data).group(1)
        return _J({"style": [{"rule": "Trả lời ngắn", "example": sample[:15], "events": []}]})
    if p.startswith("Below are standards one person enforces"):
        return _J({"core": []})
    if p.startswith("Below are the standards one person enforces"):
        return _J({"exemplars": [{"question": "Q?", "answer": "A.", "rules": []}]})
    if p.startswith("A user sent the REQUEST below"):
        return _J({"critiques": ["a", "b", "c"]})
    if p.startswith("For each item, decide"):
        n = len(re.findall(r"^\[q\d+\]", data, re.M))
        return _J({"items": [{"id": f"q{i + 1}", "x_hit": True, "y_hit": False} for i in range(n)]})
    raise AssertionError("prompt lạ: " + p[:80])


def test_lite_end_to_end(tmp_path, monkeypatch, capsys):
    shutil.copy(ROOT / "config.yaml", tmp_path / "config.yaml")
    (tmp_path / "config.local.yaml").write_text(
        "capsule:\n  owner_name: An\n  slug: an\n  thin_sessions: 1\n  quickcheck_n: 1\n", encoding="utf-8")
    for sub, convs in (("chatgpt", [chatgpt_branched(), chatgpt_merge(), chatgpt_short()]),
                       ("claude", [claude_flat(), claude_tree()])):
        d = tmp_path / "data" / "raw" / sub
        d.mkdir(parents=True)
        (d / "conversations.json").write_text(json.dumps(convs, ensure_ascii=False), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PC_CONFIG", raising=False)
    monkeypatch.setattr(pc.llm, "_http_backend", fake_backend)

    assert main(["ingest"]) == 0
    assert "Tiếp: capsule domains" in capsys.readouterr().out
    # quên đặt key: dừng có hướng dẫn, không lưu danh sách lĩnh vực rỗng
    def no_key(*a, **k):
        raise TypeError("Could not resolve authentication method")
    monkeypatch.setattr(pc.llm, "_http_backend", no_key)
    assert main(["domains"]) == 1
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err
    assert not (tmp_path / "data" / "lite" / "domains.json").exists()
    monkeypatch.setattr(pc.llm, "_http_backend", fake_backend)
    assert main(["domains"]) == 0
    assert main(["build", "--domains", "kiem-thu"]) == 0
    assert main(["package"]) == 0
    out = tmp_path / "expert" / "expert-an"
    skill = (out / "SKILL.md").read_text(encoding="utf-8")
    assert skill.startswith("---\nname: expert-an\n") and "Cách làm việc của An" in skill
    dom = (out / "references" / "domains" / "kiem-thu.md").read_text(encoding="utf-8")
    assert "KT-01" in dom and "Sửa đúng chỗ được chỉ ra." in dom
    meta = json.loads((out / "capsule.json").read_text(encoding="utf-8"))
    assert meta["quickcheck"]["n"] == 1 and meta["n_events"] >= 2
    assert (tmp_path / "reports" / "lite_build_an.md").exists()

    assert main(["install", "--target", "zip"]) == 0
    names = zipfile.ZipFile(tmp_path / "expert" / "dist" / "expert-an.zip").namelist()
    assert "expert-an/SKILL.md" in names and not any("private" in n for n in names)
    assert main(["install", "--target", "claude-code", "--dir", str(tmp_path / "skills")]) == 0
    assert (tmp_path / "skills" / "expert-an" / "SKILL.md").exists()
    # chạy lại: mọi thứ từ cache, không gọi model
    monkeypatch.setattr(pc.llm, "_http_backend", lambda *a, **k: (_ for _ in ()).throw(AssertionError("gọi lại")))
    assert main(["build", "--domains", "kiem-thu"]) == 0
