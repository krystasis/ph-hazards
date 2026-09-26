"""市町ごとの地震の頻度(50 km 圏)。"""
import json
import unittest
from datetime import date

from db import rates


def ev(at, lat, lon, mag):
    return {"occurred_at": at, "lat": str(lat), "lon": str(lon), "mag": str(mag)}


class Rates(unittest.TestCase):
    def test_counts_only_m3_since_2019_within_50km(self):
        # General Luna (Surigao del Norte) 9.7833N 126.15E の近くに置く
        evs = [
            ev("2018-06-01T00:00:00+08:00", 9.8, 126.2, 4.5),   # 期間外
            ev("2020-06-01T00:00:00+08:00", 9.8, 126.2, 2.9),   # M3 未満
            ev("2020-06-01T00:00:00+08:00", 9.8, 126.2, 4.1),
            ev("2024-01-01T00:00:00+08:00", 9.9, 126.3, 5.2),
            ev("2024-01-01T00:00:00+08:00", 9.8, 127.5, 6.0),   # 約 150 km 東 → 圏外
        ]
        rows = {r["city_code"]: r for r in rates.city_rates(evs, today=date(2026, 9, 26))}
        gl = next(r for r in rows.values() if r["city_code"] == "1606710000")
        self.assertEqual((gl["n_m3"], gl["n_m4"], gl["n_m5"]), ("2", "2", "1"))
        self.assertEqual(gl["last_m5_at"], "2024-01-01T00:00:00+08:00")
        self.assertEqual(json.loads(gl["m4_by_year"])["2024"], 1)
        self.assertEqual(gl["since"], "2019-01-01")
        self.assertAlmostEqual(float(gl["years"]), 7.73, places=1)
        # 年率 2/7.73 → 30 日以内の確率 = 1 − exp(−0.259 × 30 / 365.25) ≈ 2.1%
        self.assertAlmostEqual(float(gl["p30_m4"]), 0.021, places=3)

    def test_quiet_town_has_zero_rate(self):
        rows = rates.city_rates([ev("2020-06-01T00:00:00+08:00", 9.8, 126.2, 4.1)], today=date(2026, 9, 26))
        marikina = next(r for r in rows if r["city_code"] == "1380700000")
        self.assertEqual((marikina["n_m4"], marikina["p30_m4"], marikina["last_m4_at"]), ("0", "0.0000", ""))


if __name__ == "__main__":
    unittest.main()
