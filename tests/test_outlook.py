"""週間予報(Extended Weather Outlook)。2026-09-26 に 5 地域のページを 1 回ずつ取った切り抜きで確かめる。"""
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from collector import pagasa_regional as R
from collector import run

FIX = Path(__file__).parent / "fixtures"


def page(region: str) -> str:
    return (FIX / f"pagasa_outlook_{region}.html").read_text(encoding="utf-8")


class Parse(unittest.TestCase):
    def test_five_regions(self):
        # 静的な欄は各 PRSD の既定の州 1 つぶん
        want = {"ncrprsd": ("Metro Manila", 12), "nlprsd": ("Ilocos Norte", 16), "slprsd": ("Albay", 10),
                "visprsd": ("Cebu", 17), "minprsd": ("Zamboanga City, Zamboanga Peninsula", 32)}
        for region, (province, n) in want.items():
            o = R.parse_outlook(page(region), region)
            self.assertEqual(o["id"], f"{region}:2026-09-26T09:00:00+08:00")
            self.assertEqual(o["issued_at"], "2026-09-26T09:00:00+08:00")
            self.assertEqual([d["name"] for d in o["days"]], ["Saturday", "Sunday", "Monday", "Tuesday", "Wednesday"])
            self.assertEqual([d["day_index"] for d in o["days"]], [0, 1, 2, 3, 4])
            self.assertTrue(all(isinstance(d["tmin"], int) and isinstance(d["tmax"], int) for d in o["days"]))
            self.assertEqual((o["province"], len(o["provinces"])), (province, n))

    def test_ncr_values_as_written(self):
        o = R.parse_outlook(page("ncrprsd"), "ncrprsd")
        sat, mon = o["days"][0], o["days"][2]
        self.assertEqual((sat["tmin"], sat["tmax"], sat["wind"], sat["direction"], sat["coastal"]),
                         (25, 33, "Light to moderate", "southwest", "Slight to moderate"))
        self.assertEqual((mon["tmin"], mon["tmax"], mon["direction"]), (26, 34, "southwest becoming southeast"))
        self.assertTrue(sat["sky"].startswith("Partly cloudy"))

    def test_html_block_is_the_default_province(self):
        # 静的な欄 = 既定の州の outlook[1:](先頭は 24 時間予報)。Benguet は同じ PRSD でも別の値。
        o = R.parse_outlook(page("nlprsd"), "nlprsd")
        il = o["provinces"][o["province_psgc"]]["days"]
        self.assertEqual([[d["tmin"], d["tmax"]] for d in o["days"]], [x[:2] for x in il[:5]])
        benguet = next(p for p in o["provinces"].values() if p["name"] == "Benguet")
        self.assertEqual(benguet["days"][0][:2], [16, 25])
        self.assertEqual(dict(zip(R.PROVINCE_DAY, benguet["days"][0]))["direction"], "Southwest")

    def test_issued_at_spacing(self):
        for text, want in [
            ("Issued at: 09:00 AM, 26 September, 2026", "2026-09-26T09:00:00+08:00"),
            ("Issued at:9:00 PM 26 September 2026", "2026-09-26T21:00:00+08:00"),
            ("Issued at :  12:30 PM ,  1 October , 2026", "2026-10-01T12:30:00+08:00"),
            ("Issued at: 11:00 AM, September 26, 2026", "2026-09-26T11:00:00+08:00"),
            ("Issued at: 5:00 AM, 26 Sept 2026", "2026-09-26T05:00:00+08:00"),
            ("Issued at: 12:00 AM, 26 September, 2026", "2026-09-26T00:00:00+08:00"),
            ("Issued at: 09:00 AM, 31 September, 2026", ""),
            ("Issued at: soon", ""),
        ]:
            self.assertEqual(R.outlook_issued_iso(text), want, text)

    def test_missing_or_broken_block(self):
        self.assertIsNone(R.parse_outlook("<html><body>no outlook</body></html>", "ncrprsd"))
        broken = page("ncrprsd").replace("Issued at:", "Issued:")
        self.assertIsNone(R.parse_outlook(broken, "ncrprsd"))
        # 州別データ(JS)が無くても、静的な欄だけで読める
        no_js = page("ncrprsd").split("<script>")[0]
        o = R.parse_outlook(no_js, "ncrprsd")
        self.assertEqual((len(o["days"]), o["provinces"], o["province"]), (5, {}, ""))


class Save(unittest.TestCase):
    def test_append_only_dedupe_by_region_and_issue(self):
        now = datetime(2026, 9, 26, 1, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", Path(d)):
            self.assertEqual(run.save_outlook(page("ncrprsd"), "ncrprsd", now), 1)
            self.assertEqual(run.save_outlook(page("ncrprsd"), "ncrprsd", now), 0)   # 同じ発表は足さない
            self.assertEqual(run.save_outlook(page("visprsd"), "visprsd", now), 1)
            lines = (Path(d) / "outlook" / "2026-09.jsonl").read_text().splitlines()
            self.assertEqual([json.loads(x)["id"] for x in lines],
                             ["ncrprsd:2026-09-26T09:00:00+08:00", "visprsd:2026-09-26T09:00:00+08:00"])
            self.assertEqual(json.loads(lines[0])["first_seen_utc"], "2026-09-26T01:07:00+00:00")

    def test_never_raises(self):
        now = datetime(2026, 9, 26, 1, 7, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", Path(d)), \
                mock.patch("builtins.print"):
            self.assertIsNone(run.save_outlook("<html></html>", "ncrprsd", now))
            with mock.patch.object(R, "parse_outlook", side_effect=RuntimeError("boom")):
                self.assertIsNone(run.save_outlook(page("ncrprsd"), "ncrprsd", now))
            self.assertFalse((Path(d) / "outlook").exists())


if __name__ == "__main__":
    unittest.main()


class PrsdRegions(unittest.TestCase):
    def test_page_province_names(self):
        from db.prsd_regions import _page_province
        from places.gazetteer import load
        g = load()
        self.assertEqual(g.provinces[_page_province(g, "Isabela City, Zamboanga Peninsula")].name, "City of Isabela (Not a Province)")
        self.assertEqual(g.provinces[_page_province(g, "Aurora")].name, "Aurora")
        self.assertEqual(g.provinces[_page_province(g, "North Cotabato, SOCCSKSARGEN")].region_code, "1200000000")
