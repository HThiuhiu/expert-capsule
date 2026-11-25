"""Đưa capsule vào AI (spec v1.0 mục 3), và demo có/không capsule.

- `zip`: expert/dist/expert-<slug>.zip, chứa thư mục expert-<slug>/ (SKILL.md, references/, capsule.json).
  Tải lên Claude.ai: Settings > Capabilities > Skills > Upload skill.
- `claude-code`: chép vào thư mục skills của Claude Code ($CLAUDE_CONFIG_DIR/skills hoặc ~/.claude/skills).
Không bao giờ chép private/ (bằng chứng nguyên văn, event, bản sửa).
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import zipfile
from pathlib import Path

from .common import NeedAgents, ask_many, capsule_dir, read_json, role, stable, work_dir, write_json

SHARE = ("SKILL.md", "references", "capsule.json")
MARK = ".capsule-installed"


def _files(out: Path) -> list[Path]:
    fs = []
    for item in SHARE:
        p = out / item
        if p.is_dir():
            fs += sorted(f for f in p.rglob("*") if f.is_file())
        elif p.exists():
            fs.append(p)
    assert not any("private" in f.relative_to(out).parts for f in fs)
    return fs


def _check(out: Path) -> None:
    if not (out / "SKILL.md").exists():
        raise FileNotFoundError(f"Chưa có {out / 'SKILL.md'}. Chạy `capsule package` trước.")


def make_zip(cfg) -> Path:
    out = capsule_dir(cfg)
    _check(out)
    dist = out.parent / "dist"
    dist.mkdir(exist_ok=True)
    z = dist / f"{out.name}.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in _files(out):
            zf.write(f, f"{out.name}/{f.relative_to(out).as_posix()}")
    return z


def default_skills_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude") / "skills"


def install_dir(cfg, dest: Path | None = None, force: bool = False) -> Path:
    """Chép phần chia sẻ được vào <dest>/expert-<slug>/. Chỉ ghi đè thư mục do lệnh này cài trước đó."""
    out = capsule_dir(cfg)
    _check(out)
    target = (dest or default_skills_dir()) / out.name
    if target.exists():
        if not (target / MARK).exists() and not force:
            raise FileExistsError(f"{target} đã có và không do `capsule install` tạo. Dùng --force nếu chắc chắn.")
        shutil.rmtree(target)
    for f in _files(out):
        p = target / f.relative_to(out)
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, p)
    meta = read_json(out / "capsule.json", {}) or {}
    (target / MARK).write_text(json.dumps({"source": str(out), "version": meta.get("capsule_version"),
                                           "at": dt.datetime.now().isoformat(timespec="seconds")}), encoding="utf-8")
    return target


# ---------- demo: cùng câu hỏi, có và không có capsule ----------

BASE = "You are a helpful assistant."
WRAP = ("{q}\n\n(Định dạng trả về cho hệ thống demo: một JSON object {{\"answer\": \"...\"}}, trong đó answer là câu trả "
        "lời đầy đủ bằng Markdown, đúng như bạn sẽ trả lời người dùng.)")


def demo(cfg, llm, questions: list[str], blind: bool = False) -> str:
    out = capsule_dir(cfg)
    sp = out / "exports" / "system_prompt.md"
    if not sp.exists():
        raise FileNotFoundError(f"Chưa có {sp}. Chạy `capsule package` trước.")
    system = sp.read_text(encoding="utf-8").split("-->", 1)[-1].strip()
    prompts = [WRAP.format(q=q) for q in questions]
    ok = lambda d: isinstance(d.get("answer"), str) and d["answer"].strip()
    cap = ask_many(llm, role(cfg, "strong"), prompts, tag="demo_capsule", system=system, check=ok, max_tokens=4000)
    base = ask_many(llm, role(cfg, "strong"), prompts, tag="demo_base", system=BASE, check=ok, max_tokens=4000)
    if cap.pending + base.pending:
        raise NeedAgents("Demo", cap.pending + base.pending)
    if blind:
        return _blind(cfg, out.name, questions, cap.answers, base.answers)
    L = [f"# Demo: cùng câu hỏi, có và không có capsule `{out.name}`", "",
         f"Model: `{role(cfg, 'strong')['model']}`. Hệ có capsule dùng `exports/system_prompt.md` (cách nạp qua API).", ""]
    for i, (q, c, b) in enumerate(zip(questions, cap.answers, base.answers)):
        L += [f"## Câu {i + 1}", "", f"> {q}", "", "### Không có capsule", "", (b or {}).get("answer", "(lỗi)").strip(), "",
              "### Có capsule", "", (c or {}).get("answer", "(lỗi)").strip(), ""]
    md = "\n".join(L) + "\n"
    (work_dir(cfg) / "demo.md").write_text(md, encoding="utf-8")
    return md


def _ans(a) -> str:
    return (a or {}).get("answer", "(lỗi)").strip()


def _blind(cfg, name: str, questions: list[str], cap: list, base: list) -> str:
    """Thử mù: A/B theo thứ tự ngẫu nhiên (ổn định theo câu hỏi); khoá đáp án lưu riêng, `--reveal` mới mở."""
    key = []
    L = ["# Thử mù: câu trả lời nào giống cách bạn muốn hơn?", "",
         "Mỗi câu có hai câu trả lời, A và B, thứ tự ngẫu nhiên: một bản có capsule, một bản không. Chọn bản bạn thấy "
         "đúng cách mình làm việc hơn, rồi chạy `capsule demo --reveal A B ...` (một chữ cho mỗi câu, theo thứ tự).", ""]
    for i, (q, c, b) in enumerate(zip(questions, cap, base)):
        cap_first = stable("demo", name, q) < 0.5
        x, y = (c, b) if cap_first else (b, c)
        key.append({"question": q, "capsule": "A" if cap_first else "B"})
        L += [f"## Câu {i + 1}", "", f"> {q}", "", "### A", "", _ans(x), "", "### B", "", _ans(y), ""]
    write_json(work_dir(cfg) / "demo_key.json", {"capsule": name, "items": key})
    md = "\n".join(L) + "\n"
    (work_dir(cfg) / "demo_blind.md").write_text(md, encoding="utf-8")
    return md


def reveal(cfg, choices: list[str]) -> str:
    """Mở khoá thử mù. Có lựa chọn của người dùng (A/B mỗi câu) thì chấm và ghi vào demo_votes.jsonl."""
    k = read_json(work_dir(cfg) / "demo_key.json")
    if not k:
        raise FileNotFoundError("Chưa có thử mù. Chạy `capsule demo --blind \"<câu hỏi>\"` trước.")
    items = k["items"]
    choices = [c.strip().upper() for c in choices]
    if choices and (len(choices) != len(items) or any(c not in ("A", "B") for c in choices)):
        raise ValueError(f"Cần đúng {len(items)} lựa chọn A hoặc B, theo thứ tự câu hỏi.")
    L = []
    for i, it in enumerate(items):
        line = f"Câu {i + 1}: bản có capsule là {it['capsule']}"
        if choices:
            line += f"; bạn chọn {choices[i]} ({'có capsule' if choices[i] == it['capsule'] else 'không capsule'})"
        L.append(line)
    if choices:
        hit = sum(c == it["capsule"] for c, it in zip(choices, items))
        L.append(f"\nBạn chọn bản có capsule ở {hit}/{len(items)} câu.")
        with open(work_dir(cfg) / "demo_votes.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"at": dt.datetime.now().isoformat(timespec="seconds"), "capsule": k["capsule"],
                                "n": len(items), "hit": hit, "choices": choices}, ensure_ascii=False) + "\n")
    return "\n".join(L)
