"""Bước 8: đóng gói. Sinh SKILL.md, file lĩnh vực, references/ và exports/ từ cùng một nguồn (data/lite/synth.json
sau khi áp quyết định duyệt). Ghi capsule.json. Lưu bản trước vào private/versions/.

Cấu trúc (spec v1.0 mục 1):
  expert-<slug>/SKILL.md, references/domains/*.md, references/style.md, references/exemplars.md,
  exports/{custom_instructions.txt, project_instructions.md, system_prompt.md}, capsule.json,
  private/{evidence.jsonl, events.jsonl, corrections.jsonl, review.json, versions/}
"""
from __future__ import annotations

import datetime as dt
import shutil
from collections import Counter

from pc.textutil import approx_tokens

from .. import review
from ..common import base_dir, capsule_dir, read_json, read_jsonl, settings, work_dir, write_json, write_jsonl
from ..quickcheck import headline
from . import exports, redact
from .skill import domain_list, mark_answered, render_domain, render_exemplars, render_skill, render_style

SHARED = ("SKILL.md", "references", "exports", "capsule.json")


def _backup(out, version: int) -> None:
    dst = out / "private" / "versions" / f"v{version}"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for name in SHARED:
        p = out / name
        if p.is_dir():
            shutil.copytree(p, dst / name)
        elif p.exists():
            shutil.copy2(p, dst / name)


def package(cfg, targets: list[str] | None = None) -> str:
    st = settings(cfg)
    wd = work_dir(cfg)
    synth = read_json(wd / "synth.json")
    if not synth:
        return "Chưa có luật. Chạy `capsule build` trước."
    rv = review.load(cfg)
    s = mark_answered(review.apply(synth, rv), rv)
    q = read_json(wd / "quickcheck.json", {}) or {}
    dom_info = read_json(base_dir(cfg) / "domains.json", {}) or {}
    events = read_jsonl(wd / "events.jsonl")
    evs = {e["event_id"]: e for e in events}
    out = capsule_dir(cfg)
    old = read_json(out / "capsule.json", {}) or {}
    version = int(str(old.get("capsule_version", "v0")).lstrip("v") or 0) + 1
    if (out / "SKILL.md").exists():
        _backup(out, version - 1)
    targets = targets or ["skill", "project", "custom", "system"]
    owner = st["owner_name"]
    pii = Counter()

    files: dict[str, str] = {}
    files["SKILL.md"] = render_skill(cfg, s, version)
    for slug, x in domain_list(s):
        files[f"references/domains/{slug}.md"] = render_domain(slug, x, st["max_domain_rules"], st["max_cases"])
    files["references/style.md"] = render_style(owner, s.get("style", []))
    files["references/exemplars.md"] = render_exemplars(s, st["max_exemplars"])
    if "project" in targets:
        files["exports/project_instructions.md"] = exports.project_instructions(cfg, s, version)
    if "custom" in targets:
        files["exports/custom_instructions.txt"] = exports.custom_instructions(owner, s, st["custom_chars"])
    if "system" in targets:
        files["exports/system_prompt.md"] = exports.system_prompt(cfg, s, version, owner)
    files["exports/HUONG_DAN_CAI.md"] = exports.install_guide(f"expert-{st['slug']}", owner, s, st["custom_chars"])
    files = {k: redact.clean(v, pii) for k, v in files.items()}
    flags = redact.leaks(files, [e["quote"] for e in events], [x["example"] for x in s.get("style", [])])

    if (out / "references" / "domains").exists():  # bỏ file lĩnh vực cũ không còn chọn
        for p in (out / "references" / "domains").glob("*.md"):
            if f"references/domains/{p.name}" not in files:
                p.unlink()
    for name, text in files.items():
        p = out / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    # private/
    rules = [("core", r) for r in s.get("core", [])] + [(slug, r) for slug, x in s["domains"].items() for r in x["rules"]]
    ev_rows = []
    for where, r in rules:
        ev_rows.append({"code": r["code"], "domain": where, "rule": r["do"], "status": r.get("status", "active"),
                        "reviewed": r.get("reviewed", False),
                        "evidence": [{"event_id": x, "session_id": evs[x]["session_id"], "date": (evs[x].get("created_at") or "")[:10],
                                      "quote": evs[x]["quote"]} for x in r["events"] if x in evs]})
    write_jsonl(out / "private" / "evidence.jsonl", ev_rows)
    write_jsonl(out / "private" / "events.jsonl", events)
    write_json(out / "private" / "review.json", rv)
    if not (out / "private" / "corrections.jsonl").exists():
        (out / "private" / "corrections.jsonl").write_text("", encoding="utf-8")
    write_json(out / "private" / "redact_flags.json", {"pii": dict(pii), "leaks": flags})

    skill_tokens, skill_lines = approx_tokens(files["SKILL.md"]), files["SKILL.md"].count("\n")
    n_rules = {slug: len(x["rules"]) for slug, x in domain_list(s)}
    meta = {
        "name": f"expert-{st['slug']}", "display_name": owner, "capsule_version": f"v{version}", "spec": "1.0",
        "mode": "lite", "created_at": dt.datetime.now().isoformat(timespec="seconds"),
        "domains": [{"slug": slug, "name": x["name"], "n_sessions": x["n_sessions"], "n_events": x["n_events"],
                     "n_rules": n_rules[slug], "n_playbooks": len(x["playbooks"])} for slug, x in domain_list(s)],
        "n_sessions_total": len(dom_info.get("sessions", {})),
        "n_events": len(events), "n_core_rules": len(s.get("core", [])), "n_style": len(s.get("style", [])),
        "n_rules_reviewed": sum(1 for _, r in rules if r.get("reviewed")), "n_rules_total": len(rules),
        "quickcheck": {k: q.get(k) for k in ("n", "capsule_hits", "base_hits", "models")} if q else None,
        "skill_md": {"approx_tokens": skill_tokens, "lines": skill_lines,
                     "within_limits": skill_tokens < 5000 and skill_lines < 500},
        "exports": sorted(k for k in files if k.startswith("exports/")),
    }
    write_json(out / "capsule.json", meta)

    L = [f"Capsule v{version} -> {out}",
         f"- SKILL.md: ~{skill_tokens} token, {skill_lines} dòng ({'trong giới hạn' if meta['skill_md']['within_limits'] else 'VƯỢT giới hạn 5.000 token / 500 dòng'}).",
         f"- Lõi chung {meta['n_core_rules']} luật, văn phong {meta['n_style']} mục, lĩnh vực: "
         + ", ".join(f"{d['name']} {d['n_rules']} luật" for d in meta["domains"]) + ".",
         f"- Đã duyệt {meta['n_rules_reviewed']}/{meta['n_rules_total']} luật.",
         f"- {headline(q)}",
         f"- Che PII: {dict(pii) or 'không có'}. Đoạn trích lọt ra ngoài private/: {len(flags)}.",
         f"- exports/: {', '.join(k.split('/')[-1] for k in meta['exports'])}"]
    if flags:
        L.append("  Xem private/redact_flags.json trước khi chia sẻ.")
    return "\n".join(L)
