from __future__ import annotations

from .contract import Row, apply_rows, choice, flag, index_rows, integer, read_rows


def transform(row: Row) -> Row:
    """仅用定时等间隔采样估计占用率，另留触发采样记录。"""
    scheduled = {}
    triggered = []
    for name, item in index_rows(read_rows(row, "readings"), "reading").items():
        mode = choice(item, "mode", {"scheduled", "triggered"})
        active = flag(item, "occupied")
        if mode == "triggered":
            if active:
                triggered.append(name)
            continue
        slot = integer(item, "slot")
        if slot in scheduled:
            raise ValueError("duplicate scheduled sample for slot")
        scheduled[slot] = active
    occupied = sum(scheduled.values())
    return {"scheduled_count": len(scheduled), "occupied_count": occupied,
            "observed_fraction": occupied / len(scheduled) if scheduled else None, "triggered_activity": triggered}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
