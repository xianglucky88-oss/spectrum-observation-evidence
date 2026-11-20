import json
from pathlib import Path
import unittest

from spectrum_observation_evidence import process

ROOT = Path(__file__).resolve().parent.parent


def occupancy(readings, *, plan=None, threshold=-50, required_bin_khz=5, settings=None, range_evidence=None):
    record = {
        "id": "occupancy-test",
        "plan": plan or {"start_s": 0, "end_s": 10, "low_khz": 1000, "high_khz": 1040, "interval_s": 5},
        "threshold": threshold,
        "required_bin_khz": required_bin_khz,
        "readings": readings,
    }
    if settings is not None:
        record["settings"] = settings
    if range_evidence is not None:
        record["range_evidence"] = range_evidence
    return process("scheduled-occupancy", {"records": [record]})[0]


def sample(name, *, slot, low, high, bin_khz=5, setup="narrow", level=-60, mode="scheduled", **extra):
    reading = {
        "reading": name,
        "mode": mode,
        "slot": slot,
        "band_khz": [low, high],
        "bin_khz": bin_khz,
        "setup": setup,
        "level": level,
    }
    reading.update(extra)
    return reading


NARROW = [{"setup": "narrow", "floor": -115, "ceiling": -40}]


class ReceiverRangeTests(unittest.TestCase):
    def test_clipped_reading_keeps_only_ceiling_lower_bound(self):
        source = json.loads((ROOT / "examples" / "receiver-range.json").read_text(encoding="utf-8"))
        observations = process("receiver-range", source)[0]["observations"]
        self.assertEqual(observations["b"]["status"], "clipped")
        self.assertIsNone(observations["b"]["comparable_level"])
        self.assertEqual(observations["b"]["lower_bound"], -40)
        self.assertIsNone(observations["b"]["upper_bound"])
        self.assertEqual(observations["b"]["bound_basis"]["kind"], "ceiling")

    def test_below_range_reading_keeps_only_floor_upper_bound(self):
        source = json.loads((ROOT / "examples" / "receiver-range.json").read_text(encoding="utf-8"))
        observations = process("receiver-range", source)[0]["observations"]
        self.assertEqual(observations["c"]["status"], "below-range")
        self.assertIsNone(observations["c"]["lower_bound"])
        self.assertEqual(observations["c"]["upper_bound"], -90)

    def test_missing_same_scale_range_does_not_invent_bounds(self):
        source = json.loads((ROOT / "examples" / "receiver-range.json").read_text(encoding="utf-8"))
        observations = process("receiver-range", source)[0]["observations"]
        self.assertEqual(observations["e"]["status"], "no-range-basis")
        self.assertIsNone(observations["e"]["lower_bound"])
        self.assertIsNone(observations["e"]["upper_bound"])
        self.assertIsNone(observations["e"]["bound_basis"])

    def test_overload_flag_clips_even_below_ceiling(self):
        source = json.loads((ROOT / "examples" / "receiver-range.json").read_text(encoding="utf-8"))
        observations = process("receiver-range", source)[0]["observations"]
        self.assertEqual(observations["d"]["status"], "clipped")
        self.assertEqual(observations["d"]["lower_bound"], -40)


class OccupancyBoundTests(unittest.TestCase):
    def test_clipped_lower_bound_above_threshold_is_definite_occupancy(self):
        fact = occupancy(
            [sample("a", slot=0, low=1000, high=1040, level=-30)],
            settings=NARROW,
        )
        self.assertEqual(fact["area_by_status_khz_s"]["occupied"], 200)
        self.assertEqual(fact["ranges"][0]["status"], "occupied")

    def test_clipped_lower_bound_at_threshold_is_not_definite_occupancy(self):
        fact = occupancy(
            [sample("a", slot=0, low=1000, high=1040, level=-50)],
            settings=[{"setup": "narrow", "floor": -115, "ceiling": -50}],
            threshold=-50,
        )
        self.assertEqual(fact["area_by_status_khz_s"]["occupied"], 0)
        self.assertEqual(fact["ranges"][0]["status"], "inconclusive")
        self.assertEqual(fact["ranges"][0]["reasons"], {"a": "threshold-between-bounds"})

    def test_below_range_upper_bound_at_threshold_is_definite_idle(self):
        fact = occupancy(
            [sample("a", slot=0, low=1000, high=1040, level=-120)],
            settings=NARROW,
            threshold=-115,
        )
        self.assertEqual(fact["ranges"][0]["status"], "not-occupied")
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 0, "upper": 200})

    def test_unknown_range_basis_is_not_counted_as_idle(self):
        fact = occupancy([sample("a", slot=0, low=1000, high=1040, setup="unlisted")], settings=NARROW)
        self.assertEqual(fact["ranges"][0]["status"], "inconclusive")
        self.assertEqual(fact["ranges"][0]["reasons"], {"a": "setup-has-no-same-scale-range"})
        self.assertEqual(fact["area_by_status_khz_s"]["not-occupied"], 0)
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 0, "upper": 400})

    def test_trigger_only_range_is_not_idle_but_records_trigger(self):
        fact = occupancy([sample("t", slot=0, low=1000, high=1040, mode="triggered")], settings=NARROW)
        self.assertEqual(fact["ranges"][0]["status"], "trigger-only")
        self.assertEqual(fact["ranges"][0]["trigger_readings"], ["t"])
        self.assertEqual(fact["area_by_status_khz_s"]["not-occupied"], 0)
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 0, "upper": 400})

    def test_missing_scheduled_range_is_not_idle(self):
        fact = occupancy([], settings=NARROW)
        self.assertEqual(fact["ranges"][0]["status"], "no-scheduled-evidence")
        self.assertEqual(fact["area_by_status_khz_s"]["not-occupied"], 0)
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 0, "upper": 400})

    def test_coarse_sweep_cannot_prove_unresolved_subbands(self):
        fact = occupancy(
            [sample("coarse", slot=0, low=1000, high=1040, bin_khz=20, level=-30)],
            settings=NARROW,
            required_bin_khz=5,
        )
        self.assertEqual(fact["ranges"][0]["status"], "insufficient-resolution")
        self.assertEqual(fact["ranges"][0]["resolution_khz"], [20])
        self.assertEqual(fact["ranges"][0]["required_bin_khz"], 5)
        self.assertEqual(fact["area_by_status_khz_s"]["occupied"], 0)
        self.assertEqual(fact["area_by_status_khz_s"]["not-occupied"], 0)

    def test_overlap_is_counted_once_in_denominator_and_evidence(self):
        fact = occupancy(
            [
                sample("a", slot=0, low=1000, high=1020, level=-30),
                sample("b", slot=0, low=1010, high=1030, level=-30),
            ],
            settings=NARROW,
        )
        self.assertEqual(fact["planned_area_khz_s"], 400)
        self.assertEqual(sum(fact["area_by_status_khz_s"].values()), 400)
        self.assertEqual(fact["area_by_status_khz_s"]["occupied"], 150)
        self.assertEqual(fact["area_by_status_khz_s"]["no-scheduled-evidence"], 250)

    def test_conflicting_evidence_is_retained_as_uncertainty(self):
        fact = occupancy(
            [
                sample("busy", slot=0, low=1000, high=1040, level=-30),
                sample("quiet", slot=0, low=1000, high=1040, level=-80),
            ],
            settings=NARROW,
        )
        self.assertEqual(fact["ranges"][0]["status"], "conflict")
        self.assertEqual(fact["ranges"][0]["occupied_readings"], ["busy"])
        self.assertEqual(fact["ranges"][0]["not_occupied_readings"], ["quiet"])
        self.assertEqual(fact["area_by_status_khz_s"]["conflict"], 200)
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 0, "upper": 400})

    def test_lower_bound_counts_only_consistent_occupancy_and_upper_deducts_idle(self):
        fact = occupancy(
            [
                sample("busy", slot=0, low=1000, high=1020, level=-30),
                sample("quiet", slot=0, low=1020, high=1040, level=-80),
                sample("doubt", slot=1, low=1000, high=1020, setup="wide", level=-30),
                sample("coarse", slot=1, low=1020, high=1040, bin_khz=20, level=-30),
            ],
            settings=[{"setup": "narrow", "floor": -115, "ceiling": -40}, {"setup": "wide", "floor": -115, "ceiling": -50}],
            threshold=-50,
        )
        self.assertEqual(fact["area_by_status_khz_s"]["occupied"], 100)
        self.assertEqual(fact["area_by_status_khz_s"]["not-occupied"], 100)
        self.assertEqual(fact["area_by_status_khz_s"]["inconclusive"], 100)
        self.assertEqual(fact["area_by_status_khz_s"]["insufficient-resolution"], 100)
        self.assertEqual(fact["occupied_area_khz_s"], {"lower": 100, "upper": 300})
        self.assertEqual(fact["occupied_fraction"], {"lower": 0.25, "upper": 0.75})

    def test_referenced_range_evidence_is_used_for_readings(self):
        fact = occupancy(
            [sample("a", slot=0, low=1000, high=1040)],
            range_evidence={
                "a": {"status": "clipped", "comparable_level": None, "lower_bound": -40, "upper_bound": None}
            },
        )
        self.assertEqual(fact["ranges"][0]["status"], "occupied")

    def test_ranges_are_rectangles_not_per_cell_details(self):
        readings = [sample(f"r{slot}", slot=slot, low=1000, high=1040, level=-80) for slot in range(4)]
        fact = occupancy(readings, settings=NARROW, plan={"start_s": 0, "end_s": 20, "low_khz": 1000, "high_khz": 1040, "interval_s": 5})
        self.assertEqual(len(fact["ranges"]), 1)
        self.assertEqual(fact["ranges"][0]["time_s"], [0, 20])
        self.assertEqual(fact["ranges"][0]["band_khz"], [1000, 1040])


class SweepCoverageTests(unittest.TestCase):
    def test_coarse_sweep_is_still_traceable_and_not_fine(self):
        source = json.loads((ROOT / "examples" / "sweep-coverage.json").read_text(encoding="utf-8"))
        bands = process("sweep-coverage", source)[0]["bands"]
        coarse = bands[0]
        self.assertEqual(coarse["coverage"], "coarse")
        self.assertEqual(coarse["sweeps"], ["A"])
        self.assertEqual(coarse["coarse_sweeps"], ["A"])
        self.assertEqual(coarse["fine_sweeps"], [])
        self.assertEqual(coarse["resolution_khz"], [20])

    def test_missing_band_is_distinct_from_coarse(self):
        source = json.loads((ROOT / "examples" / "sweep-coverage.json").read_text(encoding="utf-8"))
        bands = process("sweep-coverage", source)[0]["bands"]
        self.assertEqual(bands[-1]["coverage"], "missing")
        self.assertEqual(bands[-1]["sweeps"], [])
        self.assertEqual(bands[-1]["resolution_khz"], [])


if __name__ == "__main__":
    unittest.main()
