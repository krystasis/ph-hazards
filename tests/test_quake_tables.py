"""サイト用の小さな集計表(city_quake_years / bands / months、daily_quake_counts)と regional_outlook の書き出し。

地震は 2026-09-21 の実ページ(tests/fixtures/phivolcs_eq.html)、週間予報は 2026-09-26 の実ページの切り抜きから作る。
"""
import csv
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from collector import phivolcs_eq, run
from db.export import COLUMNS, MONTHS_KEPT, build, diff, plan, quake_aggregates

FIX = Path(__file__).parent / "fixtures"


def _data(d: Path) -> Path:
    data = d / "data"
    rows = phivolcs_eq.parse((FIX / "phivolcs_eq.html").read_text(encoding="utf-8", errors="replace"))
    (data / "earthquakes").mkdir(parents=True)
    with (data / "earthquakes" / "2026-09.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=phivolcs_eq.FIELDS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    now = datetime(2026, 9, 26, 1, 7, tzinfo=timezone.utc)
    with mock.patch.object(run, "DATA", data):
        for region in ("ncrprsd", "nlprsd", "slprsd", "visprsd", "minprsd"):
            run.save_outlook((FIX / f"pagasa_outlook_{region}.html").read_text(encoding="utf-8"), region, now)
    return data


def _eq(eid, at, mag, city="1380700000"):
    return {"event_id": eid, "occurred_at": at, "mag": str(mag), "city_code": city, "row_hash": f"{eid}{at}{mag}{city}"}


class RealFixture(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.t = build(_data(Path(cls.tmp.name)), Path(cls.tmp.name) / "state")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_outlook_rows(self):
        o = self.t["regional_outlook"]
        self.assertEqual(len(o), 25)   # 5 地域 × 5 日
        row = o[("ncrprsd", "2026-09-26T09:00:00+08:00", "2")]
        self.assertEqual((row["day_name"], row["tmin"], row["tmax"], row["direction"], row["coastal"]),
                         ("Monday", "26", "34", "southwest becoming southeast", "Slight to moderate"))

    def test_province_outlook_rows(self):
        from db.export import outlook_place
        o = self.t["province_outlook"]
        self.assertEqual(len(o), 86 * 5)   # 87 州のうち「Metro Davao」だけ当たらない
        self.assertEqual(outlook_place("Metro Davao, Davao Region"), "")
        benguet = o[("1401100000", "2026-09-26T09:00:00+08:00", "0")]
        self.assertEqual((benguet["day_name"], benguet["tmin"], benguet["tmax"], benguet["direction"]),
                         ("Saturday", "16", "25", "Southwest"))
        self.assertIn(("1300000000", "2026-09-26T09:00:00+08:00", "4"), o)            # Metro Manila → NCR の地域コード
        self.assertEqual(outlook_place("Isabela City, Zamboanga Peninsula"), "0990101000")   # 市自身のコード(州の Isabela ではない)
        self.assertEqual(outlook_place("Isabela"), "0203100000")
        self.assertEqual(outlook_place("Zamboanga City, Zamboanga Peninsula"), "0931700000")
        # 既定の州の行は、静的な欄(regional_outlook)と同じ値
        for i in range(5):
            r, p = self.t["regional_outlook"][("nlprsd", "2026-09-26T09:00:00+08:00", str(i))], o[("0102800000", "2026-09-26T09:00:00+08:00", str(i))]
            self.assertEqual({k: r[k] for k in ("day_name", "tmin", "tmax", "direction")}, {k: p[k] for k in ("day_name", "tmin", "tmax", "direction")})

    def test_same_set_as_city_quake_stats(self):
        stats = self.t["city_quake_stats"]
        self.assertEqual(set(self.t["city_quake_bands"]), set(stats))
        for (code,), s in stats.items():
            years = [r for (c, _), r in self.t["city_quake_years"].items() if c == code]
            self.assertEqual(sum(int(r["n"]) for r in years), int(s["total"]))
            self.assertEqual(sum(int(r["n_m4"]) for r in years), int(s["m4_plus"]))
            b = self.t["city_quake_bands"][(code,)]
            self.assertEqual(sum(int(b[k]) for k in ("lt3", "m3", "m4", "m5")), int(s["total"]))
            self.assertEqual(int(b["m4"]) + int(b["m5"]), int(s["m4_plus"]))
            # 全部が 30 日の窓の中(1 日ぶんのページ)
            self.assertEqual(int(b["latest_30d"]), int(s["total"]))
            self.assertEqual(float(b["latest_30d_max"]), float(s["max_mag"]))

    def test_daily_counts_cover_every_day(self):
        days = self.t["daily_quake_counts"]
        eq = self.t["earthquakes"].values()
        self.assertEqual(sum(int(r["n"]) for r in days.values()), len(eq))
        self.assertEqual(sum(int(r["n_m4"]) for r in days.values()), sum(float(r["mag"]) >= 4 for r in eq))
        keys = sorted(k for (k,) in days)
        self.assertEqual(keys[0], min(r["occurred_at"] for r in eq)[:10])   # PHT の日付(+08:00 の先頭)

    def test_units_and_second_run(self):
        units = {u.key: u for u in plan(self.t, {})}
        for name in ("regional_outlook", "province_outlook", "city_quake_years", "city_quake_bands", "city_quake_months", "daily_quake_counts"):
            self.assertGreater(units[name].rows, 0, name)
        _, manifest, _ = diff(self.t, {})
        self.assertEqual([u.key for u in plan(self.t, manifest) if u.statements], [])


class Windows(unittest.TestCase):
    def _t(self, events):
        t = {n: {} for n in COLUMNS}
        for e in events:
            t["earthquakes"][(e["event_id"],)] = e
        t["_months_since"] = quake_aggregates(t)
        return t

    def test_bands_and_30_days_to_newest_event(self):
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 4.2), _eq("b", "2026-08-28T09:00:00+08:00", 2.1),
                     _eq("c", "2026-08-26T09:00:00+08:00", 5.6), _eq("d", "2019-01-01T00:30:00+08:00", 3.0)])
        b = t["city_quake_bands"][("1380700000",)]
        self.assertEqual((b["lt3"], b["m3"], b["m4"], b["m5"]), ("1", "1", "1", "1"))
        self.assertEqual((b["latest_30d"], b["latest_30d_max"]), ("2", "4.2"))   # c は 31 日前で窓の外
        self.assertEqual(t["city_quake_years"][("1380700000", "2019")], {"city_code": "1380700000", "year": "2019", "n": "1", "n_m4": "0"})

    def test_quiet_30_days_is_null(self):
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 4.2, city=""), _eq("b", "2026-01-01T00:00:00+08:00", 3.3)])
        b = t["city_quake_bands"][("1380700000",)]
        self.assertEqual((b["latest_30d"], b["latest_30d_max"]), ("0", ""))

    def test_months_window_and_zero_days(self):
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 3), _eq("b", "2024-10-31T23:59:00+08:00", 3),
                     _eq("c", "2024-09-30T23:59:00+08:00", 3)])
        self.assertEqual(MONTHS_KEPT, 24)
        self.assertEqual(t["_months_since"], "2024-10")
        self.assertEqual(sorted(m for (_, m) in t["city_quake_months"]), ["2024-10", "2026-09"])  # 0 件の月は行が無い
        days = t["daily_quake_counts"]
        self.assertEqual(len(days), (datetime(2026, 9, 26) - datetime(2024, 9, 30)).days + 1)
        self.assertEqual(days[("2025-06-01",)], {"day": "2025-06-01", "n": "0", "n_m4": "0"})

    def test_window_move_deletes_old_months_once(self):
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 3), _eq("b", "2024-10-02T00:00:00+08:00", 3)])
        _, manifest, _ = diff(t, {})
        # 1 か月進む: 2024-10 が窓から出る
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 3), _eq("b", "2024-10-02T00:00:00+08:00", 3),
                     _eq("n", "2026-10-01T08:00:00+08:00", 3)])
        u = next(u for u in plan(t, manifest) if u.key == "city_quake_months")
        self.assertEqual(u.statements[0], "DELETE FROM city_quake_months WHERE month < '2024-11';")
        self.assertEqual(sum(s.startswith("DELETE") for s in u.statements), 1)   # 窓の外の行を鍵で重ねて消さない
        _, manifest, _ = diff(t, manifest)
        u = next(u for u in plan(t, manifest) if u.key == "city_quake_months")
        self.assertEqual(u.statements, [])   # 窓が動かない回は DELETE を送らない

    def test_gone_rows_are_deleted_by_key(self):
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 3), _eq("b", "2025-01-01T10:00:00+08:00", 3, city="0102801000")])
        _, manifest, _ = diff(t, {})
        # b の基準点が付け替わって、0102801000 の行が無くなった
        t = self._t([_eq("a", "2026-09-26T10:00:00+08:00", 3), _eq("b", "2025-01-01T10:00:00+08:00", 3)])
        units = {u.key: u for u in plan(t, manifest)}
        self.assertIn("DELETE FROM city_quake_years WHERE (city_code = '0102801000' AND year = 2025);", units["city_quake_years"].statements)
        self.assertIn("DELETE FROM city_quake_bands WHERE (city_code = '0102801000');", units["city_quake_bands"].statements)
        self.assertIn("DELETE FROM city_quake_months WHERE (city_code = '0102801000' AND month = '2025-01');", units["city_quake_months"].statements)


if __name__ == "__main__":
    unittest.main()
