import json
from pathlib import Path

import pytest

from pc.induce.consolidate import consolidate, nearest
from pc.pack.build import _strip, run_writer, slug_for
from pc.pack.evidence import l1_stats, surface

ROOT = Path(__file__).resolve().parents[1]


def test_surface_and_l1():
    f = surface("Chào bạn, sửa giúp:\n1. a\n2. b\ncảm ơn?")
    assert f["greet"] and f["thanks"] and f["numbered"] and f["question"] and not f["paste"]
    st = l1_stats(["fix đi", "```code```"])
    assert st["n_turns"] == 2 and st["paste"] == 0.5


def test_slug_and_strip():
    assert slug_for("An", "ml_ai_research") == "an-ml-ai-research"
    assert _strip("```markdown\n# A\n```") == "# A\n"


def C(eid, sid):
    return {"when": "x", "do_or_dont": "Làm: y", "because": "", "aspects": [], "task_types": ["build_code"],
            "exclusive": True, "idiosyncrasy": "personal", "source_event_id": eid, "session_id": sid, "created_at": eid}


def test_embedding_nearest_uses_cosine_threshold():
    np = pytest.importorskip("numpy")  # extra [embed]/[gpu]
    v = {"e1": np.array([1.0, 0.0]), "e2": np.array([0.9, 0.436]), "e3": np.array([0.0, 1.0])}
    rules, _, _ = consolidate([C("e1", "s1")], lambda c, n: {"op": "ADD", "rule_id": "", "new_when": ""}, vec=v)
    assert [r["rule_id"] for r in nearest(rules, C("e2", "s2"), vec=v)] == ["r001"]
    assert nearest(rules, C("e3", "s3"), vec=v) == []


def test_distilly_writer_creates_skill(tmp_path):
    meta = {"name": "T · x", "display_name": "T · x", "character": "colleague",
            "classification": {"language": "vi", "tags": ["persona-capsule", "x"]}, "profile": {"role": "chuyên gia x"}}
    d = run_writer(ROOT, tmp_path, "t-x", "T · x", meta, "# Work\n\nA\n", "# Persona\n\nB\n")
    assert (d / "SKILL.md").exists() and (d / "work.md").read_text(encoding="utf-8").startswith("# Work")
    m = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    assert m["classification"]["tags"][-1] == "x"
    run_writer(ROOT, tmp_path, "t-x", "T · x", meta, "# Work\n\nA2\n", "# Persona\n\nB\n")  # lần 2: backup
    assert any((d / "versions").iterdir())
