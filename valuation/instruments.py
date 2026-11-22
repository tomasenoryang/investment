"""港股估值和开放式基金净值查询。"""
from datetime import date, datetime, time, timedelta
import json
from urllib.parse import urlencode

from zoneinfo import ZoneInfo

from daily_cache import CACHE_DIR, cached
from history_sources import fetch_text

from index_history import range_start
from stock_pe import make_chart, normalize_history

from instrument_config import FUNDS

FUND_BENCHMARKS = {code: (item["name"], item["index"]) for code, item in FUNDS.items()}


def select_years(history, years):
    if not history:
        return history
    cutoff = range_start(history[-1][0], f"{years}y")
    return [(day, value) for day, value in history if day >= cutoff]


def load_hong_kong_history(code):
    import akshare as ak

    frame = ak.stock_hk_valuation_baidu(symbol=code, indicator="市盈率(TTM)", period="全部")
    return normalize_history(frame[["date", "value"]].itertuples(index=False, name=None))


def load_fund_history(code):
    import akshare as ak

    frame = ak.fund_open_fund_info_em(symbol=code, indicator="单位净值走势")
    if frame.empty:
        raise ValueError("该基金暂无可用的单位净值历史。")
    return normalize_history(frame[["净值日期", "单位净值"]].itertuples(index=False, name=None))


def fund_chart(code, years, *, history=None, status=""):
    if history is None:
        history = load_fund_history(code)
    name, _ = FUND_BENCHMARKS.get(code, (code, None))
    title = f"{name}（{code}）" if name != code else code
    window = select_years(history, years)
    return make_chart(title, window, drawdowns=[("单位净值", history, window)],
                      source="天天基金" + (f" · {status}" if status else ""), net_value=True, category="基金")


def stock_symbol(code, market):
    if market == "hk":
        return "hk" + code.zfill(5)
    if code.startswith("6"):
        return "sh" + code
    if code.startswith(("00", "30")):
        return "sz" + code
    if code.startswith(("4", "8", "920")):
        return "bj" + code
    return None


def quote_name(symbol):
    raw = fetch_text(f"https://qt.gtimg.cn/q={symbol}", encoding="gb18030")
    key, _, value = raw.strip().partition("=")
    fields = value.strip('";').split("~")
    if key == "v_" + symbol and len(fields) > 3 and fields[2] == symbol[2:]:
        return fields[1]
    if key == "v_pv_none_match" or (key == "v_" + symbol and not value.strip('";')):
        return None
    raise ValueError("无效的行情响应")


def lookup_instruments(code):
    matches = []
    market = "hk" if len(code) < 6 else "a"
    symbol = stock_symbol(code, market)
    if symbol:
        name = cached(("quote", symbol), lambda _: quote_name(symbol))
        if name:
            matches.append({"market": market, "code": symbol[2:], "name": name})

    if market == "a":
        import akshare as ak

        def load_catalog(_):
            funds = ak.fund_name_em()
            if funds.empty:
                raise ValueError("基金列表为空")
            return dict(zip(funds["基金代码"], funds["基金简称"]))

        name = cached(("fund-catalog",), load_catalog).get(code)
        if name:
            matches.append({"market": "fund", "code": code, "name": name})
    return matches


def latest_close_date(market, now):
    cutoff = time(16, 10) if market == "hk" else time(15)
    end = now.date() if now.time() >= cutoff else now.date() - timedelta(days=1)
    while end.weekday() >= 5:
        end -= timedelta(days=1)
    return end


def stock_price_chart(code, years, market, *, sync=True):
    symbol = stock_symbol(code, market)
    if not symbol:
        raise ValueError("无效的股票代码。")
    unit = "元" if market == "a" else "港元"
    end = latest_close_date(market, datetime.now(ZoneInfo("Asia/Shanghai")))
    start = range_start(end, f"{years}y")
    rows = []
    stale = False
    endpoint = "https://proxy.finance.qq.com/ifzqgtimg/appstock/app/newfqkline/get"
    def load_block(first, last):
        query = urlencode({"param": f"{symbol},day,{first},{last},640,"})
        response = json.loads(fetch_text(f"{endpoint}?{query}"))
        if response["code"] != 0 or not isinstance(response.get("data"), dict):
            raise ValueError("行情数据暂不可用。")
        series = response["data"].get(symbol)
        if not isinstance(series, dict) or not isinstance(series.get("day"), list):
            raise ValueError("行情数据暂不可用。")
        rows = normalize_history((day, close) for day, _, close, *_ in series["day"]
                                 if first.isoformat() <= day <= last.isoformat())
        return [(day.isoformat(), close) for day, close in rows if close is not None]

    # Fixed two-year windows let overlapping user-selected ranges share source requests.
    first_year = start.year - start.year % 2
    for path in CACHE_DIR.glob(f"price-{symbol}-[0-9][0-9][0-9][0-9].json"):
        year_key = path.stem.rsplit("-", 1)[1]
        if int(year_key) < first_year:
            block = cached(("price", symbol, year_key))
            if block:
                rows.extend(block["rows"])
    for year in range(first_year, end.year + 1, 2):
        first = date(year, 1, 1)
        last = min(end, date(year + 1, 12, 31))
        def update_block(previous):
            samples = dict(previous["rows"]) if previous else {}
            # Include the last recorded trading day for any closing-price correction.
            begin = date.fromisoformat(max(samples)) if samples else first
            incoming = load_block(begin, last)
            if samples and not incoming:
                raise ValueError("行情源未返回已知交易日的数据")
            samples.update(incoming)
            # A provider may still publish the requested close on the following day.
            confirmed = last if last < date(end.year - end.year % 2, 1, 1) else max(samples, default="")
            return {"through": last.isoformat(), "confirmed_through": str(confirmed),
                    "rows": sorted(samples.items())}

        key = ("price", symbol, str(year))
        try:
            block = cached(key, update_block if sync else None, valid_through=last.isoformat())
        except Exception:
            block = cached(key)
            if block is None:
                raise
            stale = True
        if block is None:
            continue
        rows.extend(block["rows"])
    full_history = [(d, v) for d, v in normalize_history(rows) if d <= end]
    history = [(d, v) for d, v in full_history if d >= start]
    if len(history) < 2:
        raise ValueError("暂无可用的收盘价历史")
    title = f"{'A 股' if market == 'a' else '港股'} {code}"
    source = "腾讯行情 · 不复权" + (" · 数据未能更新 · 使用已保存历史" if stale else "")
    return make_chart(title, history, source=source, price_unit=unit,
                      price_metric="日收盘价", category="股票", drawdowns=[("日收盘价", full_history, history)])
