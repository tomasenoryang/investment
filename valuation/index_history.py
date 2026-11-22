"""按日历区间读取本地指数滚动市盈率快照并生成估值曲线。"""
from calendar import monthrange
import csv
import json
import re
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from instrument_config import EXTRA_INDICES, LOCAL
from daily_cache import cached
from history_sources import fetch_text, refresh_history, saved_history
from stock_pe import make_chart, normalize_history

INDICES = {
    "000300": ("沪深300", date(2005, 4, 8)),
    "000688": ("科创50", date(2020, 7, 23)),
    "NDX": ("纳斯达克100指数", date(1985, 1, 31)),
    "HSTECH": ("恒生科技指数", date(2020, 7, 27)),
    "000852": ("中证1000", date(2014, 10, 17)),
}
INDICES.update({code: (item["name"], date.fromisoformat(item["launch"]))
                for code, item in EXTRA_INDICES.items()})
RANGES = ("1w", "1m", "1y", "3y", "5y", "10y", "all")
HISTORY = Path(__file__).resolve().parent / "index-history"


@lru_cache(maxsize=len(INDICES))
def load_index_history(code):
    directory = LOCAL / "index-history" if code in EXTRA_INDICES else HISTORY
    with (directory / f"{code}.csv").open(encoding="utf-8", newline="") as file:
        return [(date.fromisoformat(day), float(value)) for day, value in csv.reader(file)]


def range_start(end, period):
    if period == "1w":
        return end - timedelta(days=7)
    months = 1 if period == "1m" else 12 * int(period[:-1])
    year, month = divmod(end.year * 12 + end.month - 1 - months, 12)
    month += 1
    return date(year, month, min(end.day, monthrange(year, month)[1]))


def fetch_hk_pe(code):
    html = fetch_text(f"https://www.getstockcheck.com/en/index/{code}.HK/")
    match = re.search(r"window\.__SSG_CHART__\s*=\s*(\{.*?\});", html, re.DOTALL)
    if not match:
        raise ValueError("未找到指数历史")
    history = json.loads(match[1])["10Y"]
    return list(zip(history["dates"], history["pe"], strict=True))


def index_bundle(code, previous):
    data = json.loads(fetch_text(f"https://guzhi.suilang.net/i/{code}/data.json"))
    if data["code"] != code:
        raise ValueError("指数代码不匹配")
    bond = dict(data["bond"])
    pe = [(day, round(100 / (erp + bond[day]), 4)) for day, erp in data["erp"]
          if day in bond and erp + bond[day] > 0]
    bundle = {}
    for field, rows in [("pe", pe), ("price", data["price"])]:
        incoming = {d.isoformat(): v for d, v in normalize_history(rows) if v is not None}
        existing = dict((previous or {}).get(field, []))
        if len(incoming) < 2 or (existing and max(incoming) < max(existing)):
            raise ValueError("指数数据不足或日期回退")
        bundle[field] = sorted((existing | incoming).items())
    return bundle


HK_IDS = {"HSTECH": "02083.00", **{code: item["hk_id"] for code, item in EXTRA_INDICES.items() if "hk_id" in item}}


def hk_prices(code):
    index_id = HK_IDS[code]
    url = ("https://www.hsi.com.hk/api/wsit-hsi-ddoc-ea-public-website-proxy/v1/"
           "product-data/pub/indexes/metadata/v2?data=valueHistoryPub&language=en-hk&indexCodes=" + index_id)
    entry = next(item for item in json.loads(fetch_text(url))["data"] if item["indexCode"] == index_id)
    return [(r["date"], r["close"]) for r in entry["valueHistory"]]


def describe_index(history, prices):
    valid = [(day, value) for day, value in history if value is not None and value > 0]
    latest = valid[-1][1]
    percentile = 100 * sum(v <= latest for _, v in valid) / len(valid)
    summary = [f"区间估值分位 {percentile:.1f}% · {len(valid)} 条有效样本中，PE 不高于最新值 {latest:.2f} 倍的占比"]
    levels = dict(prices)
    aligned = [(d, pe, levels[d]) for d, pe in valid if levels.get(d)]
    if len(aligned) < 2:
        return summary + ["同日点位与 PE 样本不足，无法拆分变化。可选更长区间或手动刷新。"]
    start, pe0, p0 = aligned[0]
    end, pe1, p1 = aligned[-1]
    price, pe = p1/p0, pe1/pe0
    earnings = price/pe
    summary.append(f"{start} 至 {end} · 点位 {(price-1)*100:+.1f}% · 推算盈利 {(earnings-1)*100:+.1f}% · PE {(pe-1)*100:+.1f}%")
    if abs(pe-1) < .0005:
        reason = "区间两端估值基本持平"
    else:
        direction = "上升" if pe > 1 else "下降"
        factors = []
        if abs(price-1) >= .0005 and (price-1)*(pe-1) > 0:
            factors.append("点位上涨" if price > 1 else "点位下跌")
        if abs(earnings-1) >= .0005 and (earnings-1)*(pe-1) < 0:
            factors.append("推算盈利增加" if earnings > 1 else "推算盈利减少")
        reason = "和".join(factors) + "推动估值" + direction if factors else "估值小幅" + direction
    return summary + [reason + "。盈利按点位 ÷ PE 推算，成份调整也会影响结果。"]


def index_chart(code, period, *, sync=False):
    name, launch = INDICES[code]
    snapshot = load_index_history(code)
    history, status = saved_history(("index", code), snapshot)
    if code in HK_IDS:
        if sync:
            history, status = refresh_history(("index", code), snapshot, lambda: fetch_hk_pe(code))
            prices, price_status = refresh_history(("index-price", code), [], lambda: hk_prices(code))
            if "未能更新" in price_status:
                status += " · 点位数据未能更新"
        else:
            prices, _ = saved_history(("index-price", code), [])
    else:
        key = ("index-bundle", code)
        try:
            bundle = cached(key, (lambda previous: index_bundle(code, previous)) if sync else None)
        except Exception:
            bundle = cached(key)
            status = "数据未能更新 · 使用已保存历史"
        if bundle:
            history = sorted((dict(history) | dict(normalize_history(bundle["pe"]))).items())
            if "未能更新" not in status:
                status = "已同步历史"
        prices = normalize_history(bundle["price"]) if bundle else []
    cutoff = launch if period == "all" else max(launch, range_start(history[-1][0], period))
    history = [(d, v) for d, v in history if d >= cutoff]
    pe_ttm = code not in HK_IDS
    source = "中证滚动 PE" if pe_ttm else "股查查 PE · 恒生指数公司点位"
    if code == "NDX":
        source = "蛋卷/雪球 · 周频 PE，前值填充"
    full_prices = [(d, v) for d, v in prices if launch <= d <= history[-1][0]]
    prices = [(d, v) for d, v in full_prices if cutoff <= d <= history[-1][0]]
    notes = describe_index(history, prices)
    return make_chart(f"{name}（{code}）", history, source=f"{source} · {status}",
                      pe_ttm=pe_ttm, category="指数", notes=notes,
                      drawdowns=[("指数点位", full_prices, prices)])
