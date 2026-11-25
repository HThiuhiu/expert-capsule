"""Skill/plugin Expert Capsule: thư mục làm việc, duyệt không tương tác, manifest, gói zip tự chạy."""
import json
import re
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

import pytest
import yaml

import capsule
from capsule import review, workspace
from pc.config import load_config
from test_capsule import _cfg, _synth, _write_work

ROOT = Path(__file__).resolve().parents[1]


def _front(path: Path) -> tuple[dict, str]:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"---\n(.*?)\n---\n(.*)", text, re.S)
    assert m, f"{path} thiếu frontmatter"
    return yaml.safe_load(m.group(1)), m.group(2)


# ---------- thư mục làm việc ----------

def test_init_writes_workspace_and_is_idempotent(tmp_path):
    ws = tmp_path / "ws"
    msg = workspace.init(ws, "Nguyễn Văn Đức", None, "agent")
    assert "Tiếp: capsule ingest" in msg
    assert (ws / "data" / "raw").is_dir() and (ws / ".gitignore").read_text(encoding="utf-8").strip().endswith("*")
    cfg = load_config(root=ws)
    assert cfg.raw["capsule"]["owner_name"] == "Nguyễn Văn Đức" and cfg.raw["capsule"]["slug"] == "nguyen-van-duc"
    assert cfg.raw["models"]["cheap"] == {"model": "agent/claude-haiku"}
    assert cfg.raw["models"]["strong"] == {"model": "agent/claude-sonnet"}
    (ws / "config.local.yaml").write_text("capsule:\n  owner_name: Giữ\n", encoding="utf-8")
    assert "Giữ nguyên" in workspace.init(ws, "Khác", None, "haiku")  # không ghi đè khi thiếu --force
    assert load_config(root=ws).raw["capsule"]["owner_name"] == "Giữ"
    with pytest.raises(ValueError, match="capsule"):
        workspace.init(tmp_path / "x", "A", "capsule", "agent")


def test_status_points_to_next_step(tmp_path):
    workspace.init(tmp_path, "An", "an", "agent")
    text, nxt = workspace.status(load_config(root=tmp_path))
    assert nxt.startswith("capsule ingest") and "[ ] 1 ingest" in text


# ---------- duyệt không tương tác (agent hỏi trong chat) ----------

def test_review_show_and_decide(tmp_path):
    cfg = _cfg(tmp_path)
    _write_work(cfg, _synth())
    out = review.show(cfg)
    assert "### LT-02" in out and "Bằng chứng" in out and "M1 (Thuật toán): Khi nào A?" in out
    assert "### TX-01" not in review.show(cfg, ["LT-02"])
    with pytest.raises(ValueError, match="XX-99"):
        review.decide(cfg, keep=["LT-01", "XX-99"])
    assert review.load(cfg)["decisions"] == {}  # mã sai: không ghi gì
    msg = review.decide(cfg, keep=["lt-01"], delete=["LT-02"], edits={"TX-01": {"do": "Nêu độ phức tạp trước."}},
                        answers={"M1": "Khi viết báo cáo."})
    assert "giữ 1" in msg and "xoá 1" in msg and "sửa 1" in msg and "trả lời 1" in msg and "capsule build" in msg
    rv = review.load(cfg)
    assert rv["decisions"]["LT-02"]["action"] == "delete" and rv["deleted"][0]["code"] == "LT-02"
    assert rv["decisions"]["TX-01"] == {**rv["decisions"]["TX-01"], "action": "edit", "do": "Nêu độ phức tạp trước."}
    assert rv["answers"][0]["answer"] == "Khi viết báo cáo."
    applied = review.apply(_synth(), rv)
    assert [r["code"] for r in applied["domains"]["lt"]["rules"]] == ["LT-01"]
    assert applied["domains"]["tx"]["rules"][0]["do"] == "Nêu độ phức tạp trước."
    assert "còn 0 luật" in review.decide(cfg, keep_rest=True).lower()
    with pytest.raises(ValueError, match="Vừa giữ"):
        review.decide(cfg, keep=["LT-01"], delete=["LT-01"])


# ---------- manifest, SKILL.md, phiên bản ----------

def test_skill_manifest_and_versions_agree():
    meta, body = _front(ROOT / "SKILL.md")
    assert meta["name"] == "expert-capsule" and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", meta["name"])
    assert len(meta["description"]) <= 1024 and "<" not in meta["description"] and ">" not in meta["description"]
    assert len(meta.get("compatibility", "")) <= 500
    assert len(body.splitlines()) < 500 and len(body.split()) < 3500  # phần thân gọn (spec: dưới 5.000 token)
    for link in re.findall(r"\]\(([^)#]+)\)", body):  # mọi link tương đối trỏ tới file có thật
        assert (ROOT / link).exists(), link
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))
    market = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text(encoding="utf-8"))
    py = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    entry = next(p for p in market["plugins"] if p["name"] == plugin["name"])
    assert capsule.__version__ == py == plugin["version"] == entry["version"] == meta["metadata"]["version"]
    assert plugin["skills"] == ["./"] and entry["source"] == "./"
    agent, prompt = _front(ROOT / "agents" / "capsule-worker.md")
    assert agent["name"] == "capsule-worker" and agent["model"] == "haiku" and set(agent["tools"]) == {"Read", "Write"}
    assert "END OF BUNDLE" in prompt


def test_default_config_ships_inside_package():
    from pc.config import DEFAULT_CONFIG
    assert DEFAULT_CONFIG.parent == Path(sys.modules["pc.config"].__file__).parent and DEFAULT_CONFIG.exists()
    assert not (ROOT / "config.yaml").exists()  # một nguồn duy nhất: không để bản sao trôi lệch


# ---------- gói zip tự chạy (Claude.ai, agent khác) ----------

def test_skill_zip_runs_standalone(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    try:
        import build_skill_zip
    finally:
        sys.path.pop(0)
    z = build_skill_zip.build(tmp_path / "dist")
    names = zipfile.ZipFile(z).namelist()
    assert all(n.startswith("expert-capsule/") for n in names) and "expert-capsule/SKILL.md" in names
    assert "expert-capsule/src/capsule/cli.py" in names and "expert-capsule/src/pc/config.default.yaml" in names
    assert not [n for n in names if re.search(r"(^|/)(tests|examples|vendor|data|\.cache|private|__pycache__)/", n)]
    zipfile.ZipFile(z).extractall(tmp_path / "x")
    launcher = tmp_path / "x" / "expert-capsule" / "scripts" / "capsule.py"
    run = lambda *a: subprocess.run([sys.executable, str(launcher), *a], capture_output=True, text=True,
                                    encoding="utf-8", cwd=tmp_path)
    v = run("--version")
    assert v.returncode == 0 and capsule.__version__ in v.stdout
    assert str((tmp_path / "x").resolve()) in v.stdout  # chạy đúng mã trong gói, không phải bản cài sẵn
    ws = tmp_path / "ws"
    assert run("-C", str(ws), "init", "--owner", "An", "--mode", "agent").returncode == 0
    st = run("-C", str(ws), "status")
    assert st.returncode == 0 and "capsule ingest" in st.stdout
