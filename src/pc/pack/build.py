"""`pc pack`: dựng bộ AI chuyên gia theo đúng create flow của distilly.

Step 3 Track A: prompts/shared/work_analyzer.md   (vai `analyzer`)  -> phân tích Work
Step 3 Track B: prompts/colleague/persona_analyzer.md (vai `analyzer`) -> phân tích Persona
Step 4:         prompts/shared/work_builder.md, prompts/colleague/persona_builder.md (vai `builder`) -> work.md, persona.md
Step 5:         tools/skill_writer.py --action create (sau khi version_manager backup bản cũ)

Khác distilly: "source material" là dữ liệu đã mining (pack/evidence.py) thay vì tài liệu người dùng tải lên,
và người được chưng cất là chính chủ dữ liệu, làm việc với AI trong một domain.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from ..ingest import read_sessions
from ..llm import LLM
from ..mining.gold import read_jsonl
from . import evidence

DOMAIN_VI = {"ml_ai_research": "nghiên cứu ML/AI", "software_web": "phần mềm và web", "algorithms": "thuật toán",
             "coursework": "học tập và ôn thi", "content_creation": "sáng tạo nội dung",
             "quant_finance": "tài chính định lượng", "personal": "việc cá nhân", "other": "việc khác",
             "all": "mọi lĩnh vực"}

ADAPT = """ADAPTATION FOR THIS RUN (overrides the generic instructions above where they conflict):
- The person is {name}. The source material is NOT messages to colleagues. It is {name}'s own chat history with AI
  assistants, already mined into: rules {name} enforces on AI answers, real corrections, workflow (move sequences),
  expression statistics, and praise.
- Interpret Work as {name}'s expertise in the domain "{domain}": the standards an answer must meet, how {name} breaks
  down and drives a problem, recurring technical judgments. Interpret Persona as how {name} communicates, directs,
  decides, pushes back, and what {name} dislikes.
- There are no manual tags: use the material only.
- Write in Vietnamese. Only claims backed by the material. Where evidence is missing write "(Thiếu dữ liệu: ...)".
- No secrets, emails, phone numbers, file paths, personal names other than {name}. Quotes at most 20 words each.
- Output the requested content only, as Markdown, no code fences around the whole answer."""


def _prompt(root: Path, rel: str, name: str) -> str:
    return (root / "vendor" / "distilly" / rel).read_text(encoding="utf-8").replace("{name}", name)


def _strip(md: str) -> str:
    md = md.strip()
    m = re.fullmatch(r"```(?:markdown|md)?\s*\n(.*)\n```", md, re.S)
    return (m.group(1) if m else md).strip() + "\n"


def slug_for(owner: str, domain: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", f"{owner}-{domain}".lower()).strip("-")
    return s[:40].strip("-")


def run_writer(root: Path, base: Path, slug: str, name: str, meta: dict, work: str, persona: str) -> Path:
    tools = root / "vendor" / "distilly" / "tools"
    tmp = root / ".cache" / "pack" / slug
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    (tmp / "work.md").write_text(work, encoding="utf-8")
    (tmp / "persona.md").write_text(persona, encoding="utf-8")
    if (base / slug / "SKILL.md").exists():  # distilly: lưu bản cũ trước khi ghi đè
        subprocess.run([sys.executable, str(tools / "version_manager.py"), "--action", "backup", "--character",
                        "colleague", "--slug", slug, "--base-dir", str(base)], check=True, capture_output=True)
    r = subprocess.run([sys.executable, str(tools / "skill_writer.py"), "--action", "create", "--character",
                        "colleague", "--slug", slug, "--name", name, "--meta", str(tmp / "meta.json"),
                        "--work", str(tmp / "work.md"), "--persona", str(tmp / "persona.md"), "--base-dir", str(base),
                        "--no-install-claude-skill"], capture_output=True, text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"skill_writer lỗi: {r.stderr[-1500:]}")
    return base / slug


def build_pack(cfg, llm: LLM, domain: str, material: str, stats: dict, owner: str, log=print) -> dict:
    root = cfg.root
    dname = DOMAIN_VI.get(domain, domain)
    adapt = ADAPT.format(name=owner, domain=dname)
    ana, bld = cfg.model("analyzer"), cfg.model("builder")

    def ask(role, system, user, mx):
        return llm.complete(role, [{"role": "system", "content": system}, {"role": "user", "content": user}],
                            max_tokens=mx)

    log(f"[{domain}] analyzer Work + Persona")
    work_an = ask(ana, _prompt(root, "prompts/shared/work_analyzer.md", owner) + "\n\n" + adapt,
                  "<source_material>\n" + material + "\n</source_material>", 6000)
    pers_an = ask(ana, _prompt(root, "prompts/colleague/persona_analyzer.md", owner) + "\n\n" + adapt,
                  "<source_material>\n" + material + "\n</source_material>", 6000)
    log(f"[{domain}] builder work.md + persona.md")
    work = _strip(ask(bld, _prompt(root, "prompts/shared/work_builder.md", owner) + "\n\n" + adapt,
                      f"Analysis from work_analyzer:\n\n{work_an}\n\nGenerate the full work.md content now.", 8000))
    persona = _strip(ask(bld, _prompt(root, "prompts/colleague/persona_builder.md", owner) + "\n\n" + adapt,
                         f"Analysis from persona_analyzer:\n\n{pers_an}\n\nGenerate the full persona.md content now.",
                         8000))
    slug = slug_for(owner, domain)
    name = f"{owner} · chuyên gia {dname}"
    meta = {"name": name, "display_name": name, "character": "colleague",
            "summary": f"Bộ AI chuyên gia {dname}, chưng cất từ {stats['n_sessions']} phiên chat của {owner} "
                       f"({stats['n_events']} lượt sửa sai, {stats['n_rules']} quy tắc).",
            "classification": {"language": "vi", "tags": ["persona-capsule", domain]},
            "profile": {"role": f"chuyên gia {dname}", "specialty": ", ".join(list(stats["task_types"])[:4])},
            "tags": {"personality": [], "culture": []},
            "knowledge_sources": [f"persona-capsule mining: {stats['n_sessions']} phiên ChatGPT + Claude"],
            "persona_capsule": stats}
    base = root / cfg.raw.get("pack", {}).get("out_dir", "skills") / "colleague"
    d = run_writer(root, base, slug, name, meta, work, persona)
    (d / "knowledge" / "docs").mkdir(parents=True, exist_ok=True)
    (d / "knowledge" / "analysis_work.md").write_text(work_an, encoding="utf-8")
    (d / "knowledge" / "analysis_persona.md").write_text(pers_an, encoding="utf-8")
    log(f"[{domain}] -> {d}")
    return {"domain": domain, "slug": slug, "dir": str(d), **stats}


def build_owner(cfg, llm: LLM, owner: str, all_dir: Path, log=print) -> Path:
    """distilly owner flow: prompts/owner/profile_builder.md -> skills/owner/profile.md (chưa link vào CLAUDE.md)."""
    root = cfg.root
    an_w = (all_dir / "knowledge" / "analysis_work.md").read_text(encoding="utf-8")
    an_p = (all_dir / "knowledge" / "analysis_persona.md").read_text(encoding="utf-8")
    sys_p = ((root / "vendor" / "distilly" / "prompts" / "owner" / "profile_builder.md").read_text(encoding="utf-8")
             + "\n\nADAPTATION: no interview was run. The only source is the owner's mined chat history with AI "
               "(source label: `export: chatgpt+claude`). Write in Vietnamese. Mark inferences `(inferred)`. "
               "Use today's date 2026-11-22. Output the profile Markdown only.")
    md = _strip(llm.complete(cfg.model("builder"), [
        {"role": "system", "content": sys_p},
        {"role": "user", "content": f"Owner preferred name: {owner}\n\n# Work analysis\n{an_w}\n\n# Persona analysis\n{an_p}"}],
        max_tokens=6000))
    sys.path.insert(0, str(root / "vendor" / "distilly" / "tools"))
    from owner_profile import check_profile  # distilly: kiểm tóm tắt luôn bật, bí mật
    try:
        check_profile(md)
        err = ""
    except ValueError as e:
        err = str(e)
    out = root / cfg.raw.get("pack", {}).get("out_dir", "skills") / "owner" / "profile.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    log(f"[owner] -> {out}" + (f" (cảnh báo: {err})" if err else ""))
    return out


def build_all(cfg, domains: list[str] | None = None, log=print) -> list[dict]:
    inter = cfg.path("interim")
    sessions = {s.session_id: s for s in read_sessions(inter / "sessions.jsonl")}
    rules = read_jsonl(cfg.path("capsule") / "rules.jsonl")
    cases = {c["event_id"]: c for c in read_jsonl(cfg.path("capsule") / "cases.jsonl")}
    events = read_jsonl(inter / "events.jsonl")
    rows = {r["turn_id"]: r for r in read_jsonl(inter / "turn_labels.jsonl")}
    text = {t.turn_id: t.text for s in sessions.values() for t in s.turns if t.role == "user"}
    for tid, r in rows.items():
        if (r.get("labeler") or {}).get("primary_label") == "accept_explicit":
            r["_text"] = text.get(tid, "")
    sp = json.loads((inter / "splits.json").read_text(encoding="utf-8"))["sessions"]
    use = set(cfg.raw.get("induce", {}).get("splits") or ["train"])
    meta, by = evidence.domain_index(cfg)
    pk = cfg.raw.get("pack", {})
    owner = pk.get("owner_name", "owner")
    llm = LLM(cfg.path("cache"))
    out = []
    plan = {d: {s for s in sids if sp.get(s) in use} for d, sids in by.items()}
    plan["all"] = {s for sids in plan.values() for s in sids}
    for d, sids in sorted(plan.items(), key=lambda x: -len(x[1])):
        if domains and d not in domains:
            continue
        if d not in ("all",) and (len(sids) < pk.get("min_sessions", 25) or d in ("other", "personal")):
            continue
        material, stats = evidence.build(cfg, d, sids, sessions, rules, cases, events, rows, meta)
        out.append(build_pack(cfg, llm, d, material, stats, owner, log))
    alld = [o for o in out if o["domain"] == "all"]
    if alld:
        build_owner(cfg, llm, owner, Path(alld[0]["dir"]), log)
    log(f"Chi phí API: ~${llm.usage.cost(cfg.raw.get('pricing', {})):.3f} ({llm.usage.calls} lệnh gọi mới)")
    return out
