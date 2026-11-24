"""CLI `pc` (D2). Mỗi bước dừng ở cổng, không tự chạy sang bước sau (D5)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config

NOT_YET = "Chưa triển khai: theo D5, bước này chỉ làm sau khi bạn duyệt `reports/step0_data.md`."


def cmd_ingest(args) -> int:
    from .ingest import ingest, write_sessions
    from .reports.step0 import render

    cfg = load_config()
    ing = cfg.ingest
    src = Path(args.path) if args.path else cfg.path("raw")
    if not src.exists():
        print(f"Không thấy {src}. Đặt export ChatGPT/Claude vào data/raw/ (D6.1).", file=sys.stderr)
        return 2
    res = ingest(src, ing.get("min_user_turns", 2), ing.get("include_attachments", True))
    out = cfg.path("interim") / "sessions.jsonl"
    write_sessions(res.sessions, out)
    rep = cfg.path("reports") / "step0_data.md"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(render(res, ing.get("gate_min_sessions", 300), ing.get("min_user_turns", 2)), encoding="utf-8")
    print(f"{len(res.sessions)} phiên -> {out}")
    print(f"Báo cáo -> {rep}")
    print("Dừng ở cổng Step 0. Chờ bạn xem báo cáo.")
    return 0


def cmd_inspect(args) -> int:
    from .ingest.inspect import inspect_export

    print(inspect_export(Path(args.path)))
    return 0


def cmd_mine(args) -> int:
    from .ingest import read_sessions
    from .llm import estimate_cost

    cfg = load_config()
    sp = cfg.path("interim") / "sessions.jsonl"
    if not sp.exists():
        print("Chưa có sessions.jsonl. Chạy `pc ingest` trước.", file=sys.stderr)
        return 2
    sessions = read_sessions(sp)
    n = sum(max(s.n_user_turns - 1, 0) for s in sessions)  # lượt user idx > 0
    pricing = cfg.raw.get("pricing", {})
    lab, ver = cfg.model("labeler")["model"], cfg.model("verifier")["model"]
    # D4: labeler ~2.500 token vào/lượt; verifier ~20-30% lượt x 6.000 token. Đầu ra JSON ~200 token.
    c_lab = estimate_cost(n * 2500, n * 200, lab, pricing)
    c_ver_lo = estimate_cost(int(n * .20) * 6000, int(n * .20) * 300, ver, pricing)
    c_ver_hi = estimate_cost(int(n * .30) * 6000, int(n * .30) * 300, ver, pricing)
    print(f"Lượt user cần gán: {n}")
    print(f"labeler  ({lab}): ~${c_lab:.2f}")
    print(f"verifier ({ver}): ~${c_ver_lo:.2f} đến ${c_ver_hi:.2f}")
    print(f"Tổng ước lượng: ~${c_lab + c_ver_lo:.2f} đến ${c_lab + c_ver_hi:.2f} "
          f"(ngưỡng xác nhận ${cfg.raw.get('cost_confirm_usd', 20)})")
    if ver.startswith("agent/"):
        print("verifier là subagent (agent/...): không tính tiền API ở đây.")
    if args.estimate:
        return 0

    from .llm import LLM, has_credentials
    from .mining.run import examples_md, render, run, write_outputs

    if args.import_answers:
        n_imp = LLM(cfg.path("cache")).import_answers(Path(args.import_answers))
        print(f"Đã nạp {n_imp} câu trả lời của subagent vào cache.")
    for role in ("labeler", "verifier"):
        if role == "verifier" and args.skip_verify:
            continue
        if not has_credentials(cfg.model(role)["model"]):
            print(f"Thiếu API key cho vai {role} ({cfg.model(role)['model']}).", file=sys.stderr)
            return 2
    total = c_lab + c_ver_hi if not ver.startswith("agent/") else c_lab
    if not args.pilot and total > cfg.raw.get("cost_confirm_usd", 20) and not args.yes:
        print("Ước lượng vượt ngưỡng (D4). Chạy lại với --yes sau khi bạn xác nhận.", file=sys.stderr)
        return 2
    res = run(cfg, pilot=args.pilot, skip_verify=args.skip_verify, workers=args.workers)
    out = cfg.path("interim") / ("pilot" if args.pilot else "")
    write_outputs(res, out)
    rep = cfg.path("reports") / ("step1_pilot.md" if args.pilot else "step1_mining.md")
    rep.write_text(render(res, cfg, args.pilot, out), encoding="utf-8")
    (out / "examples.md").write_text(examples_md(res), encoding="utf-8")
    print(f"{len(res.events)} event, {len(res.firstshot)} firstshot -> {out}")
    print(f"Báo cáo -> {rep}")
    print(f"Chi phí API lần này: ~${res.usage.cost(pricing):.3f} ({res.usage.calls} lệnh gọi mới)")
    if res.n_pending:
        print(f"{res.n_pending} yêu cầu verifier chờ subagent trong {LLM(cfg.path('cache')).queue_dir}. "
              "Trả lời xong: pc mine ... --import-answers <file.jsonl>")
    print("Dừng. Chờ bạn xem báo cáo.")
    return 0


def cmd_gold(args) -> int:
    import json

    from .ingest import read_sessions
    from .mining.gold import gold_task, read_jsonl, review, sample, score, validate_gold

    cfg = load_config()
    inter, gdir = cfg.path("interim"), cfg.path("gold")
    gdir.mkdir(parents=True, exist_ok=True)
    sp, gp = gdir / "sample.jsonl", gdir / "gold_labels.jsonl"
    rows = read_jsonl(inter / "turn_labels.jsonl")
    if not rows:
        print("Chưa có turn_labels.jsonl. Chạy `pc mine` trước.", file=sys.stderr)
        return 2
    if args.action == "sample":
        if sp.exists() and not args.force:
            print(f"{sp} đã có. Dùng --force để lấy lại (sẽ làm lệch gold đã gán).", file=sys.stderr)
            return 2
        S = sample(rows)
        with open(sp, "w", encoding="utf-8") as f:
            for s in S:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        from collections import Counter
        print(f"{len(S)} lượt -> {sp}: {dict(Counter(s['stratum'] for s in S))}")
        return 0
    samples = read_jsonl(sp)
    if not samples:
        print("Chưa có sample.jsonl. Chạy `pc gold sample`.", file=sys.stderr)
        return 2
    sessions = {s.session_id: s for s in read_sessions(inter / "sessions.jsonl")}
    if args.action == "review":
        n = review(samples, sessions, gp, args.annotator)
        print(f"Đã gán {n} lượt -> {gp}")
        return 0
    if args.action == "export":
        out = gdir / "agent_tasks"
        out.mkdir(exist_ok=True)
        done = {g["turn_id"] for g in read_jsonl(gp) if g.get("annotator") == args.annotator}
        n = 0
        for i, s in enumerate(samples):
            if s["turn_id"] in done:
                continue
            (out / f"{i:03d}.md").write_text(gold_task(sessions[s["session_id"]], s["turn_id"]), encoding="utf-8")
            n += 1
        print(f"{n} task -> {out}")
        return 0
    if args.action == "import":
        have = {(g["turn_id"], g.get("annotator")) for g in read_jsonl(gp)}
        want = {s["turn_id"] for s in samples}
        ok = bad = 0
        with open(gp, "a", encoding="utf-8") as f:
            for d in read_jsonl(Path(args.file)):
                g = validate_gold(d)
                if not g or g["turn_id"] not in want or (g["turn_id"], args.annotator) in have:
                    bad += 1
                    continue
                g["annotator"] = args.annotator
                have.add((g["turn_id"], args.annotator))
                f.write(json.dumps(g, ensure_ascii=False) + "\n")
                ok += 1
        print(f"Nạp {ok}, bỏ {bad} -> {gp}")
        return 0
    # score
    rows_by = {r["turn_id"]: r for r in rows}
    md, res = score(samples, read_jsonl(gp), rows_by, read_jsonl(inter / "events.jsonl"), args.annotator)
    rep = cfg.path("reports") / "step1_mining.md"
    if rep.exists():
        txt = rep.read_text(encoding="utf-8")
        cut = txt.find("## Cổng G1 (B6)")
        txt = (txt if cut < 0 else txt[:cut]).rstrip() + "\n\n" + md
        rep.write_text(txt, encoding="utf-8")
    print(md)
    return 0


def cmd_induce(args) -> int:
    from .induce.run import render_report, run, select, write_capsule
    from .llm import LLM, estimate_cost, has_credentials

    cfg = load_config()
    if args.align:
        print("Bước 3 (alignment, B7) cần nhiệm vụ T3 của Module 2 (eval). Chưa làm.", file=sys.stderr)
        return 2
    if not (cfg.path("interim") / "events.jsonl").exists():
        print("Chưa có events.jsonl. Chạy `pc mine` trước.", file=sys.stderr)
        return 2
    rep = cfg.path("reports") / "step1_mining.md"
    if "## Cổng G1 (B6)" not in (rep.read_text(encoding="utf-8") if rep.exists() else ""):
        print("Cảnh báo: chưa chấm G1 (`pc gold score`). Capsule dựng lúc này là bản nháp.", file=sys.stderr)
    _, _, evs, n_ex = select(cfg)
    model = cfg.model("inducer")["model"]
    pricing = cfg.raw.get("pricing", {})
    # bước 1: ~4.000 token vào, ~600 ra mỗi event; bước 2: ~1.200 vào, ~150 ra mỗi ứng viên.
    cost = estimate_cost(len(evs) * 5200, len(evs) * 750, model, pricing)
    print(f"Event train dùng được: {len(evs)} (loại theo exclude.txt: {n_ex})")
    print(f"inducer ({model}): ~${cost:.2f} (ngưỡng xác nhận ${cfg.raw.get('cost_confirm_usd', 20)})")
    if args.estimate:
        return 0
    if args.import_answers:
        print(f"Đã nạp {LLM(cfg.path('cache')).import_answers(Path(args.import_answers))} câu trả lời vào cache.")
    if not has_credentials(model):
        print(f"Thiếu API key cho vai inducer ({model}). Đổi model trong config.yaml hoặc đặt key.", file=sys.stderr)
        return 2
    if cost > cfg.raw.get("cost_confirm_usd", 20) and not args.yes:
        print("Ước lượng vượt ngưỡng (D4). Chạy lại với --yes sau khi bạn xác nhận.", file=sys.stderr)
        return 2
    res = run(cfg, workers=args.workers)
    out = cfg.path("reports") / "step2_induce.md"
    if res.n_pending or res.errors:
        out.write_text(render_report(cfg, res, None), encoding="utf-8")
        print(f"Dừng trước bước hợp nhất: {res.n_pending} yêu cầu chờ, {len(res.errors)} lỗi. Báo cáo -> {out}")
        return 1
    old = write_capsule(cfg, res)
    out.write_text(render_report(cfg, res, old), encoding="utf-8")
    from collections import Counter
    print(f"{len(res.cases)} case, {len(res.rules)} quy tắc {dict(Counter(r['status'] for r in res.rules))}")
    print(f"Capsule -> {cfg.path('capsule')}. Báo cáo -> {out}")
    print(f"Chi phí API lần này: ~${res.usage.cost(pricing):.3f} ({res.usage.calls} lệnh gọi mới)")
    print("Dừng. Chờ bạn xem capsule/SKILL.md, ledger.md, open_questions.md.")
    return 0


def cmd_pack(args) -> int:
    import subprocess

    cfg = load_config()
    base = cfg.root / cfg.raw.get("pack", {}).get("out_dir", "skills") / "colleague"
    if args.action == "build":
        from .pack.build import build_all
        res = build_all(cfg, args.domain or None)
        (cfg.path("reports") / "step5_packs.json").write_text(json.dumps(res, ensure_ascii=False, indent=1),
                                                               encoding="utf-8")
        print(f"{len(res)} bộ -> {base}")
        return 0
    packs = {}
    for d in sorted(base.glob("*")) if base.exists() else []:
        m = json.loads((d / "meta.json").read_text(encoding="utf-8")) if (d / "meta.json").exists() else {}
        dom = ((m.get("classification") or {}).get("tags") or [None, None])[-1]
        packs[dom] = d
    if not packs:
        print("Chưa có bộ nào. Chạy `pc pack build`.", file=sys.stderr)
        return 2
    if args.action == "test":
        from .pack.minitest import run
        md = run(cfg, packs, args.n)
        out = cfg.path("reports") / "step5_minitest.md"
        out.write_text(md, encoding="utf-8")
        print(md.split("## Chi tiết")[0])
        return 0
    # install: dùng installer của distilly, chỉ ghi SKILL.md tự chứa vào thư mục skills của host
    tool = cfg.root / "vendor" / "distilly" / "tools" / "install_generated_skill.py"
    for dom, d in packs.items():
        if args.domain and dom not in args.domain:
            continue
        cmd = [sys.executable, str(tool), "--skill-dir", str(d), "--host", args.host, "--force"]
        if args.skills_dir:
            cmd += ["--skills-dir", args.skills_dir]
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8")
        print(f"{d.name}: {'ok' if r.returncode == 0 else 'LỖI'} {(r.stdout or r.stderr).strip()[-300:]}")
    return 0


def cmd_stub(args) -> int:
    print(NOT_YET)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="pc", description="Persona Capsule")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("ingest", help="B1: đọc export, in reports/step0_data.md")
    s.add_argument("path", nargs="?", help="file .json/.zip hoặc thư mục (mặc định data/raw)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("inspect", help="Soi cấu trúc export thật, không in nội dung")
    s.add_argument("path")
    s.set_defaults(fn=cmd_inspect)

    s = sub.add_parser("mine", help="B2-B5; --estimate chỉ in ước lượng chi phí")
    s.add_argument("--estimate", action="store_true")
    s.add_argument("--pilot", type=int, help="chạy thử trên N phiên (ghi vào data/interim/pilot)")
    s.add_argument("--skip-verify", action="store_true")
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--import-answers", help="jsonl {key, text} do subagent verifier viết")
    s.add_argument("--yes", action="store_true", help="đã xác nhận chi phí vượt ngưỡng")
    s.set_defaults(fn=cmd_mine)

    s = sub.add_parser("gold", help="B6: sample | review (bạn gán tay) | score; export/import cho annotator proxy")
    s.add_argument("action", choices=["sample", "review", "score", "export", "import"])
    s.add_argument("--annotator", default="owner", help="tên người/model gán (mặc định owner = bạn)")
    s.add_argument("--file", help="jsonl để import")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_gold)

    s = sub.add_parser("induce", help="B7 bước 1-2: bài học + hợp nhất bằng delta -> capsule/")
    s.add_argument("--estimate", action="store_true")
    s.add_argument("--align", action="store_true", help="bước 3 (cần Module 2, chưa làm)")
    s.add_argument("--workers", type=int, default=8)
    s.add_argument("--import-answers", help="jsonl {key, text} nếu inducer là agent/...")
    s.add_argument("--yes", action="store_true", help="đã xác nhận chi phí vượt ngưỡng")
    s.set_defaults(fn=cmd_induce)

    s = sub.add_parser("pack", help="Đóng gói bộ AI chuyên gia theo distilly: build | test | install")
    s.add_argument("action", choices=["build", "test", "install"])
    s.add_argument("--domain", nargs="*", help="chỉ các domain này (mặc định: mọi domain đủ dữ liệu + all)")
    s.add_argument("--n", type=int, default=8, help="số item cho test (5-10)")
    s.add_argument("--host", default="claude-code", help="install: host của distilly (claude-code, codex, ...)")
    s.add_argument("--skills-dir", help="install: thư mục skills (mặc định của host)")
    s.set_defaults(fn=cmd_pack)

    s = sub.add_parser("eval", help="Module 2 (chưa làm)")
    s.add_argument("action", choices=["build", "run", "report"])
    s.add_argument("--system")
    s.add_argument("--split", choices=["dev", "test"])
    s.set_defaults(fn=cmd_stub)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
