"""频谱观测与覆盖统计"""

from . import sweep_coverage, scheduled_occupancy, site_check, event_windows, receiver_range
from .contract import Row

PIPELINES = {
    "sweep-coverage": sweep_coverage.build_facts,
    "scheduled-occupancy": scheduled_occupancy.build_facts,
    "site-check": site_check.build_facts,
    "event-windows": event_windows.build_facts,
    "receiver-range": receiver_range.build_facts,
}

def process(pipeline: str, data: Row) -> list[Row]:
    """Validate and transform an independent input dataset into keyed facts."""
    if pipeline not in PIPELINES:
        raise ValueError(f"unknown pipeline: {pipeline}")
    if not isinstance(data, dict):
        raise ValueError("input must be a JSON object")
    return PIPELINES[pipeline](data)
