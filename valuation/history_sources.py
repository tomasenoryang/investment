"""按请求检查公开历史数据，按日保留最后一次成功取得的样本。"""
from daily_cache import cached, today
from urllib.request import Request, urlopen

from stock_pe import normalize_history

def fetch_text(url, *, data=None, headers=None, encoding="utf-8-sig"):
    request = Request(url, data=data, headers={
        "User-Agent": "Mozilla/5.0", **(headers or {}),
    })
    with urlopen(request, timeout=8) as response:
        return response.read().decode(encoding)


def saved_history(key, snapshot):
    saved = cached(key)
    return (normalize_history(saved), "已同步历史") if saved else (snapshot, "本地历史快照")


def refresh_history(key, snapshot, fetch_rows):
    def update(saved):
        current = dict(normalize_history(saved) if saved else snapshot)
        day = today()
        if not current or max(current) < day:
            incoming = dict(normalize_history(fetch_rows()))
            if (sum(value is not None for value in incoming.values()) < 2
                    or max(incoming) > day):
                raise ValueError("数据源未返回有效历史")
            if current and max(incoming) < max(current):
                raise ValueError("数据源日期早于已保存历史")
            current.update(incoming)
        return [(day.isoformat(), value) for day, value in sorted(current.items())]

    try:
        return normalize_history(cached(key, update)), "已同步历史"
    except Exception:
        history, _ = saved_history(key, snapshot)
        return history, "数据未能更新 · 使用已保存历史"
