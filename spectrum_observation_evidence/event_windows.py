from __future__ import annotations

from .contract import Row, apply_rows, index_rows, merge_spans, read_rows, span, text


def transform(row: Row) -> Row:
    """按人工事件标记归并频段范围，保留与其他事件交叠的复核线索。"""
    groups = {}
    for window, mark in index_rows(read_rows(row, "windows"), "window").items():
        groups.setdefault(text(mark, "event"), []).append((window, span(mark, "low_khz", "high_khz")))
    merged = {event: merge_spans(bounds for _, bounds in windows) for event, windows in groups.items()}
    events = {event: dict(bands_khz=[list(pair) for pair in merged[event]], windows=sorted(name for name, _ in windows)) for event, windows in groups.items()}
    overlaps = []
    names = sorted(groups)
    for i, left in enumerate(names):
        for right in names[i + 1:]:
            for a, b in merged[left]:
                for c, d in merged[right]:
                    if max(a, c) < min(b, d):
                        overlaps.append(dict(events=[left, right], band_khz=[max(a, c), min(b, d)]))
    return {"events": events, "ambiguous_overlaps": overlaps}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
