"""D1 への送信。通信はしない(偽の transport で差し替える)。

見るところ: 送る順 / 途中で失敗したときの manifest / 1 日の上限 / 認証情報が無いとき。
"""
import json
import tempfile
import unittest
from pathlib import Path

from db import send as d1
from db.export import RECENT_MONTHS, build, diff, plan


def _eq(event_id: str, occurred_at: str, mag: str = "3.0") -> dict:
    return {"event_id": event_id, "occurred_at": occurred_at, "lat": "14.0", "lon": "121.0",
            "depth_km": "10", "mag": mag, "location": "TEST", "city_code": "012801",
            "province_code": "0128", "distance_km": "5", "bearing": "N", "row_hash": event_id + mag}


def _tables(months: dict[str, int]) -> dict:
    """{"2026-09": 3} → その月に 3 件の地震。ほかの表は空。"""
    t = {name: {} for name in ("earthquakes", "city_quake_stats", "advisories", "advisory_cities",
                               "dam_levels", "flood_watch", "river_levels", "volcano_alert",
                               "cyclone_bulletins", "source_status")}
    for month, n in months.items():
        for i in range(n):
            eid = f"{month}-{i:04d}"
            t["earthquakes"][(eid,)] = _eq(eid, f"{month}-15T0{i % 10}:00:00+08:00")
    return t


class FakeTransport:
    """送った文を覚える。fail_at 番目(0 始まり)の文で失敗する。"""

    def __init__(self, fail_at=None, rows_per_statement=100):
        self.sent = []
        self.fail_at = fail_at
        self.rows = rows_per_statement

    def execute(self, sql: str) -> int:
        if self.fail_at is not None and len(self.sent) == self.fail_at:
            self.sent.append(sql)
            raise d1.SendError("わざと失敗")
        self.sent.append(sql)
        return self.rows


class Order(unittest.TestCase):
    def test_小さい表と直近の月が先_過去分は新しい月から(self):
        tables = _tables({"2026-09": 3, "2026-08": 3, "2026-07": 3, "2026-06": 3, "2018-01": 3})
        tables["volcano_alert"][("Taal", "2026-09-21")] = {"volcano": "Taal", "date_pht": "2026-09-21", "alert_level": "1"}
        tables["source_status"][("phivolcs-eq",)] = {"source": "phivolcs-eq", "last_ok": "a", "last_fetch": "b", "note": "c"}
        keys = [u.key for u in plan(tables, {}) if u.statements]
        self.assertEqual(keys[0], "source_status")          # 「○時○分現在」がいちばん先
        self.assertLess(keys.index("volcano_alert"), keys.index("earthquakes:2026-09"))
        eq = [k for k in keys if k.startswith("earthquakes:")]
        self.assertEqual(eq, ["earthquakes:2026-09", "earthquakes:2026-08",
                              "earthquakes:2026-07", "earthquakes:2026-06", "earthquakes:2018-01"])

    def test_直近の月は過去分扱いにしない(self):
        tables = _tables({"2026-09": 3, "2026-08": 3, "2026-07": 3})
        backlog = {u.key: u.backlog for u in plan(tables, {})}
        self.assertFalse(backlog["earthquakes:2026-09"])
        self.assertFalse(backlog["earthquakes:2026-08"])
        self.assertTrue(backlog["earthquakes:2026-07"])
        self.assertEqual(RECENT_MONTHS, 2)

    def test_上限は過去分だけにかかり直近の月は必ず送る(self):
        tables = _tables({"2026-09": 5, "2026-08": 5, "2026-07": 5, "2026-06": 5})
        units = [u for u in plan(tables, {}, max_rows=5) if u.statements]
        eq = [u.key for u in units if u.key.startswith("earthquakes:")]
        self.assertEqual(eq, ["earthquakes:2026-09", "earthquakes:2026-08", "earthquakes:2026-07"])


class PartialFailure(unittest.TestCase):
    def test_失敗した単位は_manifest_に入らない(self):
        tables = _tables({"2026-09": 2, "2026-08": 2, "2026-07": 2, "2026-06": 2})
        manifest: dict = {}
        units = plan(tables, manifest, max_rows=100)
        eq_units = [u for u in units if u.key.startswith("earthquakes:")]
        # 3 つ目の地震の月(2026-07)の文で失敗させる
        before = sum(len(u.statements) for u in units[:units.index(eq_units[2])])
        t = FakeTransport(fail_at=before)
        out = d1.send(units, t, manifest, d1.Usage(None), log=lambda *a: None)
        self.assertEqual(out, "failed")
        months = manifest["earthquakes"]["months"]
        self.assertIn("2026-09", months)
        self.assertIn("2026-08", months)
        self.assertNotIn("2026-07", months)   # 失敗した月
        self.assertNotIn("2026-06", months)   # その先は送っていない

    def test_次の回は失敗した分だけ送り直す(self):
        tables = _tables({"2026-09": 2, "2026-08": 2, "2026-07": 2, "2026-06": 2})
        manifest: dict = {}
        units = plan(tables, manifest, max_rows=100)
        eq_units = [u for u in units if u.key.startswith("earthquakes:")]
        before = sum(len(u.statements) for u in units[:units.index(eq_units[2])])
        d1.send(units, FakeTransport(fail_at=before), manifest, d1.Usage(None), log=lambda *a: None)

        again = [u.key for u in plan(tables, manifest, max_rows=100) if u.statements]
        self.assertEqual([k for k in again if k.startswith("earthquakes:")],
                         ["earthquakes:2026-07", "earthquakes:2026-06"])
        t2 = FakeTransport()
        self.assertEqual(d1.send(plan(tables, manifest, max_rows=100), t2, manifest,
                                 d1.Usage(None), log=lambda *a: None), "done")
        self.assertEqual([u.key for u in plan(tables, manifest, max_rows=100) if u.statements], [])

    def test_月ごと入れ直しの_DELETE_は同じ単位に入る(self):
        """行ごとの記録が無い古い月を送り直すとき、DELETE と INSERT は分かれてはいけない。"""
        tables = _tables({"2026-09": 2, "2026-08": 2, "2018-01": 3})
        manifest: dict = {}
        d1.send(plan(tables, manifest, max_rows=100), FakeTransport(), manifest, d1.Usage(None), log=lambda *a: None)
        old = tables["earthquakes"][("2018-01-0000",)]
        tables["earthquakes"][("2018-01-0000",)] = dict(old, mag="9.9", row_hash="changed")
        unit = [u for u in plan(tables, manifest) if u.key == "earthquakes:2018-01"][0]
        self.assertIn("DELETE FROM earthquakes WHERE occurred_at >= '2018-01-01'", unit.statements[0])
        self.assertTrue(any(s.startswith("INSERT OR REPLACE INTO earthquakes") for s in unit.statements))

    def test_送る物が無い単位も_manifest_は進む(self):
        """直近でなくなった月は、行ごとの記録を捨てる(文は出ない)。"""
        tables = _tables({"2026-08": 2, "2026-07": 2})
        manifest: dict = {}
        d1.send(plan(tables, manifest), FakeTransport(), manifest, d1.Usage(None), log=lambda *a: None)
        self.assertEqual(sorted(manifest["earthquakes"]["rows"]), ["2026-07", "2026-08"])
        tables["earthquakes"][("2026-09-0000",)] = _eq("2026-09-0000", "2026-09-15T00:00:00+08:00")
        tables["earthquakes"][("2026-10-0000",)] = _eq("2026-10-0000", "2026-10-15T00:00:00+08:00")
        d1.send(plan(tables, manifest), FakeTransport(), manifest, d1.Usage(None), log=lambda *a: None)
        self.assertEqual(sorted(manifest["earthquakes"]["rows"]), ["2026-09", "2026-10"])


class Budget(unittest.TestCase):
    def test_上限に当たったら止まるが失敗ではない(self):
        tables = _tables({"2026-09": 2, "2026-08": 2, "2026-07": 2, "2026-06": 2})
        manifest: dict = {}
        usage = d1.Usage(None)
        out = d1.send(plan(tables, manifest, max_rows=100), FakeTransport(rows_per_statement=100),
                      manifest, usage, budget=250, reserve=0, log=lambda *a: None)
        self.assertEqual(out, "budget")
        self.assertGreater(usage.rows_written, 0)
        self.assertNotEqual(manifest, {})   # 途中までは進んでいる
        self.assertNotIn("2026-06", manifest.get("earthquakes", {}).get("months", {}))

    def test_残しておいた分で新しいデータは送れる(self):
        """過去分が上限に当たっても、直近の月と小さい表は送れる。"""
        tables = _tables({"2026-09": 2, "2026-08": 2, "2026-07": 2, "2026-06": 2})
        manifest: dict = {}
        usage = d1.Usage(None)
        usage.rows_written = 900   # 予備の 200 は残っている
        out = d1.send(plan(tables, manifest, max_rows=100), FakeTransport(rows_per_statement=50),
                      manifest, usage, budget=1100, reserve=200, log=lambda *a: None)
        self.assertEqual(out, "budget")
        self.assertIn("2026-09", manifest["earthquakes"]["months"])   # 直近は通る
        self.assertIn("2026-08", manifest["earthquakes"]["months"])
        self.assertNotIn("2026-07", manifest["earthquakes"]["months"])  # 過去分は止まる

    def test_過去分は上限をはみ出す前に止める(self):
        """索引のぶんで 1 行 = 5 rows_written なら、上限の手前で次の月に入らない。"""
        tables = _tables({"2026-09": 10, "2026-08": 10, "2026-07": 10, "2026-06": 10, "2026-05": 10})

        class Measured:
            sent = []

            def execute(self, sql):
                Measured.sent.append(sql)
                return 5 * sql.count("(")  # ざっくり「1 行 5 rows_written」

        manifest: dict = {}
        usage = d1.Usage(None)
        out = d1.send(plan(tables, manifest, max_rows=100), Measured(), manifest, usage,
                      budget=200, reserve=0, log=lambda *a: None)
        self.assertEqual(out, "budget")
        self.assertLess(usage.rows_written, 200)   # 見積もりで止めるので上限を超えない
        self.assertIn("2026-09", manifest["earthquakes"]["months"])

    def test_次の実行でも上限を踏み越えない(self):
        """見積もりは実行をまたいで持ち越す。1 つ目の単位を測れずに大きく超えたことがある。"""
        tables = _tables({"2026-09": 10, "2026-08": 10, "2026-07": 10, "2026-06": 10, "2026-05": 10})

        class Measured:
            def execute(self, sql):
                return 5 * sql.count("(")

        with tempfile.TemporaryDirectory() as d:
            up = Path(d) / "d1-usage.json"
            manifest: dict = {}
            for _ in range(3):   # 15 分ごとの実行を 3 回ぶん
                usage = d1.Usage(up, today="2026-09-21")
                d1.send(plan(tables, manifest, max_rows=100), Measured(), manifest, usage,
                        budget=200, reserve=0, log=lambda *a: None)
            self.assertLess(d1.Usage(up, today="2026-09-21").rows_written, 200)

    def test_日付が変わったら_0_に戻る(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "d1-usage.json"
            u = d1.Usage(p, today="2026-09-21")
            u.add(1234)
            self.assertEqual(d1.Usage(p, today="2026-09-21").rows_written, 1234)
            self.assertEqual(d1.Usage(p, today="2026-09-22").rows_written, 0)
            self.assertEqual(json.loads(p.read_text())["date"], "2026-09-21")


class Cli(unittest.TestCase):
    def test_認証情報が無ければ飛ばして_0_で終わる(self):
        import contextlib
        import io
        import os
        keep = {k: os.environ.pop(k, None) for k in d1.ENV_KEYS}
        try:
            buf = io.StringIO()
            with tempfile.TemporaryDirectory() as td:
                args = [str(Path(td) / "nodata"), "--state", str(Path(td) / "nostate"),
                        "--manifest", str(Path(td) / "m.json"), "--usage", str(Path(td) / "u.json")]
                with contextlib.redirect_stdout(buf):
                    self.assertEqual(d1.main(args + ["--dry-run"]), 0)
                    code = d1.main(args)
            self.assertEqual(code, 0)
            self.assertIn("送信は飛ばす", buf.getvalue())
        finally:
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v

    def test_wrangler_の場所は既定を持たない(self):
        import contextlib
        import io
        import os
        keep = {k: os.environ.pop(k, None) for k in ("D1_WRANGLER_BIN", "D1_WRANGLER_CWD")}
        try:
            buf = io.StringIO()
            with tempfile.TemporaryDirectory() as td, contextlib.redirect_stdout(buf):
                code = d1.main([str(Path(td) / "nodata"), "--via", "wrangler", "--state", str(Path(td)),
                                "--manifest", str(Path(td) / "m.json"), "--usage", str(Path(td) / "u.json")])
            self.assertEqual(code, 2)
        finally:
            for k, v in keep.items():
                if v is not None:
                    os.environ[k] = v


class SourceStatus(unittest.TestCase):
    def test_取得元でないファイルは入らない(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d)
            (s / "phivolcs-eq.json").write_text(json.dumps(
                {"last_ok": "2026-09-21T03:47:54+00:00", "last_fetch": "2026-09-21T03:47:54+00:00",
                 "last_note": "1279 行を解析"}))
            (s / "phivolcs-eq-archive.json").write_text(json.dumps({"done": {"2018-01": {}}}))
            (s / "d1-usage.json").write_text(json.dumps({"date": "2026-09-21", "rows_written": 1}))
            tables = build(Path(d) / "nodata", s)
            self.assertEqual(list(tables["source_status"]), [("phivolcs-eq",)])
            row = tables["source_status"][("phivolcs-eq",)]
            self.assertEqual(row["note"], "1279 行を解析")

    def test_変わった行だけ送る(self):
        with tempfile.TemporaryDirectory() as d:
            s = Path(d)
            (s / "a.json").write_text(json.dumps({"last_ok": "1", "last_fetch": "1", "last_note": "x"}))
            tables = build(Path(d) / "nodata", s)
            manifest: dict = {}
            d1.send(plan(tables, manifest), FakeTransport(), manifest, d1.Usage(None), log=lambda *a: None)
            self.assertEqual([u.key for u in plan(tables, manifest) if u.statements], [])
            (s / "a.json").write_text(json.dumps({"last_ok": "1", "last_fetch": "2", "last_note": "x"}))
            tables = build(Path(d) / "nodata", s)
            self.assertEqual([u.key for u in plan(tables, manifest) if u.statements], ["source_status"])


class DiffStillWorks(unittest.TestCase):
    def test_diff_は_plan_を全部送った結果と同じ(self):
        tables = _tables({"2026-09": 2, "2026-08": 2, "2026-07": 2})
        stmts, new, counts = diff(tables, {}, None)
        manifest: dict = {}
        t = FakeTransport()
        d1.send(plan(tables, manifest, None), t, manifest, d1.Usage(None), log=lambda *a: None)
        self.assertEqual(manifest, new)
        self.assertEqual(t.sent, stmts)
        self.assertEqual(counts["earthquakes"], 6)


if __name__ == "__main__":
    unittest.main()
