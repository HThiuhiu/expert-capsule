"""Đọc config.yaml, giải đường dẫn tương đối theo thư mục chứa config."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


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


def find_config(start: Path | None = None) -> Path:
    env = os.environ.get("PC_CONFIG")
    if env:
        return Path(env)
    cur = (start or Path.cwd()).resolve()
    for d in [cur, *cur.parents]:
        if (d / "config.yaml").exists():
            return d / "config.yaml"
    raise FileNotFoundError("Không thấy config.yaml (đặt PC_CONFIG hoặc chạy trong thư mục dự án)")


def deep_merge(base: dict, over: dict) -> dict:
    """Gộp đè từng khoá lồng nhau; list và giá trị thường thì thay hẳn."""
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: Path | None = None) -> Config:
    """Đọc config.yaml, rồi gộp đè config.local.yaml cùng thư mục nếu có (cấu hình riêng, không đưa lên git)."""
    path = path or find_config()
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    local = path.with_name("config.local.yaml")
    if local.exists():
        with open(local, encoding="utf-8") as f:
            over = yaml.safe_load(f) or {}
        raw = deep_merge(raw, over)
        for role, v in (over.get("models") or {}).items():  # mỗi vai thay nguyên cụm (khoá cache theo cả cụm)
            raw["models"][role] = v
    return Config(root=path.parent.resolve(), raw=raw)
