"""台風公報。実物は 2026-09-24〜27 の Typhoon "Queenie"(data/tcb/2026-09.jsonl)。

- pagasa_tcb_queenie.html: 2026-09-27 17:00 の公報のページ(実物の切り抜き。コメントアウトされた HTML を含む)
- pagasa_tcb_queenie_2026-09-27T11.txt: 2026-09-27 11:00 の公報の本文(実物を整えた物)
- pagasa_tcb_signals_SYNTHETIC.txt: **SYNTHETIC(手で作った物)**。Queenie はシグナルが一度も出ていないので、
  シグナルの読み方は PAGASA の公表している書式から作った。実物では未確認。
"""
import json
import tempfile
import unittest
from pathlib import Path

from collector import pagasa_tcb as T
from collector import tcb_clean, tcb_parse

FIX = Path(__file__).parent / "fixtures"
DATA = Path(__file__).parent.parent / "data" / "tcb" / "2026-09.jsonl"

# 整える前の行(2026-09-27 17:00 の公報。取得したままの本文の頭と尻)
LEGACY_HEAD = ('Typhoon "Queenie"\n\nTOS\n\n-->\n\nTyphoon "Queenie"\n\nTropical Cyclone: ALERT -->\n\n'
               "Issued at 05:00 pm, 27 September 2026\n"
               "(Valid for broadcast until the next advisory to be issued at 5:00 AM tomorrow) -->\n"
               "(Valid for broadcast until the next advisory to be issued at 5:00 AM tomorrow)\n\n")


def fix(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


class Collect(unittest.TestCase):
    def test_page_is_stored_clean(self):
        items = T.parse_all(fix("pagasa_tcb_queenie.html"))
        self.assertEqual(len(items), 1)
        text = items[0]["text"]
        for junk in ("-->", "TOS", "ALERT", "Previous", "Bulletin Archive", "TCB#"):
            self.assertNotIn(junk, text)
        self.assertEqual(text.count("(Valid for broadcast"), 1)
        self.assertTrue(text.startswith('Typhoon "Queenie"\n\nIssued at 05:00 pm, 27 September 2026\n'))
        self.assertIn("QUEENIE HAS EXITED THE PHILIPPINE AREA OF RESPONSIBILITY.", text)
        self.assertEqual(items[0]["sha"], T.sha_of(text))
        self.assertEqual(T.parse(fix("pagasa_tcb_queenie.html")), items[0])

    def test_legacy_row_cleans_to_the_same_text(self):
        """整える前の行を tcb_clean で整えると、同じページを今の収集器で読んだ本文と一致する。"""
        page_text = T.parse_all(fix("pagasa_tcb_queenie.html"))[0]["text"]
        body = page_text.split("\n\n", 3)[3]   # 「QUEENIE HAS EXITED …」から後ろ
        legacy = LEGACY_HEAD + body + "\n\nTropical Cyclone Bulletin Archive\n\nTCB#1_queenie.pdf\n\nPrevious Next\n-->"
        self.assertEqual(T.clean_text(legacy), page_text)
        self.assertEqual(T.clean_text(page_text), page_text)   # 何度かけても同じ

    def test_two_cyclones_two_bulletins(self):
        page = fix("pagasa_tcb_queenie.html")
        a, b = page.index('<div role="tabpanel"'), page.index("We always find ways")
        pane = page[a:b]
        second = pane.replace("Queenie", "Rolly").replace("QUEENIE", "ROLLY").replace('id="tcwb-1"', 'id="tcwb-2"')
        items = T.parse_all(page[:a] + pane + second + page[b:])
        self.assertEqual([i["text"].split("\n")[0] for i in items], ['Typhoon "Queenie"', 'Typhoon "Rolly"'])

    def test_clean_file_dedupes_and_keeps_sha(self):
        rows = [{"fetched_utc": "2026-09-27T09:39:04+00:00", "sha": "old1",
                 "text": LEGACY_HEAD + "X\n\nTropical Cyclone Bulletin Archive\n\nTCB#13_queenie.pdf\n\nPrevious Next\n-->"},
                {"fetched_utc": "2026-09-27T10:09:04+00:00", "sha": "old2",
                 "text": LEGACY_HEAD + "X\n\nTropical Cyclone Bulletin Archive\n\nTCB#13_queenie.pdf\nTCB#14_queenie.pdf\n\nPrevious Next\n-->"}]
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "2026-09.jsonl"
            p.write_text("".join(json.dumps(r) + "\n" for r in rows))
            self.assertEqual(tcb_clean.clean_file(p), (2, 1))
            out = [json.loads(ln) for ln in p.read_text().splitlines()]
            self.assertEqual(out[0]["sha"], "old1")
            self.assertNotIn("-->", out[0]["text"])
            self.assertEqual(tcb_clean.clean_file(p), (1, 1))


class Parse(unittest.TestCase):
    def test_real_bulletin(self):
        a = tcb_parse.parse(fix("pagasa_tcb_queenie_2026-09-27T11.txt"))
        self.assertEqual((a["name"], a["category"]), ("Queenie", "Typhoon"))
        self.assertEqual(a["issued_at"], "2026-09-27T11:00:00+08:00")
        self.assertEqual(a["next_advisory_at"], "2026-09-27T17:00:00+08:00")
        self.assertEqual(a["headline"], "QUEENIE FURTHER INTENSIFIES AND IS ABOUT TO EXIT THE PHILIPPINE AREA OF RESPONSIBILITY.")
        self.assertEqual(a["par_status"], "exiting")
        self.assertTrue(a["center_text"].startswith("The center of the eye of Typhoon QUEENIE was estimated"))
        self.assertEqual((a["center_lat"], a["center_lon"]), (24.9, 127.6))
        self.assertEqual(a["movement"], "Moving North Northeastward at 10 km/h")
        self.assertEqual((a["max_wind_kmh"], a["gust_kmh"]), (150, 185))
        self.assertEqual(a["forecast_positions"][0]["at"], "2026-09-27T20:00:00+08:00")
        self.assertEqual([f["outside_par"] for f in a["forecast_positions"]], [True, True, True])
        self.assertTrue(a["coastal_text"].startswith("24-Hour Sea Condition Outlook"))
        self.assertIsNotNone(a["land_hazards_text"])
        self.assertEqual(a["signals"], [])   # 「No Tropical Cyclone Wind Signal」

    def test_all_real_bulletins(self):
        """2026-09 の実物全部。発表時刻・強さ・位置が本文どおりに取れる。"""
        got = {}
        for ln in DATA.read_text(encoding="utf-8").splitlines():
            a = tcb_parse.parse(json.loads(ln)["text"])
            got[a["issued_at"]] = (a["category"], a["par_status"], a["max_wind_kmh"], a["center_lat"], a["center_lon"])
            self.assertEqual(a["name"], "Queenie")
            self.assertTrue(a["headline"] and a["movement"] and a["forecast_positions"])
            self.assertEqual(a["signals"], [])
        self.assertEqual(len(got), 14)
        self.assertEqual(got["2026-09-24T11:00:00+08:00"], ("Tropical Storm", "inside", 75, 17.8, 134.1))
        self.assertEqual(got["2026-09-24T23:00:00+08:00"][4], 132.0)   # 本文は「132. °E」
        self.assertEqual(got["2026-09-25T23:00:00+08:00"][:3], ("Severe Tropical Storm", "inside", 95))
        self.assertEqual(got["2026-09-26T23:00:00+08:00"][:3], ("Typhoon", "inside", 120))
        self.assertEqual(got["2026-09-27T17:00:00+08:00"], ("Typhoon", "outside", 155, 25.6, 128.5))

    def test_missing_values_are_none(self):
        a = tcb_parse.parse('Typhoon "X"\n\nsomething else entirely')
        self.assertEqual((a["name"], a["category"]), ("X", "Typhoon"))
        for k in ("issued_at", "next_advisory_at", "center_lat", "max_wind_kmh", "movement", "headline"):
            self.assertIsNone(a[k])
        self.assertEqual((a["par_status"], a["forecast_positions"], a["signals"]), ("unknown", [], []))

    def test_par_status_rules(self):
        f = tcb_parse.par_status
        self.assertEqual(f("X HAS ENTERED THE PHILIPPINE AREA OF RESPONSIBILITY", "at 500 km East (15.0 °N, 130.0 °E )", ""), "inside")
        self.assertEqual(f("X IS ABOUT TO EXIT THE PHILIPPINE AREA OF RESPONSIBILITY", "at 700 km (24.9 °N, 127.6 °E )", ""), "exiting")
        self.assertEqual(f("X HAS EXITED THE PHILIPPINE AREA OF RESPONSIBILITY.", "(OUTSIDE PAR) (25.6 °N, 128.5 °E )", ""), "outside")
        self.assertEqual(f("X CONTINUES TO MOVE WESTWARD", "1,500 km East of Mindanao (OUTSIDE PAR)",
                           "X is forecast to enter the PAR tomorrow."), "entering")
        self.assertEqual(f(None, None, None), "unknown")


class Signals(unittest.TestCase):
    """SYNTHETIC の欄だけで確かめている(実物では未確認)。"""

    def setUp(self):
        text = fix("pagasa_tcb_signals_SYNTHETIC.txt")
        self.rows = tcb_parse.parse_signals(text.split("Wind Signal", 1)[1])
        self.by = {(r["signal"], r["area"]): r for r in self.rows}

    def test_portion_with_towns(self):
        p = self.by[(3, "The northern portion of mainland Cagayan")]
        self.assertEqual((p["area_kind"], p["province_code"], p["city_code"]), ("portion", "0201500000", None))
        towns = [r["area"] for r in self.rows if r["signal"] == 3 and r["area_kind"] == "city"]
        self.assertEqual(towns, ["Santa Ana", "Gonzaga", "Aparri", "Buguey"])
        self.assertEqual(self.by[(3, "Santa Ana")]["city_code"], "0201523000")   # Cagayan の Santa Ana(Pampanga ではない)
        self.assertEqual(self.by[(1, "Casiguran")]["province_code"], "0307700000")  # Aurora の Casiguran(Sorsogon ではない)

    def test_rest_and_provinces(self):
        self.assertEqual(self.by[(2, "the rest of Cagayan")]["area_kind"], "portion")
        self.assertEqual(self.by[(2, "Batanes")]["area_kind"], "province")
        self.assertEqual(self.by[(2, "the northern and central portions of Isabela")]["province_code"], "0203100000")
        self.assertEqual(self.by[(2, "Ilagan City")]["city_code"], "0203114000")
        self.assertEqual(self.by[(1, "Metro Manila")]["province_code"], "1300000000")
        self.assertEqual(self.by[(1, "Dinagat Islands")]["area_kind"], "province")
        self.assertEqual(self.by[(3, "Babuyan Islands")]["province_code"], "0201500000")

    def test_descriptors_and_island_heads_are_not_places(self):
        areas = {r["area"] for r in self.rows}
        for word in ("Luzon", "Visayas", "Mindanao", "Wind threat", "Strong winds", "36 hours"):
            self.assertFalse(any(word.lower() in a.lower() for a in areas), word)
        self.assertEqual(len(self.rows), 29)
        self.assertTrue(all(r["province_code"] for r in self.rows))

    def test_no_signal(self):
        self.assertEqual(tcb_parse.parse_signals("No Tropical Cyclone Wind Signal"), [])
        self.assertEqual(tcb_parse.parse_signals(""), [])


class Save(unittest.TestCase):
    def test_same_bulletin_is_not_added_twice(self):
        from datetime import datetime, timezone
        from unittest import mock
        from collector import run
        page = fix("pagasa_tcb_queenie.html")
        now = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", Path(d)):
            # 整える前に入った行(sha は古いまま、本文は tcb_clean 済み)があれば、sha が違っても足さない
            old = {"fetched_utc": "2026-09-27T09:39:04+00:00", "sha": "4b157e4d5f65bcab", "text": T.parse_all(page)[0]["text"]}
            (Path(d) / "tcb").mkdir()
            (Path(d) / "tcb" / "2026-09.jsonl").write_text(json.dumps(old) + "\n")
            self.assertEqual(run.save_tcb(page, now), (1, 0))
            self.assertEqual(run.save_tcb("<html>No Active Tropical Cyclone</html>", now), (0, 0))
        with tempfile.TemporaryDirectory() as d, mock.patch.object(run, "DATA", Path(d)):
            self.assertEqual(run.save_tcb(page, now), (1, 1))
            self.assertEqual(run.save_tcb(page, now), (1, 0))


class SignalWatch(unittest.TestCase):
    """シグナルの行が出たら目立つ 1 行を出し、初めての回だけ赤くする(collector/run.py の signal_watch)。"""

    def setUp(self):
        from datetime import datetime, timezone
        self.now = datetime(2026, 10, 1, 0, 0, tzinfo=timezone.utc)
        base = fix("pagasa_tcb_queenie_2026-09-27T11.txt")
        self.quiet = {"sha": "q", "text": base}
        # 実物の本文のシグナル欄を、手で作った欄に差し替えた物(SYNTHETIC)
        head, _, _ = base.partition("Wind Signal")
        self.loud = {"sha": "s", "text": head + fix("pagasa_tcb_signals_SYNTHETIC.txt").split("\n", 1)[1]}

    def test_シグナルが無ければ何もしない(self):
        from collector import run
        state = {}
        self.assertEqual(run.signal_watch([self.quiet], state, self.now), (0, False))
        self.assertEqual(run.signal_watch([], state, self.now), (0, False))
        self.assertNotIn("signals_seen_first", state)

    def test_初めての回だけ赤_以後は緑(self):
        from collector import run
        state = {}
        n, first = run.signal_watch([self.loud], state, self.now)
        self.assertGreater(n, 5)
        self.assertTrue(first)
        self.assertEqual(state["signals_seen_first"], self.now.isoformat())
        n2, first2 = run.signal_watch([self.loud], state, self.now)
        self.assertEqual((n2, first2), (n, False))
        self.assertEqual(state["signals_seen_first"], self.now.isoformat())

    def test_run_tcb_の終了コード(self):
        from unittest import mock
        from collector import run
        page = "<html>Tropical Cyclone</html>"
        resp = mock.Mock(text=page, status=200, etag="", last_modified="")
        saved = {}
        with mock.patch.object(run, "fetch", return_value=resp), \
             mock.patch.object(run, "load_state", side_effect=lambda k: dict(saved)), \
             mock.patch.object(run, "save_state", side_effect=lambda k, st: saved.update(st)), \
             mock.patch.object(run, "save_tcb", side_effect=lambda p, now, stored: (stored.append(self.loud), (1, 1))[1]), \
             mock.patch("builtins.print") as out:
            ok, note = run.run_tcb(self.now, True)
            self.assertFalse(ok)                                   # 初めて → 赤
            self.assertIn("★ シグナル", out.call_args_list[0].args[0])
            ok2, _ = run.run_tcb(self.now, True)
            self.assertTrue(ok2)                                   # 2 回目 → 緑
        self.assertIn("signals_seen_first", saved)
        self.assertIn("シグナル", note)
