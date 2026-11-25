"""Thư mục làm việc: `capsule init` tạo, `capsule status` cho biết đang ở bước nào và lệnh kế tiếp.

Thư mục làm việc chứa mọi dữ liệu riêng của một người: export, phiên đã chuẩn hoá, cache LLM, capsule sinh ra.
Nó tách khỏi mã nguồn, nên skill/plugin cài ở đâu cũng được, cập nhật không làm mất dữ liệu.
"""
from __future__ import annotations

import json
import shlex
from pathlib import Path

from .common import capsule_dir, read_json, settings, slugify, work_dir

MODELS = {
    "agent": ("# Không cần API key: Claude Code (hoặc agent khác có subagent) trả lời qua hàng đợi.\n"
              "# Tên sau agent/claude- là model gợi ý cho subagent: haiku rẻ, sonnet tổng hợp luật tốt hơn.\n"
              "models:\n"
              "  cheap:  {model: \"agent/claude-haiku\"}\n"
              "  strong: {model: \"agent/claude-sonnet\"}\n"
              "  judge:  {model: \"agent/claude-haiku\"}\n"),
    "anthropic": ("# API Anthropic: đặt ANTHROPIC_API_KEY. Dùng model mặc định (Haiku cho Bước 2, 4; Opus cho Bước 5, 6).\n"
                  "# Rẻ hơn: `capsule init --mode haiku`.\n"),
    "haiku": ("# API Anthropic, mọi vai là Haiku (rẻ nhất). Đặt ANTHROPIC_API_KEY.\n"
              "models:\n"
              "  cheap:  {model: \"anthropic/claude-haiku-5-5\", effort: low}\n"
              "  strong: {model: \"anthropic/claude-haiku-5-5\", effort: medium}\n"
              "  judge:  {model: \"anthropic/claude-haiku-5-5\", effort: medium}\n"),
    "openai": ("# API OpenAI: đặt OPENAI_API_KEY (tạo ở platform.openai.com, tính tiền riêng với gói ChatGPT).\n"
               "# Đổi tên model theo những model tài khoản bạn có.\n"
               "models:\n"
               "  cheap:  {model: \"openai/gpt-5-mini\", effort: low}\n"
               "  strong: {model: \"openai/gpt-5\", effort: medium}\n"
               "  judge:  {model: \"openai/gpt-5\", effort: medium}\n"),
    "ollama": ("# Chạy hết trên máy bằng Ollama: không gửi gì lên API. Trước đó: `ollama pull qwen3:14b`.\n"
               "# Chất lượng luật phụ thuộc model bạn chọn (model càng lớn càng tốt).\n"
               "models:\n"
               "  cheap:  {model: \"ollama/qwen3:14b\"}\n"
               "  strong: {model: \"ollama/qwen3:14b\"}\n"
               "  judge:  {model: \"ollama/qwen3:14b\"}\n"),
}

TEMPLATE = """# Cấu hình riêng của thư mục làm việc này (do `capsule init` tạo). Gộp đè lên mặc định trong package.
# Thư mục này chứa dữ liệu chat riêng của bạn: không đưa lên git, không chia sẻ.

capsule:
  owner_name: {owner}   # hiện trong SKILL.md: "Cách làm việc của <tên>"
  slug: {slug}          # capsule ra ở expert/expert-{slug}/
  # turns: 300          # số lượt đưa vào khai thác ở Bước 3 (200 đến 400)
  # quickcheck_n: 15    # Bước 6; đặt 0 để bỏ qua khi không có subagent riêng để chấm mù

{models}
# Lĩnh vực tuỳ chỉnh: cắt phiên theo kiểu việc thay vì theo ngành. Ví dụ (bỏ dấu # để dùng):
# capsule:
#   custom_domains:
#     nghien-cuu:
#       name: "Phong cách nghiên cứu"
#       match: any
#       raw_task: "review paper|plan project|find paper|literature|research"
"""

GITIGNORE = ("# Thư mục làm việc của Expert Capsule: dữ liệu chat riêng. Không đưa gì ở đây lên git.\n*\n")


def init(path: Path, owner: str | None, slug: str | None, mode: str, force: bool = False) -> str:
    if mode not in MODELS:
        raise ValueError(f"--mode phải là một trong: {', '.join(MODELS)}")
    owner = (owner or "").strip() or "Chủ capsule"
    slug = slugify(slug or owner) if (slug or owner != "Chủ capsule") else "me"
    if slug == "capsule":
        raise ValueError("slug `capsule` trùng tên skill Expert Capsule; chọn slug khác (--slug).")
    path = path.resolve()
    (path / "data" / "raw").mkdir(parents=True, exist_ok=True)
    L = [f"Thư mục làm việc: {path}"]
    cfg = path / "config.local.yaml"
    if cfg.exists() and not force:
        L.append(f"- Giữ nguyên {cfg.name} đã có (dùng --force để ghi lại).")
    else:
        cfg.write_text(TEMPLATE.format(owner=json.dumps(owner, ensure_ascii=False), slug=slug, models=MODELS[mode]),
                       encoding="utf-8")
        L.append(f"- Đã ghi {cfg.name}: tên `{owner}`, slug `{slug}`, cách chạy model `{mode}`.")
    gi = path / ".gitignore"
    if not gi.exists():
        gi.write_text(GITIGNORE, encoding="utf-8")
        L.append("- Đã ghi .gitignore chặn mọi file trong thư mục này khỏi git.")
    L += [f"- Đặt file export (zip ChatGPT/Claude, hoặc .txt) vào {path / 'data' / 'raw'},",
          "  hoặc chỉ thẳng đường dẫn: capsule ingest <file>.",
          "Tiếp: capsule ingest"]
    return "\n".join(L)


# ---------- trạng thái ----------

def last_file(cfg) -> Path:
    return cfg.path("cache").parent / "last_pending_command.json"


def save_pending_command(cfg, argv: list[str]) -> None:
    p = last_file(cfg)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"argv": argv}, ensure_ascii=False), encoding="utf-8")


def _cmd(argv: list[str]) -> str:
    return "capsule " + shlex.join(argv)


def _count_lines(p: Path) -> int:
    with open(p, encoding="utf-8") as f:
        return sum(1 for line in f if line.strip())


def _newer(a: Path, *bs: Path) -> bool:
    """a có mới hơn mọi file b đang tồn tại không."""
    return a.exists() and all(a.stat().st_mtime >= b.stat().st_mtime for b in bs if b.exists())


def status(cfg) -> tuple[str, str]:
    """(mô tả từng bước, lệnh kế tiếp). Đọc file trên đĩa, không gọi LLM."""
    from . import agentq, review
    from . import domains as dom_mod
    from .install import MARK, default_skills_dir

    st = settings(cfg)
    L = [f"Thư mục làm việc: {cfg.root}", f"Capsule: expert-{st['slug']} (chủ: {st['owner_name']})"]

    def done(step: str, text: str) -> None:
        L.append(f"[x] {step}: {text}")

    def todo(step: str, text: str, cmd: str) -> tuple[str, str]:
        L.append(f"[ ] {step}: {text}")
        return "\n".join(L), cmd

    # hàng đợi subagent: ưu tiên xử lý trước mọi bước
    pend = agentq.status(cfg)
    if pend:
        last = read_json(last_file(cfg), {}) or {}
        again = _cmd(last["argv"]) if last.get("argv") else "lệnh vừa dừng"
        L.append(f"[!] {sum(pend.values())} yêu cầu LLM chờ subagent ({', '.join(f'{k}: {v}' for k, v in pend.items())}).")
        L.append(f"    Làm: capsule queue bundle -> subagent trả lời từng gói -> capsule queue import -> {again}")
        return "\n".join(L), "capsule queue bundle"

    sess = cfg.path("interim") / "sessions.jsonl"
    if not sess.exists():
        raw = cfg.path("raw")
        has = raw.exists() and any(p.is_file() for p in raw.rglob("*"))
        return todo("1 ingest", "chưa đọc lịch sử chat" + (" (đã có file trong data/raw)" if has else ""),
                    "capsule ingest" if has else "capsule ingest <file export .zip/.json/.txt>")
    done("1 ingest", f"{_count_lines(sess)} phiên")

    d = dom_mod.load(cfg)
    if not d or not d.get("domains"):
        return todo("2 domains", "chưa gán lĩnh vực", "capsule domains")
    full = [g for g in d["domains"] if not g["thin"]]
    done("2 domains", f"{len(full)} lĩnh vực đủ dữ liệu: " + ", ".join(f"{g['slug']} ({g['n_sessions']})" for g in full))

    build = read_json(work_dir(cfg) / "build.json", {}) or {}
    synth_p = work_dir(cfg) / "synth.json"
    report_p = work_dir(cfg) / "build_report.md"
    if not build.get("domains"):
        pick = ",".join(g["slug"] for g in full[:3]) or "<slug>"
        return todo("3-6 build", "chưa chọn lĩnh vực (hỏi người dùng muốn chưng cất lĩnh vực nào)",
                    f"capsule build --domains {pick}")
    if not _newer(report_p, work_dir(cfg) / "build.json"):
        return todo("3-6 build", f"đang dở với {', '.join(build['domains'])}",
                    f"capsule build --domains {','.join(build['domains'])}")
    synth = read_json(synth_p, {}) or {}
    rules = review.all_rules(synth)
    done("3-6 build", f"{len(rules)} luật cho {', '.join(build['domains'])} (báo cáo: {report_p})")

    rv = review.load(cfg)
    n_rule = sum(1 for _, r in rules if not review.decision_for(rv, r))
    asked = {a["question"] for a in rv["answers"]}
    n_conf = sum(1 for _, _, cf in review.conflicts(synth) if cf["question"] not in asked)
    if n_rule or n_conf:
        return todo("7 review", f"{n_rule} luật chưa duyệt, {n_conf} câu hỏi mâu thuẫn chưa trả lời",
                    "capsule review --show")
    done("7 review", "đã duyệt hết")

    out = capsule_dir(cfg)
    meta = out / "capsule.json"
    if not _newer(meta, synth_p, work_dir(cfg) / "review.json"):
        return todo("8 package", "chưa đóng gói, hoặc có luật/duyệt mới hơn bản đã đóng gói", "capsule package")
    done("8 package", str(out))

    inst = default_skills_dir() / out.name / MARK
    z = out.parent / "dist" / f"{out.name}.zip"
    where = [w for w, ok in (("Claude Code", _newer(inst, meta)), ("zip Claude.ai", _newer(z, meta))) if ok]
    if not where:
        return todo("9 install", "chưa đưa vào AI nào (hoặc bản cài cũ hơn bản đóng gói)",
                    "capsule install --target claude-code   # hoặc --target zip; ChatGPT: xem exports/")
    done("9 install", ", ".join(where))
    L.append("Xong. Có thể thử: capsule demo --blind \"<câu hỏi thật của bạn>\"")
    return "\n".join(L), ""


def strip_global(argv: list[str]) -> list[str]:
    """Bỏ `-C <dir>` khỏi argv để in lại lệnh gọn."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("-C", "--workspace"):
            skip = True
            continue
        if a.startswith("--workspace="):
            continue
        out.append(a)
    return out

