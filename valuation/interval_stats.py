"""根据图表所用的有序历史样本，统计估值修复和峰谷回撤。"""

from xml.sax.saxutils import escape


def recovery_notes(history, low, target):
    notes = [f"低估修复 · PE ≤ 区间 P20（{low:.2f} 倍）进入，首次回到区间均值（{target:.2f} 倍）算修复"]
    if low >= target:
        return notes + ["修复线未高于低估线，此区间无法区分低估与修复。"]

    completed = []
    start = previous = None
    partial = False
    interrupted = 0
    boundary_notes = []
    for day, value in history:
        if value is None:
            interrupted += int(start is not None)
            start = previous = None
            continue
        if start is None and value <= low:
            start, partial = day, previous is None
        elif start is not None and value >= target:
            duration = (day - start).days
            if partial:
                boundary_notes.append(f"起点不明 · {start} 首次观测时已低估，{day} 修复，至少 {duration} 天")
            else:
                completed.append((duration, start, day))
            start = None
        previous = day

    if completed:
        days, first, last = max(completed, key=lambda cycle: cycle[0])
        notes.append(f"最长已修复周期 {days} 个自然日 · {first} 至 {last} · 共 {len(completed)} 个完整周期")
    else:
        notes.append("区间内没有起止均可确认的已修复周期。")
    if boundary_notes:
        notes.append(boundary_notes[0])
        if len(boundary_notes) > 1:
            notes.append(f"另有 {len(boundary_notes) - 1} 个起点不明的周期，未计入最长纪录。")
    if start is not None:
        notes.append(f"尚未修复 · {start} 至 {previous} · 已观察 {(previous-start).days} 天"
                     + ("（低估起点可能更早）" if partial else ""))
    if interrupted:
        notes.append(f"另有 {interrupted} 个周期因 PE 数据中断，修复时间未知。")
    return notes


def drawdown(history):
    valid = [(day, value) for day, value in history if value is not None and value > 0]
    if len(valid) < 2:
        return None
    peak_day, peak = valid[0]
    worst, first, last = 0, None, None
    for day, value in valid[1:]:
        if value >= peak:
            peak_day, peak = day, value
        elif (drop := (peak - value) / peak) > worst:
            worst, first, last = drop, peak_day, day
    return worst, first, last, valid[0][0], valid[-1][0]


def drawdown_header(series):
    """在 SVG 标题和曲线之间绘制两列指标，并返回绘图区所需的下移距离。"""
    if not series:
        return "", 0
    parts = []
    for column, title in enumerate(("历史最大回撤率", "时间区间最大回撤率")):
        scope = "window" if column else "history"
        parts.append(f'<g data-drawdown="{scope}">')
        x = 50 + column * 500
        parts.append(f'<text x="{x}" y="119" font-size="20" font-weight="bold">{title}</text>')
        for i, (label, full, window) in enumerate(series):
            y = 150 + i * 80
            result = drawdown(window if column else full)
            value = f"{result[0]:.2%}" if result else "有效样本不足"
            parts.append(f'<text x="{x}" y="{y}" font-size="20">{escape(label)}　{value}</text>')
            if result:
                rate, peak, trough, start, end = result
                detail = f"峰 {peak} → 谷 {trough}" if rate else "期间未观察到下跌"
                parts.append(f'<text x="{x}" y="{y+22}" font-size="16">{detail}</text>')
                parts.append(f'<text x="{x}" y="{y+42}" font-size="15" fill="#51627a">样本 {start} 至 {end}</text>')
        parts.append("</g>")
    return "".join(parts), 24 + 80 * len(series)
