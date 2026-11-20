"""定时占用：在计划时频范围内按证据给出占用的上下界。

分母固定为计划时长 × 计划频宽。所有测得的时频矩形先按边界切分，同一部分即使
被多次重叠测到也只在分母里计一次。每个切分单元按下列顺序归为一种状态：

- ``occupied``：只看分辨率足够的定时读数，确定占用的证据一致；
- ``not-occupied``：只看分辨率足够的定时读数，确定未占用的证据一致；
- ``conflict``：确定占用与确定未占用在同一单元相撞，保留为不确定性；
- ``insufficient-resolution``：有定时读数但粗于指定分辨率，不能证明其未分辨的子带；
- ``inconclusive``：有定时读数，但量程依据或界限不足以判定；
- ``trigger-only``：没有定时读数覆盖，只有触发补测覆盖；
- ``no-scheduled-evidence``：计划内完全没有定时读数覆盖。

只有 ``occupied`` 计入下界；``not-occupied`` 从分母中扣除得到上界。其余状态既
不算空闲也不计入下界，全部留在上下界之间的不确定性里。触发采样只解释活动，
不代替定时样本。
"""

from __future__ import annotations

from .contract import (
    Row,
    apply_rows,
    index_rows,
    number,
    optional,
    optional_flag,
    optional_text,
    plain,
    read_array,
    read_rows,
    text,
)
from .evidence import evidence_reason, explicit_evidence, level_evidence, read_limits, verdict


STATUSES = (
    "occupied",
    "not-occupied",
    "conflict",
    "insufficient-resolution",
    "inconclusive",
    "trigger-only",
    "no-scheduled-evidence",
)


def _coord(value: float) -> int | float:
    return plain(value)


def _pair(row: Row, field: str) -> tuple[int | float, int | float]:
    values = read_array(row, field)
    if len(values) != 2:
        raise ValueError(f"{field} must have two endpoints")
    low, high = (_coord(number({field: value}, field)) for value in values)
    if low >= high:
        raise ValueError(f"{field} must have positive width")
    return low, high


def _plan(row: Row) -> Row:
    plan = row["plan"]
    if not isinstance(plan, dict):
        raise ValueError("plan must be a JSON object")
    start = _coord(number(plan, "start_s"))
    end = _coord(number(plan, "end_s"))
    low = _coord(number(plan, "low_khz"))
    high = _coord(number(plan, "high_khz"))
    if start >= end or low >= high:
        raise ValueError("plan must have positive duration and bandwidth")
    result = {"start_s": start, "end_s": end, "low_khz": low, "high_khz": high}
    if "interval_s" in plan:
        interval = _coord(number(plan, "interval_s"))
        if interval <= 0:
            raise ValueError("plan interval_s must be positive")
        result["interval_s"] = interval
    return result


def _window(row: Row, plan: Row) -> tuple[int | float, int | float]:
    """读数的时间窗：显式 ``time_s`` 优先，其次按计划间隔和 ``slot`` 推算。"""
    if "time_s" in row:
        return _pair(row, "time_s")
    if "slot" in row:
        if "interval_s" not in plan:
            raise ValueError("plan needs interval_s when readings use slot")
        interval = number(plan, "interval_s")
        if interval <= 0:
            raise ValueError("plan interval_s must be positive")
        slot = number(row, "slot", minimum=0)
        start = plan["start_s"] + slot * interval
        return _coord(start), _coord(start + interval)
    raise ValueError("reading needs time_s or slot")


def _evidence(row: Row, limits: dict[str, tuple[float, float]], referenced: Row | None) -> Row:
    """读数自带界限优先，其次引用离线量程核查事实，最后按同标度量程换算。"""
    if "lower_bound" in row or "upper_bound" in row:
        evidence = explicit_evidence(
            optional(row, "lower_bound", number),
            optional(row, "upper_bound", number),
            row.get("bound_basis"),
            "reading-carries-bounds",
        )
        if evidence["status"] == "no-range-basis":
            evidence["reason"] = "reading-has-no-bounds"
        return evidence
    if referenced is not None:
        if "status" not in referenced:
            raise ValueError("range_evidence entry needs status")
        evidence = explicit_evidence(
            optional(referenced, "lower_bound", number),
            optional(referenced, "upper_bound", number),
            referenced.get("bound_basis"),
            "range-evidence",
        )
        if evidence["status"] == "no-range-basis":
            evidence["reason"] = f"range-evidence-{referenced['status']}-without-bounds"
        return evidence
    setup = optional_text(row, "setup")
    return level_evidence(number(row, "level"), optional_flag(row, "overload"), limits.get(setup), setup)


def _reading(row: Row, plan: Row, limits: dict[str, tuple[float, float]], referenced: Row | None) -> Row:
    name = text(row, "reading")
    mode = text(row, "mode")
    if mode not in {"scheduled", "triggered"}:
        raise ValueError(f"unexpected mode: {mode!r}")
    band = _pair(row, "band_khz") if "band_khz" in row else (plan["low_khz"], plan["high_khz"])
    t0, t1 = _window(row, plan)
    if t0 >= t1:
        raise ValueError("reading time window must have positive duration")
    bin_khz = _coord(number(row, "bin_khz")) if "bin_khz" in row else None
    if mode == "scheduled" and bin_khz is None:
        raise ValueError("scheduled reading needs bin_khz")
    return {
        "reading": name,
        "mode": mode,
        "bin_khz": bin_khz,
        "time": (t0, t1),
        "band": band,
        "evidence": _evidence(row, limits, referenced) if mode == "scheduled" else None,
    }


def _clip(reading: Row, plan: Row) -> Row | None:
    t0, t1 = max(reading["time"][0], plan["start_s"]), min(reading["time"][1], plan["end_s"])
    f0, f1 = max(reading["band"][0], plan["low_khz"]), min(reading["band"][1], plan["high_khz"])
    if t0 >= t1 or f0 >= f1:
        return None
    return {**reading, "time": (t0, t1), "band": (f0, f1)}


def _covers(reading: Row, t0, t1, f0, f1) -> bool:
    return reading["time"][0] <= t0 and reading["time"][1] >= t1 and reading["band"][0] <= f0 and reading["band"][1] >= f1


def _cell_state(scheduled: list[Row], triggered: list[Row], threshold: float, required_bin_khz: float) -> Row:
    """按一个时频单元的覆盖证据判定状态，并保留可追溯的读数。"""
    trigger_names = sorted(item["reading"] for item in triggered)
    if not scheduled:
        if triggered:
            return {
                "status": "trigger-only",
                "trigger_readings": trigger_names,
                "reason": "triggered-backfill-does-not-replace-scheduled-samples",
            }
        return {
            "status": "no-scheduled-evidence",
            "trigger_readings": trigger_names,
            "reason": "no-scheduled-reading-covers-this-range",
        }

    fine = [item for item in scheduled if item["bin_khz"] <= required_bin_khz]
    coarse = [item for item in scheduled if item["bin_khz"] > required_bin_khz]
    if not fine:
        return {
            "status": "insufficient-resolution",
            "readings": sorted(item["reading"] for item in coarse),
            "resolution_khz": sorted({item["bin_khz"] for item in coarse}),
            "required_bin_khz": required_bin_khz,
            "trigger_readings": trigger_names,
            "reason": "coarse-sweep-cannot-prove-its-unresolved-subbands",
        }

    occupied = sorted(item["reading"] for item in fine if verdict(item["evidence"], threshold) == "occupied")
    idle = sorted(item["reading"] for item in fine if verdict(item["evidence"], threshold) == "not-occupied")
    coarse_names = sorted(item["reading"] for item in coarse)
    if occupied and idle:
        state = {
            "status": "conflict",
            "occupied_readings": occupied,
            "not_occupied_readings": idle,
            "trigger_readings": trigger_names,
            "reason": "occupied-and-not-occupied-evidence-overlap",
        }
    elif occupied:
        state = {
            "status": "occupied",
            "readings": occupied,
            "resolution_khz": sorted({item["bin_khz"] for item in fine}),
            "trigger_readings": trigger_names,
        }
    elif idle:
        state = {
            "status": "not-occupied",
            "readings": idle,
            "resolution_khz": sorted({item["bin_khz"] for item in fine}),
            "trigger_readings": trigger_names,
        }
    else:
        reasons = {item["reading"]: evidence_reason(item["evidence"], threshold) for item in fine}
        state = {
            "status": "inconclusive",
            "readings": sorted(reasons),
            "reasons": reasons,
            "trigger_readings": trigger_names,
            "reason": "no-reading-supports-a-definite-verdict",
        }
    if coarse_names:
        state["coarse_readings"] = coarse_names
    state["evidence"] = {
        item["reading"]: {
            "status": item["evidence"]["status"],
            "lower_bound": item["evidence"]["lower_bound"],
            "upper_bound": item["evidence"]["upper_bound"],
        }
        for item in fine
    }
    return state


def _signature(state: Row) -> tuple:
    """决定能否合并的稳定特征：状态、分辨率与缺测原因。

    读数清单不参与特征，合并时取并集，所以合并后的范围仍能追到每条读数。
    """
    fields = ("status", "resolution_khz", "required_bin_khz", "reason")
    signature = []
    for field in fields:
        if field in state:
            value = state[field]
            signature.append((field, tuple(value) if isinstance(value, list) else value))
    return tuple(signature)


def _merge_along(items: list[Row], axis: str) -> tuple[list[Row], bool]:
    """沿一个轴合并证据相同且相邻的矩形，读数取并集以便追溯。"""
    other = "band" if axis == "time" else "time"
    merged, changed = [], False
    for item in sorted(items, key=lambda row: (row[other], row[axis])):
        for existing in merged:
            if (
                existing["signature"] == item["signature"]
                and existing[other] == item[other]
                and existing[axis][1] == item[axis][0]
            ):
                existing[axis] = (existing[axis][0], item[axis][1])
                existing["area_khz_s"] += item["area_khz_s"]
                for field in (
                    "readings",
                    "occupied_readings",
                    "not_occupied_readings",
                    "trigger_readings",
                    "coarse_readings",
                ):
                    if field in existing or field in item:
                        existing[field] = sorted(set(existing.get(field, [])) | set(item.get(field, [])))
                if "reasons" in existing or "reasons" in item:
                    existing["reasons"] = {**item.get("reasons", {}), **existing.get("reasons", {})}
                if "evidence" in existing or "evidence" in item:
                    existing["evidence"] = {**item.get("evidence", {}), **existing.get("evidence", {})}
                changed = True
                break
        else:
            merged.append(dict(item))
    return merged, changed


def _merge_ranges(cells: list[Row]) -> list[Row]:
    """把状态与证据一致的相邻单元合并成矩形，不展开成逐时刻逐频点明细。"""
    items = []
    for cell in cells:
        items.append(
            {
                "time": cell["time"],
                "band": cell["band"],
                "area_khz_s": cell["area_khz_s"],
                "signature": cell["signature"],
                **{key: value for key, value in cell.items() if key not in {"time", "band", "area_khz_s", "signature"}},
            }
        )
    while True:
        items, by_time = _merge_along(items, "time")
        items, by_band = _merge_along(items, "band")
        if not (by_time or by_band):
            return items


def _public_range(item: Row) -> Row:
    result = {
        "time_s": [plain(value) for value in item["time"]],
        "band_khz": [plain(value) for value in item["band"]],
        "area_khz_s": plain(item["area_khz_s"]),
        "status": item["status"],
    }
    for field in (
        "readings",
        "occupied_readings",
        "not_occupied_readings",
        "coarse_readings",
        "resolution_khz",
        "required_bin_khz",
        "trigger_readings",
        "reasons",
        "reason",
    ):
        if field in item:
            result[field] = item[field]
    if "evidence" in item:
        result["evidence"] = item["evidence"]
    return result


def transform(row: Row) -> Row:
    """定时等间隔采样的时频占用上下界；触发采样只作解释线索。"""
    plan = _plan(row)
    threshold = number(row, "threshold")
    required_bin_khz = _coord(number(row, "required_bin_khz"))
    if required_bin_khz <= 0:
        raise ValueError("required_bin_khz must be positive")

    limits = read_limits(read_rows(row, "settings")) if "settings" in row else {}
    referenced = row.get("range_evidence", {})
    if not isinstance(referenced, dict):
        raise ValueError("range_evidence must be a JSON object")
    parsed = [
        _reading(item, plan, limits, referenced.get(text(item, "reading")))
        for item in index_rows(read_rows(row, "readings"), "reading").values()
    ]
    readings, outside = [], []
    for item in parsed:
        clipped = _clip(item, plan)
        (readings if clipped is not None else outside).append(clipped or item)
    scheduled = [item for item in readings if item["mode"] == "scheduled"]
    triggered = [item for item in readings if item["mode"] == "triggered"]

    time_edges = {plan["start_s"], plan["end_s"]}
    band_edges = {plan["low_khz"], plan["high_khz"]}
    for item in readings:
        time_edges.update(item["time"])
        band_edges.update(item["band"])

    times, bands = sorted(time_edges), sorted(band_edges)
    cells = []
    for t0, t1 in zip(times, times[1:]):
        for f0, f1 in zip(bands, bands[1:]):
            here_scheduled = [item for item in scheduled if _covers(item, t0, t1, f0, f1)]
            here_triggered = [item for item in triggered if _covers(item, t0, t1, f0, f1)]
            state = _cell_state(here_scheduled, here_triggered, threshold, required_bin_khz)
            cells.append(
                {
                    "time": (t0, t1),
                    "band": (f0, f1),
                    "area_khz_s": (t1 - t0) * (f1 - f0),
                    "signature": _signature(state),
                    **state,
                }
            )

    totals = {status: 0 for status in STATUSES}
    for cell in cells:
        totals[cell["status"]] += cell["area_khz_s"]
    planned = (plan["end_s"] - plan["start_s"]) * (plan["high_khz"] - plan["low_khz"])
    lower = totals["occupied"]
    upper = planned - totals["not-occupied"]
    return {
        "plan": plan,
        "planned_area_khz_s": plain(planned),
        "threshold": plain(threshold),
        "required_bin_khz": plain(required_bin_khz),
        "occupied_area_khz_s": {"lower": plain(lower), "upper": plain(upper)},
        "occupied_fraction": {"lower": lower / planned, "upper": upper / planned},
        "area_by_status_khz_s": {status: plain(value) for status, value in totals.items()},
        "ranges": [_public_range(item) for item in _merge_ranges(cells)],
        "trigger_readings": sorted(item["reading"] for item in triggered),
        "outside_plan_readings": sorted(item["reading"] for item in outside),
    }


def transform_slot_table(row: Row) -> Row:
    """旧版等间隔样本表：没有计划时频范围，只能给出计数比例。"""
    scheduled = {}
    triggered = []
    for name, item in index_rows(read_rows(row, "readings"), "reading").items():
        mode = text(item, "mode")
        if mode not in {"scheduled", "triggered"}:
            raise ValueError(f"unexpected mode: {mode!r}")
        active = item.get("occupied")
        if active is not None and type(active) is not bool:
            raise ValueError("occupied must be true or false")
        if mode == "triggered":
            if active:
                triggered.append(name)
            continue
        slot = number(item, "slot", minimum=0)
        slot = _coord(slot)
        if slot in scheduled:
            raise ValueError("duplicate scheduled sample for slot")
        scheduled[slot] = bool(active)
    occupied = sum(scheduled.values())
    return {
        "scheduled_count": len(scheduled),
        "occupied_count": occupied,
        "observed_fraction": occupied / len(scheduled) if scheduled else None,
        "triggered_activity": triggered,
    }


def transform_record(row: Row) -> Row:
    return transform(row) if "plan" in row else transform_slot_table(row)


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform_record)
