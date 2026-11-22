"""使用基金管理人公布的基金收益和合同业绩基准，按共同日期归一到 100。"""
import csv
from datetime import date
from io import StringIO
import json
from math import isfinite
from xml.sax.saxutils import escape

from interval_stats import drawdown_header
from daily_cache import cached
from history_sources import fetch_text, refresh_history, saved_history
from index_history import hk_prices, index_bundle, range_start

from instrument_config import FUNDS
from urllib.parse import urlencode


def fetch_returns(code):
    if FUNDS[code]["provider"] == "nffund":
        payload = json.loads(fetch_text("https://www.nffund.com/nfwebApi/fund/earningsMovements",
                                        data=urlencode({"fundCode": code, "months": 7}).encode()))
        data = payload["data"]
        if data.get("jzzscode") != FUNDS[code]["source_index"]:
            raise ValueError("基金跟踪标的未核实")
        benchmark = {row["fdate"]: row["upratio"] for row in data["brList"]}
        index_returns = {r["fdate"]: r["upratio"] for r in data["jzlist"]}
        pairs = [(r["fdate"], r["upratio"], benchmark.get(r["fdate"])) for r in data["thisfundlist"]]
    elif FUNDS[code]["provider"] == "jsfund":
        query = urlencode({"funcNo": "741032", "product_id": FUNDS[code]["product_id"], "product_code": code})
        data = json.loads(fetch_text("https://www.jsfund.cn/servlet/json?" + query))["results"]
        if not any(FUNDS[code]["source_index"] in r.get("index_name", "") and "人民币" in r["index_name"] for r in data):
            raise ValueError("人民币业绩基准未核实")
        pairs = [(r["date"], r["nav_yield"], r["hs300_yield"]) for r in data]

    else:
        raise ValueError("未配置支持的基金收益来源")

    rows = {}
    for day, fund, benchmark in pairs:
        if fund in ("", None) or benchmark in ("", None):
            continue
        values = [100 + float(fund), 100 + float(benchmark)]
        if all(isfinite(v) and v > 0 for v in values):
            if FUNDS[code]["provider"] == "nffund":
                raw = index_returns.get(day)
                level = 100 + float(raw) if raw not in ("", None) else None
                values.append(level if level and isfinite(level) and level > 0 else None)
            rows[date.fromisoformat(day).isoformat()] = values
    return [[d, *rows[d]] for d in sorted(rows)]


def ecb_hkd_cny(previous):
    start = previous[-1][0] if previous else "2018-11-28"
    url = ("https://data-api.ecb.europa.eu/service/data/EXR/D.CNY+HKD.EUR.SP00.A"
           f"?startPeriod={start}&format=csvdata")
    rates = {"CNY": {}, "HKD": {}}
    for row in csv.DictReader(StringIO(fetch_text(url))):
        if row["CURRENCY_DENOM"] == "EUR" and row["OBS_VALUE"]:
            value = float(row["OBS_VALUE"])
            if isfinite(value) and value > 0:
                rates[row["CURRENCY"]][row["TIME_PERIOD"]] = value
    incoming = {day: yuan / rates["HKD"][day] for day, yuan in rates["CNY"].items() if day in rates["HKD"]}
    if not incoming or max(incoming) < start:
        raise ValueError("缺少同日港币人民币参考汇率")
    return sorted((dict(previous or []) | incoming).items())


def tracking_levels(code, rows, sync):
    if FUNDS[code]["provider"] == "nffund":
        if any(len(r) > 3 and r[3] for r in rows):
            return {r[0]: r[3] for r in rows if len(r) > 3 and r[3]}
        # Legacy daily caches contain only the fund and contract benchmark.
        key = ("index-bundle", FUNDS[code]["index"])
        bundle = cached(key, (lambda prev: index_bundle(FUNDS[code]["index"], prev)) if sync else None)
        return dict(bundle["price"]) if bundle else {}

    key = ("index-price", FUNDS[code]["index"])
    if sync:
        prices, _ = refresh_history(key, [], lambda: hk_prices(FUNDS[code]["index"]))
    else:
        prices, _ = saved_history(key, [])
    fx_key = ("fx", "ecb-hkd-cny")
    try:
        fx = cached(fx_key, ecb_hkd_cny if sync else None)
    except Exception:
        fx = cached(fx_key)
    fx = dict(fx or [])
    return {day.isoformat(): value * fx[day.isoformat()] for day, value in prices
            if value and day.isoformat() in fx}


def tracking_summary(fund_return, index_return):
    if index_return == 0:
        return "区间指数跟踪率 —（指数累计收益为零）"
    ratio = 100 * fund_return / index_return
    return f"区间指数跟踪率 {ratio:.2f}%"


def comparison_chart(code, years, sync):
    key = ("fund-return-pair", code)
    def update(previous):
        rows = fetch_returns(code)
        if len(rows) < 2 or (previous and rows[-1][0] < previous[-1][0]):
            raise ValueError("收益数据缺失或日期回退")
        return rows

    stale = False
    try:
        rows = cached(key, update if sync else None)
    except Exception:
        rows = cached(key)
        stale = True
    if not rows:
        raise ValueError("暂无收益对比数据，请手动刷新同步")
    cutoff = range_start(date.fromisoformat(rows[-1][0]), f"{years}y").isoformat()
    full_rows = rows
    rows = [r for r in full_rows if r[0] >= cutoff]
    if len(rows) < 2:
        raise ValueError("所选区间共同日期不足")
    days = [date.fromisoformat(r[0]) for r in rows]
    fund = [100 * r[1] / rows[0][1] for r in rows]
    bench = [100 * r[2] / rows[0][2] for r in rows]
    levels = tracking_levels(code, full_rows, sync)
    full_index = sorted(levels.items())
    index_window = [(d, v) for d, v in full_index if rows[0][0] <= d <= rows[-1][0]]
    series = [(label, [(r[0], r[col]) for r in full_rows], [(r[0], r[col]) for r in rows])
              for col, label in [(1, "基金收益"), (2, "合同基准")]]
    header, offset = drawdown_header(series + [("跟踪指数", full_index, index_window)])
    height = 690 + offset
    common = [i for i,r in enumerate(rows) if r[0] in levels]
    tracking = [None] * len(rows)
    if len(common) >= 2:
        first = common[0]
        for i in common:
            index_growth = levels[rows[i][0]] / levels[rows[first][0]]
            fund_growth = rows[i][1] / rows[first][1]
            tracking[i] = round(100 * (fund_growth - index_growth), 4)
    lo, hi = min(min(fund), min(bench)), max(max(fund), max(bench))
    pad = max((hi-lo)*.08, .5)
    lo, hi = lo-pad, hi+pad
    xs = [80 + 880*(d-days[0]).days/(days[-1]-days[0]).days for d in days]
    def y(value):
        return 420 - 300*(value-lo)/(hi-lo)
    points = [[round(x, 2), round(y(f) + offset, 2), d.isoformat(), round(f, 3), round(b, 3), t]
              for x, d, f, b, t in zip(xs, days, fund, bench, tracking)]
    metadata = {"plot":[80,120+offset,960,420+offset], "metric":"基金", "unit":"点", "digits":2, "points":points,
                "comparison":"合同基准", "tracking":True}
    status = " · 数据未能更新，使用已保存历史" if stale else ""
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1040 {height}" width="1040" height="{height}">',
             f'<rect width="1040" height="{height}" fill="#f7f9fc"/>',
             f'<metadata id="chart-data">{escape(json.dumps(metadata, ensure_ascii=False))}</metadata>',
             '<g font-family="sans-serif" fill="#21324a">',
             f'<text x="50" y="45" font-size="27">【基金】{code} · 基金收益与指数跟踪</text>',
             f'<text x="50" y="78" font-size="17">{days[0]} 至 {days[-1]} · 起点均为 100 · 基金管理人公布收益{status}</text>',
             header, f'<g transform="translate(0 {offset})">']
    for i in range(5):
        level = lo+(hi-lo)*i/4
        parts.append(f'<path d="M80 {y(level):.2f}H960" stroke="#dce4ef"/><text x="72" y="{y(level)+4:.2f}" text-anchor="end">{level:.1f}</text>')
    for values, color, dash in [(fund, "#165aa0", "none"), (bench, "#a45d12", "8 4")]:
        coords = " ".join(f"{x:.2f},{y(v):.2f}" for x,v in zip(xs,values))
        parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" stroke-width="2.4" stroke-dasharray="{dash}"/>')
    parts.extend([f'<text x="80" y="445">{days[0]}</text><text x="960" y="445" text-anchor="end">{days[-1]}</text>',
                  f'<text x="80" y="495" fill="#165aa0">实线 · 基金 {fund[-1]-100:+.2f}%</text>',
                  f'<text x="380" y="495" fill="#a45d12">虚线 · 合同基准 {bench[-1]-100:+.2f}%</text>',
                  f'<text x="720" y="495">较基准 {fund[-1]-bench[-1]:+.2f} 个百分点</text>',
                  f'<text x="80" y="525" font-size="16">基准：{escape(FUNDS[code]["terms"])}</text>'])
    if len(common) >= 2:
        last = common[-1]
        fund_return = 100 * (rows[last][1] / rows[first][1] - 1)
        index_return = 100 * (levels[rows[last][0]] / levels[rows[first][0]] - 1)
        summary = tracking_summary(fund_return, index_return)
        coverage = " · 按实际可用区间计算" if (days[first] - date.fromisoformat(cutoff)).days > 31 or last != len(rows)-1 else ""
        parts.append(f'<text x="80" y="558" font-size="20" font-weight="bold">{summary}</text>')
        parts.append(f'<text x="80" y="585" font-size="16">基金累计收益 {fund_return:+.2f}% ÷ 跟踪指数累计收益 {index_return:+.2f}%　·　相差 {tracking[last]:+.2f} 个百分点</text>')
        parts.append(f'<text x="80" y="619" font-size="16">近 {years} 年 · 共同数据 {days[first]} 至 {days[last]}{coverage}</text>')
    else:
        parts.append('<text x="80" y="558">缺少共同日期，暂无指数跟踪读数。</text>')
    note = escape(FUNDS[code]["tracking"])
    parts.append(f'<text x="80" y="657" font-size="15">跟踪标的：{note}</text>')
    parts.append("</g></g></svg>")
    return "".join(parts)
