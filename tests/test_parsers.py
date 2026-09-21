"""2026-09-21 に取得した実ページの切り抜きで、解析が壊れていないことを確かめる。

    python -m unittest discover -s tests
"""
import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from collector import pagasa_dams, pagasa_regional, pagasa_tcb, phivolcs_eq, phivolcs_volcano
from collector.store import append_jsonl, upsert_csv

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8", errors="replace")


class Earthquakes(unittest.TestCase):
    def test_rows(self):
        rows = phivolcs_eq.parse(load("phivolcs_eq.html"))
        self.assertEqual(len(rows), 25)
        first = rows[0]
        self.assertEqual(first["event_id"], "2026_0921_0058")
        self.assertEqual(first["datetime_pht"], "2026-09-21T08:58:00+08:00")
        self.assertEqual((first["lat"], first["lon"], first["depth_km"], first["mag"]), ("6.51", "124.07", "1.0", "1.8"))
        self.assertIn("Kalamansig (Sultan Kudarat)", first["location"])
        self.assertTrue(first["bulletin"].startswith("2026_Earthquake_Information/September/"))
        self.assertTrue(all(r["mag"] and r["lat"] for r in rows))


class Dams(unittest.TestCase):
    def test_current_and_previous(self):
        dams, watch = pagasa_dams.parse(load("pagasa_flood.html"), date(2026, 9, 21))
        angat = {d["obs_date"]: d for d in dams if d["dam"] == "Angat"}
        self.assertEqual(angat["2026-09-21"]["rwl_m"], "208.23")
        self.assertEqual(angat["2026-09-21"]["dev_24h_m"], "-0.06")
        self.assertEqual(angat["2026-09-21"]["nhwl_m"], "210.00")
        self.assertEqual(angat["2026-09-20"]["rwl_m"], "208.29")
        self.assertGreaterEqual(len({d["dam"] for d in dams}), 9)
        amb = next(d for d in dams if d["dam"] == "Ambuklao" and d["obs_date"] == "2026-09-21")
        self.assertEqual((amb["gates"], amb["gate_opening_m"]), ("1", "0.30"))
        self.assertIn({"date_pht": "2026-09-21", "sub_basin": "Ambuklao-Binga-San Roque Sub-basin", "status": "Flood Watch"}, watch)

    def test_year_boundary(self):
        self.assertEqual(pagasa_dams._obs_date("Dec-31", date(2027, 1, 1)), "2026-12-31")


class Regional(unittest.TestCase):
    def test_thunderstorm_only(self):
        items = pagasa_regional.parse(load("pagasa_regional_ncr.html"), "ncrprsd")
        self.assertEqual(len(items), 1)  # 「豪雨警報なし」の文は拾わない
        it = items[0]
        self.assertEqual((it["kind"], it["number"], it["issued_at"]), ("thunderstorm", "14", "2026-09-21T09:34:00+08:00"))
        self.assertIn("Bulacan (Meycauayan, Marilao, and Obando)", it["text"])


class Cyclone(unittest.TestCase):
    def test_none_active(self):
        self.assertIsNone(pagasa_tcb.parse(load("pagasa_tcb_none.html")))


class Volcano(unittest.TestCase):
    def test_levels(self):
        rows = phivolcs_volcano.parse(load("phivolcs_volcano.html"), date(2026, 9, 21))
        self.assertEqual({r["volcano"]: r["alert_level"] for r in rows}, {"Taal": "1", "Kanlaon": "2", "Bulusan": "1", "Pinatubo": "0", "Mayon": "2"})


class Store(unittest.TestCase):
    def test_upsert_and_dedupe(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "a.csv"
            rows = [{"k": "1", "v": "a"}, {"k": "2", "v": "b"}]
            self.assertEqual(upsert_csv(p, ["k", "v"], rows, ["k"], ["k"]), 2)
            self.assertEqual(upsert_csv(p, ["k", "v"], rows, ["k"], ["k"]), 0)
            self.assertEqual(upsert_csv(p, ["k", "v"], [{"k": "1", "v": "z"}], ["k"], ["k"]), 1)
            self.assertEqual([r["v"] for r in csv.DictReader(p.read_text().splitlines())], ["z", "b"])
            j = Path(tmp) / "b.jsonl"
            self.assertEqual(append_jsonl(j, [{"id": "x"}, {"id": "y"}], "id"), 2)
            self.assertEqual(append_jsonl(j, [{"id": "y"}, {"id": "z"}], "id"), 1)


if __name__ == "__main__":
    unittest.main()
