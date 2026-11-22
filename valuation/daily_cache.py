"""按北京时间复用成功取得的数据，同一数据源的并发查询共享一次获取。"""
from collections import defaultdict
from datetime import datetime
import json
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from zoneinfo import ZoneInfo

CACHE_DIR = Path(__file__).resolve().parent / ".cache" / "daily"
_locks = defaultdict(Lock)
_guard = Lock()


def today():
    return datetime.now(ZoneInfo("Asia/Shanghai")).date()


def cached(key, fetch=None, *, valid_through=None):
    # key components are internal identifiers or validated market symbols.
    path = CACHE_DIR / ("-".join(key) + ".json")
    with _guard:
        lock = _locks[path]
    with lock:
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, ValueError):
            record = {}
        day = today().isoformat()
        fresh = record.get("date") == day
        if valid_through:
            block = record.get("data") or {}
            fresh = (block.get("confirmed_through", "") >= valid_through or
                     (fresh and block.get("through", "") >= valid_through))
        if fetch is None or fresh:
            return record.get("data")
        data = fetch(record.get("data"))
        path.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile("w", dir=path.parent, encoding="utf-8", delete=False) as file:
            json.dump({"date": day, "data": data}, file, ensure_ascii=False, separators=(",", ":"))
        Path(file.name).replace(path)
        return data
