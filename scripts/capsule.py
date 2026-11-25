#!/usr/bin/env python3
"""Chạy CLI `capsule` thẳng từ thư mục skill/plugin, không cần `pip install`.

    python scripts/capsule.py -C <thư mục làm việc> <lệnh> ...

Cần Python 3.11+ và PyYAML. Model `anthropic/...` cần thêm gói `anthropic`; chế độ `agent` thì không.
"""
import sys
from pathlib import Path

if sys.version_info < (3, 11):
    sys.exit(f"Expert Capsule cần Python 3.11 trở lên (đang chạy {sys.version.split()[0]}).")

for stream in (sys.stdout, sys.stderr):  # console Windows cũ không in được tiếng Việt: thay ký tự lỗi thay vì dừng
    try:
        stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    import yaml  # noqa: F401
except ImportError:
    sys.exit("Thiếu PyYAML. Cài: python -m pip install pyyaml")

from capsule.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
