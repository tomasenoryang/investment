"""输入 A 股个股代码，生成滚动市盈率 SVG 曲线图。"""
import argparse
import json
from datetime import date
from math import ceil, floor, isfinite
from pathlib import Path
import re
from statistics import mean
from xml.sax.saxutils import escape
import webbrowser

from interval_stats import drawdown_header, recovery_notes

PERIODS = {1: "近一年", 3: "近三年", 5: "近五年", 10: "近十年"}


def percentile(values, fraction):
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    lower = floor(index)
    upper = ceil(index)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower)


def load_history(code, years):
    import akshare as ak

    data = ak.stock_zh_valuation_baidu(
        symbol=code, indicator="市盈率(TTM)", period=PERIODS[years]
    )
    return normalize_history(data[["date", "value"]].itertuples(index=False, name=None))


def normalize_history(rows):
    points = {}
    for day, value in rows:
        try:
            day = date.fromisoformat(str(day)[:10])
        except ValueError:
            continue
        try:
            value = float(value)
        except (ValueError, TypeError):
            value = None
        points[day] = value if value is not None and isfinite(value) and value > 0 else None
    return sorted(points.items())


def make_chart(code, history, *, source="百度股市通", reference_lines=None, net_value=False, pe_ttm=True, price_unit=None, category=None, price_metric="价格", notes=(), drawdowns=()):
    valid = [(day, value) for day, value in history if value is not None]
    if len(valid) < 2:
        raise ValueError("有效数据不足两条，无法绘制曲线。")

    values = [value for _, value in valid]
    start, end = history[0][0], history[-1][0]
    low, average, high = reference_lines or (
        percentile(values, .2), mean(values), percentile(values, .8)
    )
    notes = list(notes)
    if not (net_value or price_unit):
        notes.extend(recovery_notes(history, low, average))
    header, offset = drawdown_header(drawdowns)
    minimum = min(values) if net_value else min(min(values), low, average, high)
    maximum = max(values) if net_value else max(max(values), low, average, high)
    metric, unit = ("单位净值", "元") if net_value else ("滚动市盈率" if pe_ttm else "市盈率", "倍")
    digits = 4 if net_value else 2
    axis_label = "单位净值（元）" if net_value else ("PE-TTM（倍）" if pe_ttm else "PE（倍）")
    if price_unit:
        metric, unit = price_metric, price_unit
        axis_label = f"{metric}（{price_unit}）"
    spread = max(maximum - minimum, maximum * .05)
    bottom, top = max(0, minimum - .1 * spread), maximum + .1 * spread

    def x(day):
        return 80 + 880 * (day - start).days / (end - start).days

    def y(value):
        return 420 - 300 * (value - bottom) / (top - bottom)

    title = f"{code} {metric}走势"
    category = category or (None if price_unit else "股票")
    if category:
        title = f"【{category}】{title}"

    chart_data = {
        "plot": [80, 120 + offset, 960, 420 + offset],
        "metric": metric,
        "unit": unit,
        "digits": digits,
        "points": [[round(x(day), 2), round(y(value) + offset, 2), day.isoformat(), value]
                   for day, value in valid],
    }
    metadata = escape(json.dumps(chart_data, ensure_ascii=False, separators=(",", ":")))
    height = 550 + 32 * len(notes) + offset
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="1040" height="{height}" viewBox="0 0 1040 {height}">',
        f'<metadata id="chart-data">{metadata}</metadata>',
        f'<rect width="1040" height="{height}" fill="#f7f9fc"/>',
        '<g font-family="PingFang SC, Microsoft YaHei, sans-serif" fill="#21324a">',
        f'<text x="50" y="50" font-size="30" font-weight="bold">{escape(title)}</text>',
        f'<text x="50" y="80" font-size="17">{start} 至 {end} · {axis_label} · {source}</text>',
        header, f'<g transform="translate(0 {offset})">',
    ]
    for index in range(6):
        value = bottom + (top - bottom) * index / 5
        day = start + (end - start) * index / 5
        parts.extend([
            f'<path d="M80 {y(value):.2f}H960" stroke="#dce4ef"/>',
            f'<text x="73" y="{y(value)+5:.2f}" text-anchor="end" font-size="13">{value:.{digits}f}</text>',
            f'<text x="{x(day):.2f}" y="448" text-anchor="middle" font-size="13">{day}</text>',
        ])

    lines = [
        ("价格 P20" if price_unit else "低估线（P20）", low, "#157554", "3 4"),
        ("均值线", average, "#946414", "8 5"),
        ("价格 P80" if price_unit else "高估线（P80）", high, "#b13939", "12 5"),
    ]
    for index, (label, value, color, dash) in enumerate([] if net_value else lines):
        parts.append(f'<path d="M80 {y(value):.2f}H960" stroke="{color}" stroke-width="2" stroke-dasharray="{dash}"/>')
        parts.append(f'<text x="{80 + index * 270}" y="483" fill="{color}" font-size="17">{label} {value:.2f} {unit}</text>')

    commands = []
    move = True
    for day, value in history:
        if value is None:
            move = True
            continue
        commands.append(f'{"M" if move else "L"}{x(day):.2f} {y(value):.2f}')
        move = False
    path = " ".join(commands)
    last_day, last_value = valid[-1]
    parts.extend([
        f'<path d="{path}" fill="none" stroke="#1765bd" stroke-width="2.5" stroke-linejoin="round"/>',
        f'<circle cx="{x(last_day):.2f}" cy="{y(last_value):.2f}" r="4.5" fill="#1765bd" stroke="transparent" stroke-width="12">'
        f'<title>{last_day} · {metric} {last_value:.{digits}f} {unit}</title></circle>',
        f'<text x="80" y="516" fill="#1765bd" font-size="16">最近有效值 {last_value:.{digits}f} {unit}（{last_day}）· 有效样本 {len(valid)} 条</text>',
        *(f'<text x="80" y="{552+i*32}" font-size="17">{escape(note)}</text>' for i, note in enumerate(notes)),
        '</g></g></svg>',
    ])
    return "\n".join(parts)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("code", nargs="?", help="六位 A 股个股代码")
    parser.add_argument("--years", type=int, choices=PERIODS, default=5)
    args = parser.parse_args()
    try:
        code = (args.code or input("请输入六位 A 股个股代码：")).strip()
    except (EOFError, KeyboardInterrupt):
        parser.exit(1, "未收到股票代码。\n")
    if not re.fullmatch(r"[0-9]{6}", code):
        parser.error("请输入六位数字股票代码。")

    try:
        history = load_history(code, args.years)
    except ModuleNotFoundError as error:
        parser.exit(1, f"缺少依赖（{error.name}），请运行 python3 -m pip install -U akshare\n")
    except Exception as error:
        parser.exit(1, f"获取 {code} 估值失败，请检查代码、网络和数据源状态。{error}\n")

    output = Path(f"{code}-pe-{args.years}y.svg").resolve()
    try:
        output.write_text(make_chart(code, history), encoding="utf-8")
    except (ValueError, OSError) as error:
        parser.exit(1, f"{error}\n")
    print(f"图表已保存：{output}")
    webbrowser.open(output.as_uri())


if __name__ == "__main__":
    main()
