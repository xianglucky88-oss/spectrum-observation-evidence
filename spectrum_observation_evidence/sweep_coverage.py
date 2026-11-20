from __future__ import annotations

from .contract import Row, apply_rows, index_rows, number, plain, read_rows


def _bounds(row: Row, low_field: str, high_field: str) -> tuple[int | float, int | float]:
    low = number(row, low_field)
    high = number(row, high_field)
    if low >= high:
        raise ValueError(f"{low_field} must be below {high_field}")
    return plain(low), plain(high)


def transform(row: Row) -> Row:
    """把模拟扫频批次拆成覆盖来源一致的频段，保留漏扫与粗测区间。

    分辨率以每个频段的实际 bin 宽度表达。粗扫不能证明它未分辨的指定子带，
    所以粗扫覆盖的频段仍应能查到这段曾有粗扫，而不是被当作精细覆盖。
    """
    low, high = _bounds(row, "low_khz", "high_khz")
    limit = number(row, "fine_bin_khz")
    if limit <= 0:
        raise ValueError("fine_bin_khz must be positive")
    windows = []
    edges = {low, high}
    for name, reading in index_rows(read_rows(row, "sweeps"), "sweep").items():
        start, end = _bounds(reading, "low_khz", "high_khz")
        width = number(reading, "bin_khz")
        if width <= 0:
            raise ValueError("bin_khz must be positive")
        a, b = max(low, start), min(high, end)
        if a < b:
            edges.update((a, b))
            windows.append((a, b, width, name))
    points = sorted(edges)
    bands = []
    for a, b in zip(points, points[1:]):
        scans = [(width, name) for lo, hi, width, name in windows if lo <= a and hi >= b]
        fine = sorted(name for width, name in scans if width <= limit)
        coarse = sorted(name for width, name in scans if width > limit)
        bands.append(
            {
                "band_khz": [a, b],
                "sweeps": sorted(name for _, name in scans),
                "coverage": "fine" if fine else "coarse" if coarse else "missing",
                "fine_bin_khz": plain(limit),
                "resolution_khz": sorted({plain(width) for width, _ in scans}),
                "fine_sweeps": fine,
                "coarse_sweeps": coarse,
                "reason": "fine-resolution-sweep" if fine else "coarse-sweep-cannot-prove-subbands" if coarse else "no-sweep-coverage",
            }
        )
    return {"bands": bands}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
