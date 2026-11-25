"""Cấu hình theo lớp, đường dẫn tương đối tính theo thư mục làm việc.

Thứ tự gộp (lớp sau đè lớp trước):
1. `config.default.yaml` nằm trong package (mặc định chung).
2. `config.yaml` trong thư mục làm việc, nếu có (hoặc file chỉ định bằng biến môi trường PC_CONFIG).
3. `config.local.yaml` trong thư mục làm việc: cấu hình riêng (tên, model, lĩnh vực tuỳ chỉnh), không đưa lên git.

Thư mục làm việc là thư mục hiện tại (`capsule -C <thư mục>` để đổi), hoặc thư mục chứa file PC_CONFIG.
Mỗi vai trong `models` được thay nguyên cụm, không gộp từng khoá, để khoá cache không dính tham số của lớp dưới.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG = Path(__file__).with_name("config.default.yaml")


@dataclass
class Config:
    root: Path
    raw: dict[str, Any]

    def path(self, key: str) -> Path:
        p = Path(self.raw["paths"][key])
        return p if p.is_absolute() else self.root / p

    def model(self, role: str) -> dict[str, Any]:
        return dict(self.raw["models"][role])

    @property
    def ingest(self) -> dict[str, Any]:
        return self.raw.get("ingest", {})


def find_config(start: Path | None = None) -> Path | None:
    """File config.yaml của thư mục làm việc (hoặc PC_CONFIG). Không có thì None: chỉ dùng mặc định trong package."""
    env = os.environ.get("PC_CONFIG")
    if env:
        return Path(env)
    p = (start or Path.cwd()).resolve() / "config.yaml"
    return p if p.exists() else None


def deep_merge(base: dict, over: dict) -> dict:
    """Gộp đè từng khoá lồng nhau; list và giá trị thường thì thay hẳn."""
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def _read(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        d = yaml.safe_load(f) or {}
    if not isinstance(d, dict):
        raise ValueError(f"{path}: cần một bảng YAML (khoá: giá trị) ở mức ngoài cùng")
    return d


def _layer(raw: dict, over: dict) -> dict:
    out = deep_merge(raw, over)
    for role, v in (over.get("models") or {}).items():  # mỗi vai thay nguyên cụm (khoá cache theo cả cụm)
        out["models"][role] = v
    return out


def load_config(path: Path | None = None, root: Path | None = None) -> Config:
    """Mặc định trong package, rồi config.yaml (nếu có), rồi config.local.yaml của thư mục làm việc."""
    path = Path(path) if path else find_config(root)
    if path is not None and not path.exists():
        raise FileNotFoundError(f"Không thấy {path}")
    base = (path.parent if path else (root or Path.cwd())).resolve()
    raw = _read(DEFAULT_CONFIG)
    for f in ([path] if path else []) + [base / "config.local.yaml"]:
        if f.exists():
            raw = _layer(raw, _read(f))
    return Config(root=base, raw=raw)
