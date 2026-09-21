"""2026-09-21 に実際に出た注意報の文で、名寄せを確かめる。  python3 -m unittest discover -s tests"""
import unittest

from places.advisory_places import city_codes, extract
from places.eq_places import resolve
from places.gazetteer import key, load

NCR = ("Moderate to heavy rainshowers with lightning and strong winds are expected over Bataan (Limay, Mariveles, Pilar, and Orion), "
       "Cavite (Tagaytay, Trece Martires, General Emilio Aguinaldo, Gen. Mariano Alvarez, and Dasmarinas), "
       "Metro Manila (Quezon City, Caloocan, Marikina, and Pasig), Pampanga (Porac, Mabalacat, and Angeles), "
       "Rizal (Rodriguez, San Mateo, and Antipolo), Tarlac (Capas, San Jose, and Bamban), and Zambales (Iba) within the next 2 hours.\n\n"
       "The above condition is affecting Cavite (Naic, Maragondon, and Ternate) which may persist within 2 hours.")
VIS = ("Moderate to Heavy rainshowers with lightning and strong winds are expected over #Bohol(SierraBullones, Pilar, Duero) and #Cebu(CebuCity) "
       "within the next 30 minutes to an hour.\n\nThe above conditions are being experienced in #Bohol(Carmen, GarciaHernandez and Jagna) "
       "which may persist within 1 to 2 hours and may affect nearby areas.")
WATCH = "Thunderstorm is MORE LIKELY to develop over #DavaoCity, #DavaoDelNorte, #DavaoDeOro, #Camiguin and #LanaoDelNorte within 12 hours."
REGION = "Thunderstorm is MORE LIKELY to develop over #BicolRegion within 12 hours."


def names(areas, status=None):
    return {(a.province.name if a.province else a.region_code, c.name) for a in areas if status in (None, a.status) for c in a.cities}


class Keys(unittest.TestCase):
    def test_variants_share_a_key(self):
        self.assertEqual(key("#SierraBullones"), key("Sierra Bullones"))
        self.assertEqual(key("CebuCity"), key("City of Cebu"))
        self.assertEqual(key("Dasmarinas"), key("City of Dasmariñas"))
        self.assertEqual(key("Gen. Mariano Alvarez"), key("General Mariano Alvarez"))


class Advisories(unittest.TestCase):
    def test_ncr_style(self):
        areas = extract(NCR)
        self.assertEqual([u for a in areas for u in a.unmatched], [])
        got = names(areas)
        self.assertIn(("Cavite", "City of Trece Martires"), got)
        self.assertIn(("Cavite", "Gen. Mariano Alvarez"), got)
        self.assertIn(("Tarlac", "San Jose"), got)              # 全国に 9 つある San Jose のうち Tarlac の物
        self.assertIn(("Pampanga", "City of Angeles"), got)      # PSGC では州の外の独立市
        self.assertIn(("1300000000", "Quezon City"), got)        # Metro Manila は地域として引く
        san_jose = next(c for a in areas for c in a.cities if c.name == "San Jose")
        self.assertEqual(load().provinces[san_jose.province_code].name, "Tarlac")
        self.assertEqual({c for _, c in names(areas, "occurring")}, {"Naic", "Maragondon", "Ternate"})

    def test_hashtag_style(self):
        areas = extract(VIS)
        self.assertEqual([u for a in areas for u in a.unmatched], [])
        self.assertEqual({c for _, c in names(areas, "expected")}, {"Sierra Bullones", "Pilar", "Duero", "City of Cebu"})
        self.assertEqual({c for _, c in names(areas, "occurring")}, {"Carmen", "Garcia Hernandez", "Jagna"})
        pilar = next(c for a in areas for c in a.cities if c.name == "Pilar")
        self.assertEqual(load().provinces[pilar.province_code].name, "Bohol")  # Bataan の Pilar ではない

    def test_watch_whole_provinces(self):
        areas = extract(WATCH)
        self.assertEqual([u for a in areas for u in a.unmatched], [])
        self.assertEqual({a.province.name for a in areas if a.whole}, {"Davao del Norte", "Davao de Oro", "Camiguin", "Lanao del Norte"})
        self.assertIn("City of Davao", {c.name for a in areas for c in a.cities})
        self.assertTrue(all(a.likelihood == "MORE" for a in areas))
        self.assertGreater(len(city_codes(areas)), 40)

    def test_region(self):
        areas = extract(REGION)
        self.assertEqual((areas[0].region_code, areas[0].whole), ("0500000000", True))
        self.assertGreater(len(city_codes(areas)), 100)

    def test_no_place_sentence(self):
        self.assertEqual(extract("All are advised to take precautionary measures. Keep monitoring for updates."), [])


class EarthquakeLocations(unittest.TestCase):
    def check(self, location, town, province, km):
        p = resolve(location)
        self.assertEqual((p.city.name if p.city else None, p.province.name if p.province else None, p.distance_km), (town, province, km))

    def test_real_strings(self):
        self.check("005 km S 24° E of Kalamansig (Sultan Kudarat)", "Kalamansig", "Sultan Kudarat", 5)
        self.check("094 km S 79° E of Sarangani Island (Municipality Of Sarangani) (Davao Occidental)", "Sarangani", "Davao Occidental", 94)
        self.check("0 33 km S 84° E of General Luna (Surigao Del Norte)", "General Luna", "Surigao del Norte", 33)  # 距離の打ち間違い
        self.check("021 km S 84° E of Remedios Romualdez (Agusan Del Norte)", "Remedios T. Romualdez", "Agusan del Norte", 21)
        self.check("082m N 29° E of Palapag (Northern Samar)", "Palapag", "Northern Samar", 82)  # 2018 年の書式
        self.check("037 km N 80° E of Baculin (Davao Oriental)", "Baganga", "Davao Oriental", 37)  # aliases.json


if __name__ == "__main__":
    unittest.main()
