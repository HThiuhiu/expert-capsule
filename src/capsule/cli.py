"""CLI `capsule` (spec v1.0 mục 6). Chế độ Lite. Deep dùng pipeline cũ `pc`.

  capsule init [thư mục] --owner "Tên"   Tạo thư mục làm việc (config.local.yaml, data/raw/)
  capsule status                          Đang ở bước nào, lệnh kế tiếp là gì
  capsule ingest [export]                 Bước 1
  capsule domains                         Bước 2, in danh sách lĩnh vực để chọn
  capsule build --domains a,b             Bước 3 đến 6
  capsule review                          Bước 7
  capsule package [--target ...]          Bước 8
  capsule correct "<lời sửa>" --domain a  Bước 9, ghi một bản ghi sửa
  capsule queue status|bundle|import      Hàng đợi subagent khi vai LLM là `agent/...`

Mọi lệnh chạy trong thư mục làm việc hiện tại, hoặc `capsule -C <thư mục> <lệnh>`.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .common import LLMUnavailable, NeedAgents, load_config, make_llm


def _cfg(args):
    """Đọc config của thư mục làm việc (-C); `--slug` chọn capsule (expert/expert-<slug>/, data/lite/<slug>/)."""
    ws = getattr(args, "workspace", None)
    cfg = load_config(root=Path(ws) if ws else None)
    if getattr(args, "slug", None):
        cfg.raw.setdefault("capsule", {})["slug"] = args.slug
    return cfg


def _sessions(cfg):
    from pc.ingest import read_sessions
    p = cfg.path("interim") / "sessions.jsonl"
    if not p.exists():
        print("Chưa có sessions.jsonl. Chạy `capsule ingest` trước.", file=sys.stderr)
        raise SystemExit(2)
    return read_sessions(p)


def _need(e: NeedAgents) -> int:
    print(f"\nDừng ở {e.step}: {e.n} yêu cầu chờ subagent (vai LLM là `agent/...`).")
    print("Làm tiếp: `capsule queue bundle` -> subagent trả lời từng gói -> `capsule queue import` -> chạy lại lệnh này.")
    return 3


def cmd_ingest(args) -> int:
    from pc.cli import run_ingest
    cfg = _cfg(args)
    r = run_ingest(cfg, args.path)
    if r is None:
        return 2
    res, out, rep = r
    print(f"{len(res.sessions)} phiên -> {out}")
    print(f"Báo cáo dữ liệu -> {rep}")
    if not res.sessions:
        print("Không đọc được phiên nào. Xem báo cáo, và data/README.md để biết cần đặt file nào.", file=sys.stderr)
        return 2
    gate = cfg.ingest.get("gate_min_sessions", 50)
    if len(res.sessions) < gate:
        print(f"Lưu ý: dưới {gate} phiên, sẽ có ít luật đủ bằng chứng. Vẫn chạy tiếp được.")
    print("Tiếp: capsule domains")
    return 0


def cmd_domains(args) -> int:
    from . import domains
    cfg = _cfg(args)
    try:
        domains.run(cfg, make_llm(cfg), _sessions(cfg), force=args.force)
    except NeedAgents as e:
        return _need(e)
    d = domains.load(cfg)  # kèm lĩnh vực tuỳ chỉnh
    print(domains.table(d))
    print()
    print(domains.summary(d))
    return 0


def cmd_build(args) -> int:
    from . import build
    cfg = _cfg(args)
    sel = [x.strip() for x in (args.domains or "").split(",") if x.strip()]
    try:
        rep = build.run(cfg, make_llm(cfg), _sessions(cfg), sel, deep=args.deep, turns=args.turns)
    except NeedAgents as e:
        return _need(e)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    print(rep)
    return 0


def cmd_review(args) -> int:
    from . import review
    cfg = _cfg(args)
    if args.list:
        print(review.listing(cfg))
        return 0
    if args.show is not None:
        print(review.show(cfg, args.show, all_=args.all))
        return 0
    fields = {f: getattr(args, f) for f in review.EDITABLE if getattr(args, f)}
    if fields and not args.edit:
        print("--when/--do/--because/--scope/--exceptions chỉ dùng kèm --edit <mã>.", file=sys.stderr)
        return 2
    if args.keep or args.delete or args.edit or args.answer or args.keep_rest:
        try:
            print(review.decide(cfg, keep=args.keep or [], delete=args.delete or [],
                                edits={args.edit: fields} if args.edit else None,
                                answers=dict(args.answer or []), keep_rest=args.keep_rest))
        except ValueError as e:
            print(str(e), file=sys.stderr)
            return 2
        return 0
    if not sys.stdin.isatty():
        print("`capsule review` cần terminal tương tác. Không tương tác: `capsule review --show` để xem, rồi "
              "--keep/--delete/--edit/--answer để ghi quyết định.", file=sys.stderr)
        return 2
    return review.interactive(cfg, only_pending=not args.all)


def cmd_package(args) -> int:
    from .package import package
    cfg = _cfg(args)
    out = package(cfg, targets=[t for t in (args.target or "").split(",") if t] or None)
    print(out)
    return 0


def cmd_correct(args) -> int:
    from . import evolve
    cfg = _cfg(args)
    n = evolve.correct(cfg, args.text, args.domain, situation=args.situation or "", wrong=args.wrong or "")
    print(f"Đã ghi. {n} bản ghi sửa chưa áp dụng (từ 5 bản ghi thì chạy `capsule update`).")
    return 0


def cmd_update(args) -> int:
    print("Bước 9 (học dần, `capsule update`) thuộc giai đoạn 3 của lộ trình. Chưa làm.")
    return 0


def cmd_install(args) -> int:
    from . import install
    cfg = _cfg(args)
    try:
        if args.target == "zip":
            z = install.make_zip(cfg)
            print(f"{z}\nTải file này lên Claude.ai: Settings > Capabilities > Skills > Upload skill.")
        else:
            t = install.install_dir(cfg, Path(args.dir) if args.dir else None, force=args.force)
            print(f"Đã cài vào {t}\nMở phiên Claude Code mới; Claude tự dùng skill khi câu hỏi khớp mô tả, "
                  f"hoặc gõ /{t.name}.")
    except (FileNotFoundError, FileExistsError) as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def cmd_demo(args) -> int:
    from . import install
    cfg = _cfg(args)
    try:
        if args.reveal is not None:
            print(install.reveal(cfg, args.reveal))
            return 0
        if not args.questions:
            print("Cần ít nhất một câu hỏi: capsule demo [--blind] \"<câu hỏi>\" ...", file=sys.stderr)
            return 2
        print(install.demo(cfg, make_llm(cfg), args.questions, blind=args.blind))
    except NeedAgents as e:
        return _need(e)
    except (FileNotFoundError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def cmd_queue(args) -> int:
    from . import agentq
    cfg = _cfg(args)
    if args.action == "status":
        st = agentq.status(cfg)
        print(f"{sum(st.values())} yêu cầu chờ: {dict(st)}")
        return 0
    if args.action == "bundle":
        ps = agentq.make_bundles(cfg, max_chars=args.max_chars, tags=args.tag or None)
        for b in agentq.bundle_index(cfg):
            print(f"{b['bundle']}\tmodel={b['model']}\tn={b['n']}")
        print(f"{len(ps)} gói. Mỗi gói: một subagent (model ghi ở cột model=) đọc file .md và ghi file "
              f".answers.jsonl nêu trong đầu gói. Xong hết thì: capsule queue import")
        return 0
    files = [Path(f) for f in args.files] or None
    ok, bad, done = agentq.import_answers(cfg, files)
    print(f"Nạp {ok} đáp án, {bad} dòng hỏng, từ {len(done)} file. Còn chờ: {sum(agentq.status(cfg).values())}")
    return 0


def cmd_init(args) -> int:
    from . import workspace
    path = Path(args.path or args.workspace or ".")
    try:
        print(workspace.init(path, args.owner, args.init_slug, args.mode, force=args.force))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2
    return 0


def cmd_status(args) -> int:
    from . import workspace
    text, nxt = workspace.status(_cfg(args))
    print(text)
    if nxt:
        print(f"\nTiếp: {nxt}")
    return 0


class _Version(argparse.Action):
    """In phiên bản kèm thư mục mã (biết đang chạy bản plugin, zip hay repo). Không ngắt dòng như action mặc định."""

    def __init__(self, option_strings, dest=argparse.SUPPRESS, default=argparse.SUPPRESS, help=None):
        super().__init__(option_strings, dest=dest, default=default, nargs=0, help=help)

    def __call__(self, parser, namespace, values, option_string=None):
        print(f"expert-capsule {__version__} ({Path(__file__).resolve().parent})")
        parser.exit()


def main(argv: list[str] | None = None) -> int:
    from .workspace import MODELS, save_pending_command, strip_global
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="capsule", description="Expert Capsule: chưng cất lịch sử chat thành Agent Skill "
                                "mang tiêu chuẩn và văn phong của bạn (chế độ Lite)")
    p.add_argument("--version", action=_Version, help="in phiên bản và thư mục mã đang chạy")
    p.add_argument("-C", "--workspace", metavar="THƯ_MỤC",
                   help="thư mục làm việc chứa dữ liệu và config.local.yaml (mặc định: thư mục hiện tại)")
    p.add_argument("--slug", help="capsule nào (mặc định capsule.slug trong config). Mỗi slug có dữ liệu và thư mục ra riêng")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="Tạo thư mục làm việc: config.local.yaml, data/raw/, .gitignore")
    s.add_argument("path", nargs="?", help="thư mục (mặc định: -C hoặc thư mục hiện tại)")
    s.add_argument("--owner", help="tên hiển thị trong capsule: \"Cách làm việc của <tên>\"")
    s.add_argument("--slug", dest="init_slug", help="tên ngắn không dấu (mặc định: lấy từ --owner)")
    s.add_argument("--mode", choices=list(MODELS), default="anthropic",
                   help="cách chạy model: agent (subagent Claude Code, không cần key), anthropic, haiku, openai, ollama")
    s.add_argument("--force", action="store_true", help="ghi lại config.local.yaml đã có")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("status", help="Đang ở bước nào và lệnh kế tiếp")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("ingest", help="Bước 1: đọc export ChatGPT/Claude/văn bản dán Gemini")
    s.add_argument("path", nargs="?", help="file .json/.zip/.txt hoặc thư mục (mặc định data/raw)")
    s.set_defaults(fn=cmd_ingest)

    s = sub.add_parser("domains", help="Bước 2: gán lĩnh vực, in danh sách để chọn")
    s.add_argument("--force", action="store_true", help="gán lại từ đầu")
    s.set_defaults(fn=cmd_domains)

    s = sub.add_parser("build", help="Bước 3 đến 6")
    s.add_argument("--domains", help="slug lĩnh vực, cách nhau bằng dấu phẩy (xem `capsule domains`)")
    s.add_argument("--turns", type=int, help="số lượt chọn ở Bước 3 (mặc định config, 200 đến 400)")
    s.add_argument("--deep", action="store_true", help="chế độ Deep (dùng pipeline `pc`)")
    s.set_defaults(fn=cmd_build)

    s = sub.add_parser("review", help="Bước 7: duyệt từng luật")
    s.add_argument("--list", action="store_true", help="chỉ in danh sách luật và trạng thái duyệt")
    s.add_argument("--all", action="store_true", help="duyệt lại (hoặc --show) cả luật đã duyệt")
    s.add_argument("--show", nargs="*", metavar="MÃ",
                   help="không tương tác: in chi tiết luật chưa duyệt (hoặc các mã chỉ định) kèm bằng chứng, "
                        "và câu hỏi mâu thuẫn (M1, M2...)")
    s.add_argument("--keep", nargs="+", metavar="MÃ", help="giữ các luật này")
    s.add_argument("--keep-rest", action="store_true", help="giữ mọi luật còn lại chưa duyệt")
    s.add_argument("--delete", nargs="+", metavar="MÃ", help="xoá các luật này (không học lại từ cùng bằng chứng)")
    s.add_argument("--edit", metavar="MÃ", help="sửa một luật, kèm một hoặc vài trường dưới đây")
    s.add_argument("--when", help="--edit: vế Khi")
    s.add_argument("--do", help="--edit: vế Làm")
    s.add_argument("--because", help="--edit: vế Vì")
    s.add_argument("--scope", help="--edit: phạm vi áp dụng")
    s.add_argument("--exceptions", help="--edit: ngoại lệ")
    s.add_argument("--answer", nargs=2, action="append", metavar=("Mx", "TRẢ_LỜI"),
                   help="trả lời câu hỏi mâu thuẫn Mx (lặp lại được)")
    s.set_defaults(fn=cmd_review)

    s = sub.add_parser("package", help="Bước 8: sinh SKILL.md, file lĩnh vực, exports/")
    s.add_argument("--target", help="skill,project,custom,system (mặc định: tất cả)")
    s.set_defaults(fn=cmd_package)

    s = sub.add_parser("correct", help="Bước 9: ghi một bản ghi sửa vào private/corrections.jsonl")
    s.add_argument("text", help="lời sửa (cách đúng)")
    s.add_argument("--domain", required=True)
    s.add_argument("--situation")
    s.add_argument("--wrong")
    s.set_defaults(fn=cmd_correct)

    s = sub.add_parser("update", help="Bước 9: cập nhật từ bản ghi sửa (giai đoạn 3)")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("install", help="Đưa capsule vào AI: zip (Claude.ai) | claude-code (thư mục skills)")
    s.add_argument("--target", choices=["zip", "claude-code"], default="zip")
    s.add_argument("--dir", help="claude-code: thư mục skills (mặc định $CLAUDE_CONFIG_DIR/skills hoặc ~/.claude/skills)")
    s.add_argument("--force", action="store_true", help="ghi đè thư mục không do lệnh này cài")
    s.set_defaults(fn=cmd_install)

    s = sub.add_parser("demo", help="Hỏi cùng câu cho AI có và không có capsule")
    s.add_argument("questions", nargs="*", help="câu hỏi thật của bạn")
    s.add_argument("--blind", action="store_true", help="thử mù: hai câu trả lời A/B thứ tự ngẫu nhiên, không ghi nhãn")
    s.add_argument("--reveal", nargs="*", metavar="A|B",
                   help="mở khoá thử mù; kèm lựa chọn của bạn cho từng câu (vd: --reveal A B A) để chấm điểm")
    s.set_defaults(fn=cmd_demo)

    s = sub.add_parser("queue", help="Hàng đợi subagent: status | bundle | import")
    s.add_argument("action", choices=["status", "bundle", "import"])
    s.add_argument("files", nargs="*", help="import: file .answers.jsonl (mặc định: mọi file trong .cache/agent_bundles)")
    s.add_argument("--tag", nargs="*", help="bundle: chỉ các tag này")
    s.add_argument("--max-chars", type=int, default=90_000)
    s.set_defaults(fn=cmd_queue)

    args = p.parse_args(argv)
    if args.workspace and args.cmd != "init" and not Path(args.workspace).is_dir():
        print(f"Không thấy thư mục làm việc {args.workspace}. Tạo bằng: capsule init {args.workspace}", file=sys.stderr)
        return 2
    try:
        rc = args.fn(args)
    except LLMUnavailable as e:
        print(f"\n{e}", file=sys.stderr)
        return 1
    if rc == 3:  # dừng chờ subagent: nhớ lệnh để `capsule status` nhắc chạy lại sau khi nạp đáp án
        save_pending_command(_cfg(args), strip_global(argv))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
