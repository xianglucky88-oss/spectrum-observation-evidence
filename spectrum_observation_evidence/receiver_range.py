from __future__ import annotations

from .contract import Row, apply_rows, index_rows, number, optional_flag, read_rows, text
from .evidence import level_evidence, read_limits


def transform(row: Row) -> Row:
    """按接收设置核对同标度读数：保留可比较测值或有依据的单侧界限。

    截顶读数不能当作精确值，只留下量程上限给出的下界；低于有效量程的读数只
    留下量程下限给出的上界；没有同标度量程依据的读数不推测界限。
    """
    limits = read_limits(read_rows(row, "settings"))
    observations = {}
    for reading, item in index_rows(read_rows(row, "samples"), "reading").items():
        setup = text(item, "setup")
        level = number(item, "level")
        overload = optional_flag(item, "overload")
        evidence = level_evidence(level, overload, limits.get(setup), setup)
        observations[reading] = {
            "setup": setup,
            "status": evidence["status"],
            "comparable_level": evidence["comparable_level"],
            "lower_bound": evidence["lower_bound"],
            "upper_bound": evidence["upper_bound"],
            "bound_basis": evidence["bound_basis"],
            "reason": evidence["reason"],
        }
    return {"observations": observations}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
