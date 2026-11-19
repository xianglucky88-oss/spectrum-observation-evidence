from __future__ import annotations

from .contract import Row, apply_rows, index_rows, integer, read_rows, span


def transform(row: Row) -> Row:
    """把模拟扫频批次拆成覆盖来源一致的频段，保留漏扫与粗测区间。"""
    low, high = span(row, "low_khz", "high_khz")
    limit = integer(row, "fine_bin_khz", minimum=1)
    windows = []
    edges = {low, high}
    for name, reading in index_rows(read_rows(row, "sweeps"), "sweep").items():
        start, end = span(reading, "low_khz", "high_khz")
        width = integer(reading, "bin_khz", minimum=1)
        a, b = max(low, start), min(high, end)
        if a < b:
            edges.update((a, b))
            windows.append((a, b, width, name))
    points = sorted(edges)
    result = []
    for a, b in zip(points, points[1:]):
        scans = [(width, name) for lo, hi, width, name in windows if lo <= a and hi >= b]
        result.append(dict(band_khz=[a, b], sweeps=sorted(name for _, name in scans),
                           coverage="fine" if any(width <= limit for width, _ in scans) else "coarse" if scans else "missing"))
    return {"bands": result}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
