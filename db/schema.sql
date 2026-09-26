-- D1(SQLite)のスキーマ。すべての問い合わせがインデックスで引けることを前提にする
-- (D1 の無料枠は「走査した行数」で数える。全件走査が 1 本あるだけで 1 日の上限に届く)。

CREATE TABLE IF NOT EXISTS earthquakes (
  event_id      TEXT PRIMARY KEY,        -- 発生時刻(分)+ 緯度 + 経度
  occurred_at   TEXT NOT NULL,           -- ISO 8601、+08:00
  lat           REAL, lon REAL, depth_km REAL, mag REAL,
  location      TEXT NOT NULL,           -- 取得元の表記そのまま
  city_code     TEXT,                    -- 基準点の市町(震央の市町ではない)
  province_code TEXT,
  distance_km   INTEGER,
  bearing       TEXT,
  row_hash      TEXT NOT NULL            -- 内容が変わった行だけ書くための目印
);
CREATE INDEX IF NOT EXISTS eq_city_time ON earthquakes (city_code, occurred_at DESC);
CREATE INDEX IF NOT EXISTS eq_prov_time ON earthquakes (province_code, occurred_at DESC);
CREATE INDEX IF NOT EXISTS eq_time      ON earthquakes (occurred_at DESC);

-- 市町ごとの集計。ページはここを 1 行読む(13 万件を数え直さない)。
CREATE TABLE IF NOT EXISTS city_quake_stats (
  city_code TEXT PRIMARY KEY,
  total INTEGER NOT NULL, m4_plus INTEGER NOT NULL,
  max_mag REAL, max_mag_at TEXT, first_at TEXT, last_at TEXT
);

CREATE TABLE IF NOT EXISTS advisories (
  id         TEXT PRIMARY KEY,
  region     TEXT NOT NULL,              -- ncrprsd / nlprsd / slprsd / visprsd / minprsd
  kind       TEXT NOT NULL,              -- thunderstorm / rainfall
  title      TEXT NOT NULL,
  number     TEXT,
  issued_at  TEXT,
  expires_at TEXT,                       -- 本文の「within the next 2 hours」などから。読めなければ issued_at + 3 時間
  text       TEXT NOT NULL,              -- 公式の文言。書き換えない
  first_seen TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS adv_expires ON advisories (expires_at);

CREATE TABLE IF NOT EXISTS advisory_cities (
  advisory_id TEXT NOT NULL,
  city_code   TEXT NOT NULL,
  status      TEXT NOT NULL,             -- watch / expected / occurring
  expires_at  TEXT,                      -- advisories と同じ値。市町ページが結合なしで「発令中」を引くため
  PRIMARY KEY (city_code, advisory_id)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS advc_city_expires ON advisory_cities (city_code, expires_at DESC);

CREATE TABLE IF NOT EXISTS dam_levels (
  dam TEXT NOT NULL, obs_date TEXT NOT NULL, obs_time TEXT,
  rwl_m REAL, dev_24h_m REAL, nhwl_m REAL, dev_nhwl_m REAL, rule_curve_m REAL, dev_rule_curve_m REAL,
  gates TEXT, gate_opening_m TEXT, inflow_cms TEXT, outflow_cms TEXT,
  PRIMARY KEY (dam, obs_date)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS flood_watch (
  date_pht TEXT NOT NULL, sub_basin TEXT NOT NULL, status TEXT NOT NULL,
  PRIMARY KEY (sub_basin, date_pht)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS river_levels (
  station_code TEXT NOT NULL, time_pht TEXT NOT NULL, station TEXT NOT NULL,
  wl_m REAL, flag TEXT, alert_m REAL, alarm_m REAL, critical_m REAL,
  PRIMARY KEY (station_code, time_pht)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS volcano_alert (
  volcano TEXT NOT NULL, date_pht TEXT NOT NULL, alert_level INTEGER NOT NULL,
  PRIMARY KEY (volcano, date_pht)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS cyclone_bulletins (
  sha TEXT PRIMARY KEY, fetched_utc TEXT NOT NULL, text TEXT NOT NULL
);

-- 取得元ごとの鮮度。ページの「○時○分現在」と、外形監視が読む。
CREATE TABLE IF NOT EXISTS source_status (
  source TEXT PRIMARY KEY, last_ok TEXT, last_fetch TEXT, note TEXT
) WITHOUT ROWID;

-- 市町ごとの地震の頻度(50 km 圏、ベースレート)。「予知」ではなく「この土地はどれくらい揺れる場所か」。
-- 完全性の都合で M3.0 以上だけを数える(M1〜2 は年によって取りこぼしが違う)。
CREATE TABLE IF NOT EXISTS city_quake_rates (
  city_code      TEXT PRIMARY KEY,
  radius_km      INTEGER NOT NULL,
  since          TEXT NOT NULL,           -- 数え始めの日
  until_         TEXT NOT NULL,           -- 数え終わりの日
  years          REAL NOT NULL,
  n_m3           INTEGER NOT NULL,
  n_m4           INTEGER NOT NULL,
  n_m5           INTEGER NOT NULL,
  m4_per_year    REAL NOT NULL,
  p30_m4         REAL NOT NULL,           -- 30 日以内に M4.0+ が 1 回以上ある確率(ポアソン近似、0..1)
  p365_m4        REAL NOT NULL,
  last_m4_at     TEXT,                    -- 最後の M4.0+ の発生時刻
  last_m5_at     TEXT,
  m4_by_year     TEXT NOT NULL            -- JSON {"2018": n, …}(傾向の折れ線用)
) WITHOUT ROWID;

-- M5.5 以上だけの小さな写し(2018 年〜、数百行)。「直近に大きい地震があったか」を、13 万行の表を走査せずに引くため。
CREATE TABLE IF NOT EXISTS big_quakes (
  event_id      TEXT PRIMARY KEY,
  occurred_at   TEXT NOT NULL,
  lat REAL, lon REAL, depth_km REAL, mag REAL,
  location      TEXT NOT NULL,
  city_code     TEXT,
  province_code TEXT
);
CREATE INDEX IF NOT EXISTS bigq_time ON big_quakes (occurred_at DESC);

-- 市町ページの地震の記録(city_quake_stats と同じ対象: 基準点の市町が付いた地震、全マグニチュード)。年・月・日は PHT。
CREATE TABLE IF NOT EXISTS city_quake_years (
  city_code TEXT, year INTEGER, n INTEGER, n_m4 INTEGER,  -- n_m4 = M4.0 以上
  PRIMARY KEY (city_code, year)
) WITHOUT ROWID;

-- マグニチュードの帯 <3.0 / 3.0–3.9 / 4.0–4.9 / 5.0+。latest_30d は手元の最新の地震までの 30 日(実行時刻ではない)。
CREATE TABLE IF NOT EXISTS city_quake_bands (
  city_code TEXT PRIMARY KEY,
  lt3 INTEGER, m3 INTEGER, m4 INTEGER, m5 INTEGER,
  latest_30d INTEGER, latest_30d_max REAL                  -- 30 日に 0 件なら latest_30d_max は NULL
) WITHOUT ROWID;

-- 直近 24 か月(最新の地震の月を含む)だけ。0 件の月は行が無い。窓から出た月は、窓が動いた回に
-- 書き出し側が「month < 下限」の DELETE を同じ単位で送って消す(db/export.py の _rowhash_unit)。
CREATE TABLE IF NOT EXISTS city_quake_months (
  city_code TEXT, month TEXT, n INTEGER,                  -- month = 'YYYY-MM'
  PRIMARY KEY (city_code, month)
) WITHOUT ROWID;

-- 全国の日ごとの件数(PHT の日付)。記録の最初の日から最後の日まで、0 件の日も 1 行ある。
CREATE TABLE IF NOT EXISTS daily_quake_counts (
  day TEXT PRIMARY KEY, n INTEGER, n_m4 INTEGER           -- day = 'YYYY-MM-DD'
) WITHOUT ROWID;

-- PAGASA 地域別ページの週間予報(Extended Weather Outlook)。発表ごとに全部残す。
-- region は ncrprsd などの PRSD。中身はそのページの**既定の州 1 つぶん**(docs/sources/pagasa-regional.md)。
-- day_index 0 = 欄の先頭の日(day_name が曜日。2026-09-26 の実物では発表日と同じ曜日)。tmin / tmax は ℃、wind / direction / coastal は取得元の表記そのまま。
CREATE TABLE IF NOT EXISTS regional_outlook (
  region TEXT, issued_at TEXT, day_index INTEGER, day_name TEXT,
  tmin INTEGER, tmax INTEGER, wind TEXT, direction TEXT, coastal TEXT,
  PRIMARY KEY (region, issued_at, day_index)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS outlook_region_issued ON regional_outlook (region, issued_at DESC);
