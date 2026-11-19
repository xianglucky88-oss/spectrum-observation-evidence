from __future__ import annotations

from .contract import Row, apply_rows, flag, index_rows, number, read_rows, text


def transform(row: Row) -> Row:
    """按接收设置核对同标度读数，分开可用背景、过载和低于有效量程的读数。"""
    limits = {}
    for setup, item in index_rows(read_rows(row, "settings"), "setup").items():
        floor, ceiling = number(item, "floor"), number(item, "ceiling")
        if floor >= ceiling:
            raise ValueError("invalid receiver range")
        limits[setup] = (floor, ceiling)
    observations = {}
    for reading, item in index_rows(read_rows(row, "samples"), "reading").items():
        setup = text(item, "setup")
        floor, ceiling = limits[setup]
        level = number(item, "level")
        state = "clipped" if flag(item, "overload") or level >= ceiling else "below-range" if level < floor else "usable"
        observations[reading] = dict(setup=setup, status=state, comparable_level=level if state == "usable" else None)
    return {"observations": observations}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
