"""土地の危険度(data/hazard_susceptibility.csv → hazard_susceptibility)の書き出し。"""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from db.export import COLUMNS, build, diff

HEAD = ",".join(COLUMNS["hazard_susceptibility"])
ROWS = [
    "1380700000,flood_100yr,48.4,15.6,4.3,high,noah-2021-10/hf-x,2026-09-27",
    "1380700000,landslide,0.0,0.1,0.3,low,noah-2021-10/hf-x,2026-09-27",
    "1380700000,storm_surge,0.0,0.0,0.0,none,noah-2021-10/hf-x,2026-09-27",
]


class Hazard(unittest.TestCase):
    def _tables(self, lines):
        d = Path(tempfile.mkdtemp())
        (d / "data").mkdir()
        if lines is not None:
            (d / "data" / "hazard_susceptibility.csv").write_text("\n".join([HEAD, *lines]) + "\n")
        return build(d / "data", d / "state")

    def test_no_file_is_empty(self):
        self.assertEqual(self._tables(None)["hazard_susceptibility"], {})

    def test_rows_diff_and_delete(self):
        con = sqlite3.connect(":memory:")
        con.executescript((Path(__file__).parent.parent / "db" / "schema.sql").read_text())
        stmts, m, c = diff(self._tables(ROWS), {})
        for s in stmts:
            con.execute(s)
        self.assertEqual(c["hazard_susceptibility"], 3)
        self.assertEqual(con.execute("select class_high_pct, label from hazard_susceptibility where city_code='1380700000' and layer='flood_100yr'").fetchone(), (48.4, "high"))
        # 変わらなければ 0 行、1 行消えたら DELETE が出る
        self.assertEqual(diff(self._tables(ROWS), m)[2]["hazard_susceptibility"], 0)
        stmts, m, c = diff(self._tables(ROWS[:2]), m)
        for s in stmts:
            con.execute(s)
        self.assertEqual(con.execute("select count(*) from hazard_susceptibility").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
