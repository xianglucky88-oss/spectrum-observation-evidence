"""把单条电平读数换算成可比较的测值或有依据的单侧界限。

接收机量程（``floor``/``ceiling``）是唯一允许用来推断界限的依据：只有同标度的
``setup`` 才有可用的量程。没有量程依据时保留空界限，不做猜测。
"""

from __future__ import annotations

from .contract import Row, number, text

Limits = tuple[float, float]


def _num(value: float | None) -> int | float | None:
    """整数值以整数输出，便于人工核对，不改变数值本身。"""
    if value is None:
        return None
    return int(value) if float(value).is_integer() else value


def read_limits(rows: list[Row]) -> dict[str, Limits]:
    """读取 ``[{setup, floor, ceiling}]``，按设置名建立量程索引。"""
    result: dict[str, Limits] = {}
    for item in rows:
        setup = text(item, "setup")
        if setup in result:
            raise ValueError(f"duplicate setup: {setup}")
        floor, ceiling = number(item, "floor"), number(item, "ceiling")
        if floor >= ceiling:
            raise ValueError(f"invalid receiver range for setup {setup!r}")
        result[setup] = (floor, ceiling)
    return result


def _basis(kind: str, setup: str, limits: Limits) -> Row:
    floor, ceiling = limits
    return {"kind": kind, "setup": setup, "floor": _num(floor), "ceiling": _num(ceiling)}


def _unknown(reason: str, setup: str | None = None) -> Row:
    return {
        "status": "no-range-basis",
        "comparable_level": None,
        "lower_bound": None,
        "upper_bound": None,
        "exact": False,
        "bound_basis": None,
        "reason": reason,
        "setup": setup,
    }


def level_evidence(
    level: float,
    overload: bool,
    limits: Limits | None,
    setup: str | None = None,
) -> Row:
    """按量程为一条电平读数给出证据。

    - 量程内：精确可比较测值，上下界都等于读数。
    - 截顶（过载或读数达到上限）：不是精确值，只保留量程给出的下界。
    - 低于量程：不是精确值，只保留量程给出的上界。
    - 没有同标度量程依据：不给任何界限。
    """
    if limits is None:
        return _unknown("setup-has-no-same-scale-range", setup)
    floor, ceiling = limits
    if overload or level >= ceiling:
        return {
            "status": "clipped",
            "comparable_level": None,
            "lower_bound": _num(ceiling),
            "upper_bound": None,
            "exact": False,
            "bound_basis": _basis("ceiling", setup or "", limits),
            "reason": "reading-at-or-above-ceiling",
            "setup": setup,
        }
    if level < floor:
        return {
            "status": "below-range",
            "comparable_level": None,
            "lower_bound": None,
            "upper_bound": _num(floor),
            "exact": False,
            "bound_basis": _basis("floor", setup or "", limits),
            "reason": "reading-below-floor",
            "setup": setup,
        }
    return {
        "status": "usable",
        "comparable_level": _num(level),
        "lower_bound": _num(level),
        "upper_bound": _num(level),
        "exact": True,
        "bound_basis": _basis("measured", setup or "", limits),
        "reason": "within-range",
        "setup": setup,
    }


def explicit_evidence(
    lower: float | None,
    upper: float | None,
    basis: Row | None = None,
    reason: str = "reported-bounds",
) -> Row:
    """采纳已经算好的界限（例如离线量程核查事实里的界限）。"""
    if basis is not None and not isinstance(basis, dict):
        raise ValueError("bound_basis must be a JSON object")
    if lower is not None and upper is not None and lower > upper:
        raise ValueError("lower bound must not exceed upper bound")
    exact = lower is not None and upper is not None and lower == upper
    if lower is None and upper is None:
        return _unknown(reason)
    return {
        "status": "reported" if exact else "bounded",
        "comparable_level": _num(lower) if exact else None,
        "lower_bound": _num(lower),
        "upper_bound": _num(upper),
        "exact": exact,
        "bound_basis": basis,
        "reason": reason,
        "setup": (basis or {}).get("setup"),
    }


def verdict(evidence: Row, threshold: float) -> str:
    """只在界限足以判定时给出 ``occupied``/``not-occupied``。

    下界必须严格超过门槛才能肯定占用；上界不超过门槛才能肯定未占用。
    两个条件都不满足时保留 ``unknown``。
    """
    lower, upper = evidence["lower_bound"], evidence["upper_bound"]
    if lower is not None and lower > threshold:
        return "occupied"
    if upper is not None and upper <= threshold:
        return "not-occupied"
    return "unknown"


def evidence_reason(evidence: Row, threshold: float | None) -> str:
    """给无法判定的读数一个人可核对的理由。"""
    if threshold is None:
        return "threshold-not-provided"
    if evidence["status"] == "no-range-basis":
        return evidence.get("reason") or "no-range-basis"
    if evidence["lower_bound"] is None and evidence["upper_bound"] is None:
        return "no-level-evidence"
    return "threshold-between-bounds"
