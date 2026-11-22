"""可选的本地品种资料。公开发行版不附带个人配置。"""
import json
from pathlib import Path

LOCAL = Path(__file__).resolve().parent / ".local"
try:
    config = json.loads((LOCAL / "instruments.json").read_text(encoding="utf-8"))
except FileNotFoundError:
    config = {}
FUNDS = config.get("funds", {})
EXTRA_INDICES = config.get("indices", {})
