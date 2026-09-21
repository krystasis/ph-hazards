# ph-hazards (working title)

Archive of public hazard information for the Philippines, collected politely from official pages
and kept as plain files so the git history doubles as a change log.

| Data | Source | Interval |
|---|---|---|
| Earthquakes (2018 onward) | PHIVOLCS earthquake information | 15 min (conditional GET); past months loaded once |
| Thunderstorm advisories / heavy rainfall warnings | PAGASA regional services divisions (5 pages) | 15 min |
| Dam water levels, flood watch status | PAGASA flood information | 3 h (values are daily) |
| River water levels (Pasig-Marikina-Tullahan basin, 17 stations) | PAGASA flood forecasting and warning system | 15 min, stored when a value changes |
| Volcano alert levels | PHIVOLCS volcano monitoring | 1 h, one row per day |
| Tropical cyclone bulletins | PAGASA severe weather bulletin | 30 min, stored only while active |

This is not an official source. For decisions that affect safety, use PAGASA and PHIVOLCS directly.

The collector sends one request per page per run, identifies itself, honours 403/429 by stopping,
and never tries to get around a block. See `docs/sources/` for what was checked before each source was added.

Changed rows are also pushed to a Cloudflare D1 database that a separate site reads. That step is
skipped unless `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID` and `D1_DATABASE_ID` are set, so a
fork keeps working without them. It stops for the day once it has written the configured number of
rows (default 60,000), to stay inside the free plan.

    python3 -m unittest discover -s tests
    python3 -m collector.run
    python3 -m db.send data --dry-run
