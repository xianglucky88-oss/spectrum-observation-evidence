from __future__ import annotations

from .contract import Row, apply_rows, flag, index_rows, number, read_rows


def transform(row: Row) -> Row:
    """以离线校验标记与对应读数区分通过、失败、无读数和未执行。"""
    result = {}
    threshold = number(row, "min_test_level")
    for station, check in index_rows(read_rows(row, "checks"), "station").items():
        if not flag(check, "performed"):
            result[station] = "not-run"
        elif check["test_level"] is None:
            result[station] = "no-evidence"
        else:
            result[station] = "pass" if number(check, "test_level") >= threshold else "fail"
    return {"station_checks": result}


def build_facts(data: Row) -> list[Row]:
    return apply_rows(data, transform)
