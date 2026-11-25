#!/usr/bin/env python3
"""Đóng gói skill Expert Capsule thành một file zip tự chạy được.

    python scripts/build_skill_zip.py [thư mục ra]      # mặc định dist/

Ra `expert-capsule-skill.zip`, trong đó là thư mục `expert-capsule/` (tên khớp `name` trong SKILL.md):
SKILL.md, references/, agents/, scripts/capsule.py, mã nguồn src/capsule và src/pc, LICENSE.
Dùng cho Claude.ai (Settings > Capabilities > Skills > Upload skill) và agent khác đọc Agent Skills (giải nén vào
thư mục skills của nó). Không có test, ví dụ, vendor/ (chỉ chế độ Deep dùng) hay dữ liệu nào.
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "expert-capsule"
INCLUDE = ["SKILL.md", "LICENSE", "config.local.example.yaml", "references", "agents", "scripts/capsule.py",
           "src/capsule", "src/pc"]
SKIP_PARTS = {"__pycache__", ".pytest_cache"}
SKIP_SUFFIX = {".pyc", ".pyo"}


def files() -> list[Path]:
    out = []
    for item in INCLUDE:
        p = ROOT / item
        if not p.exists():
            raise FileNotFoundError(p)
        for f in sorted(p.rglob("*")) if p.is_dir() else [p]:
            rel = f.relative_to(ROOT)
            if f.is_file() and not SKIP_PARTS & set(rel.parts) and f.suffix not in SKIP_SUFFIX \
                    and not any(x.endswith(".egg-info") for x in rel.parts):
                out.append(f)
    return out


def build(out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    z = out_dir / f"{NAME}-skill.zip"
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in files():
            zf.write(f, f"{NAME}/{f.relative_to(ROOT).as_posix()}")
    return z


if __name__ == "__main__":
    z = build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist")
    with zipfile.ZipFile(z) as zf:
        n = len(zf.namelist())
    print(f"{z} ({n} file, {z.stat().st_size // 1024} KB)")
