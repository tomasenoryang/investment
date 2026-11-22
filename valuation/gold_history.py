"""生成国内与国际黄金价格快照。"""
import csv
import json
from datetime import date
from functools import lru_cache
from pathlib import Path

from history_sources import fetch_text, refresh_history, saved_history
from index_history import range_start
from stock_pe import make_chart

MARKETS = {
    "domestic": ("国内金价 · Au99.99", "元/克", "上海黄金交易所日收盘价"),
    "international": ("国际金价 · XAU/USD", "美元/金衡盎司", "Crystal Ball Markets 日参考价"),
}
HISTORY = Path(__file__).resolve().parent / "gold-history"


@lru_cache(maxsize=len(MARKETS))
def load_gold_history(market):
    with (HISTORY / f"{market}.csv").open(encoding="utf-8", newline="") as file:
        return [(date.fromisoformat(day), float(value)) for day, value in csv.reader(file)]


def fetch_gold_rows(market):
    if market == "domestic":
        payload = fetch_text("https://www.sge.com.cn/graph/Dailyhq", data=b"instid=Au99.99",
                             headers={
                                 "Content-Type": "application/x-www-form-urlencoded",
                                 "Referer": "https://www.sge.com.cn/sjzx/mrhq",
                                 "Origin": "https://www.sge.com.cn",
                                 "X-Requested-With": "XMLHttpRequest",
                             })
        return [(day, close) for day, _, close, _, _ in json.loads(payload)["time"]]
    payload = fetch_text("https://crystalballmarkets.com/markets/data/xauusd-since-1999.csv")
    return [(row["Date"], row["Rate"]) for row in csv.DictReader(payload.splitlines())]


def gold_chart(market, period, *, sync=False):
    title, unit, source = MARKETS[market]
    snapshot = load_gold_history(market)
    if sync:
        history, status = refresh_history(("gold", market), snapshot, lambda: fetch_gold_rows(market))
    else:
        history, status = saved_history(("gold", market), snapshot)
    full_history = history
    if period != "all":
        cutoff = range_start(history[-1][0], period)
        history = [(day, value) for day, value in history if day >= cutoff]
    return make_chart(title, history, source=f"{source} · {status}", price_unit=unit,
                      drawdowns=[("金价", full_history, history)])
