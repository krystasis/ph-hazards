# ph-hazards (working title)

Archive of public hazard information for the Philippines, collected politely from official pages
and kept as plain files so the git history doubles as a change log.

| Data | Source | Interval |
|---|---|---|
| Earthquakes | PHIVOLCS earthquake information | 15 min (conditional GET) |
| Thunderstorm advisories / heavy rainfall warnings | PAGASA regional services divisions (5 pages) | 15 min |
| Dam water levels, flood watch status | PAGASA flood information | 3 h (values are daily) |
| Volcano alert levels | PHIVOLCS volcano monitoring | 1 h, one row per day |
| Tropical cyclone bulletins | PAGASA severe weather bulletin | 30 min, stored only while active |

This is not an official source. For decisions that affect safety, use PAGASA and PHIVOLCS directly.

The collector sends one request per page per run, identifies itself, honours 403/429 by stopping,
and never tries to get around a block. See `docs/sources/` for what was checked before each source was added.

    python3 -m unittest discover -s tests
    python3 -m collector.run
