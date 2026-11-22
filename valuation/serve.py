"""在本机浏览器中查看 A 股估值曲线。"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from fund_returns import comparison_chart
from gold_history import MARKETS, gold_chart
from index_history import INDICES, RANGES, index_chart
from history_sources import refresh_history, saved_history
from instruments import (
    FUND_BENCHMARKS, fund_chart, load_hong_kong_history, load_fund_history,
    lookup_instruments, select_years, stock_price_chart,
)
from stock_pe import PERIODS, load_history, make_chart

DIRECTORY = Path(__file__).resolve().parent
FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/chart-interaction.js": ("chart-interaction.js", "text/javascript; charset=utf-8"),
}


class Handler(BaseHTTPRequestHandler):
    def send_content(self, status, content, content_type, benchmark=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        if content_type == "image/svg+xml" and "数据未能更新".encode() in content:
            self.send_header("X-Data-Stale", "1")
        if benchmark:
            self.send_header("X-Benchmark-Code", benchmark)
        self.end_headers()
        self.wfile.write(content)

    def error_message(self, status, message):
        self.send_content(status, json.dumps({"message": message}).encode(), "application/json")

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path in FILES:
            filename, content_type = FILES[url.path]
            content = (DIRECTORY / filename).read_bytes()
            if url.path == "/":
                indices = {code: index for code, (_, index) in FUND_BENCHMARKS.items()}
                encoded = json.dumps(indices).replace("<", "\\u003c").encode()
                content = content.replace(b'id="fund-indices">{}</script>',
                                          b'id="fund-indices">' + encoded + b'</script>')
            self.send_content(200, content, content_type)
            return
        if url.path == "/api/gold-chart":
            query = parse_qs(url.query)
            market = query.get("market", [""])[0]
            period = query.get("range", ["1m"])[0]
            if market not in MARKETS or period not in RANGES:
                self.error_message(400, "黄金市场或时间区间无效。")
                return
            self.send_content(200, gold_chart(market, period, sync=query.get("sync") == ["1"]).encode(), "image/svg+xml")
            return
        if url.path == "/api/index-chart":
            query = parse_qs(url.query)
            code = query.get("code", [""])[0]
            period = query.get("range", ["1m"])[0]
            if code not in INDICES or period not in RANGES:
                self.error_message(400, "指数代码或时间区间无效。")
                return
            svg = index_chart(code, period, sync=query.get("sync") == ["1"])
            self.send_content(200, svg.encode(), "image/svg+xml")
            return
        if url.path == "/api/instruments":
            code = parse_qs(url.query).get("code", [""])[0]
            numeric = re.fullmatch(r"[0-9]{1,6}", code)
            if not numeric and code not in INDICES:
                self.error_message(400, "请输入有效代码。")
                return
            try:
                matches = lookup_instruments(code) if numeric else []
            except Exception:
                if code not in INDICES:
                    self.error_message(502, "品种列表暂时不可用，请重试。")
                    return
                matches = []
            if code in INDICES:
                matches.append({"market": "index", "code": code, "name": INDICES[code][0]})
            self.send_content(200, json.dumps(matches).encode(), "application/json")
            return

        if url.path == "/api/fund-comparison":
            query = parse_qs(url.query)
            code = query.get("code", [""])[0]
            years = query.get("years", ["5"])[0]
            if code not in FUND_BENCHMARKS or years not in {str(n) for n in PERIODS}:
                self.error_message(400, "无效的基金或比较区间。")
                return
            try:
                svg = comparison_chart(code, int(years), query.get("sync") == ["1"])
            except ValueError as error:
                self.error_message(422, str(error))
                return
            self.send_content(200, svg.encode(), "image/svg+xml")
            return

        if url.path not in {"/api/chart", "/api/stock-price"}:
            self.send_error(404)
            return

        query = parse_qs(url.query)
        code = query.get("code", [""])[0]
        years = query.get("years", ["5"])[0]
        market = query.get("market", ["a"])[0]
        pattern = {"a": r"[0-9]{6}", "hk": r"[0-9]{1,5}", "fund": r"[0-9]{6}"}.get(market)
        if not pattern or not re.fullmatch(pattern, code) or years not in {str(n) for n in PERIODS}:
            self.error_message(400, "请检查品种、代码位数和查询区间。")
            return

        symbol = code.zfill(5) if market == "hk" else code
        is_price = url.path == "/api/stock-price"
        if is_price and market == "fund":
            self.error_message(400, "股价查询仅支持股票。")
            return
        dashboard = query.get("dashboard") == ["1"]
        try:
            if is_price:
                svg = stock_price_chart(symbol, int(years), market,
                                        sync=not dashboard or query.get("sync") == ["1"])
            else:
                key = ("history", market, symbol)
                if not dashboard or query.get("sync") == ["1"]:
                    def fetch_history():
                        if market == "fund":
                            return load_fund_history(symbol)
                        if market == "hk":
                            return load_hong_kong_history(symbol)
                        return load_history(symbol, max(PERIODS))

                    history, status = refresh_history(key, [], fetch_history)
                else:
                    history, status = saved_history(key, [])
                if not history:
                    self.error_message(404, "暂无可用数据，请手动刷新或重新查询。")
                    return
                if market == "fund":
                    svg = fund_chart(symbol, int(years), history=history, status=status)
                else:
                    title = f"港股 {symbol}" if market == "hk" else symbol
                    svg = make_chart(title, select_years(history, int(years)),
                                     source=f"百度股市通 · {status}")
        except ModuleNotFoundError:
            self.error_message(503, "缺少 AKShare 依赖，请按 README 安装后重新启动。")
            return
        except ValueError:
            self.error_message(422, "有效历史数据不足，请核对代码或尝试更长的区间。")
            return
        except Exception:
            self.error_message(502, "数据源暂时未返回可用历史。请核对品种、代码和网络后重试。")
            return

        benchmark = FUND_BENCHMARKS.get(code, (None, None))[1] if market == "fund" else None
        self.send_content(200, svg.encode(), "image/svg+xml", benchmark)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    with ThreadingHTTPServer(("127.0.0.1", args.port), Handler) as server:
        print(f"浏览器打开 http://127.0.0.1:{server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
