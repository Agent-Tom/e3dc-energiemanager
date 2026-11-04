"""Unit-Tests für planner.py (reine Rechenlogik, ohne Home Assistant).

Ausführen im Repo-Wurzelordner:

    python -m unittest discover -s tests -v

Läuft auch unter pytest. Keine Abhängigkeiten außer der Standardbibliothek.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
import importlib.util
from pathlib import Path
import sys
import unittest

# planner.py direkt laden: Das Paket-__init__ importiert Home Assistant.
_PFAD = Path(__file__).resolve().parents[1] / "custom_components" / "energiemanager" / "planner.py"
_spec = importlib.util.spec_from_file_location("energiemanager_planner", _PFAD)
planner = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = planner
_spec.loader.exec_module(planner)

# Fenster wie DEFAULT_TARIFF in const.py (Octopus Heat), Preise gerundet
OCTOPUS = "02:00-06:00=low@0.18; 12:00-16:00=low@0.18; 18:00-21:00=high@0.35"
MODELL = (35.0, 54.3, 3.2, 8.0)
KAPAZITAET = 32.6


def dt(h: int, m: int = 0, tag: int = 2) -> datetime:
    """Zeitpunkt am 2.11.2026, mit tag=3 am Folgetag."""
    return datetime(2026, 11, tag, h, m)


class TestParseTariff(unittest.TestCase):
    def test_octopus(self):
        w = planner.parse_tariff(OCTOPUS)
        self.assertEqual(len(w), 3)
        self.assertEqual(w[0], planner.TariffWindow(time(2), time(6), "low", 0.18))
        self.assertEqual(w[1], planner.TariffWindow(time(12), time(16), "low", 0.18))
        self.assertEqual(w[2], planner.TariffWindow(time(18), time(21), "high", 0.35))

    def test_zeilenumbruch_komma_und_grossschreibung(self):
        w = planner.parse_tariff("02:00-06:00=LOW@0,18\n18:00 - 21:00 = high")
        self.assertEqual(w[0].level, "low")
        self.assertAlmostEqual(w[0].price, 0.18)
        self.assertEqual(w[1], planner.TariffWindow(time(18), time(21), "high", None))

    def test_ohne_stufe_ist_low(self):
        w = planner.parse_tariff("02:00-06:00")
        self.assertEqual(w, [planner.TariffWindow(time(2), time(6), "low", None)])

    def test_24_uhr_ist_mitternacht(self):
        w = planner.parse_tariff("22:00-24:00=high")
        self.assertEqual(w[0].end, time(0))
        self.assertEqual(w[0].duration, timedelta(hours=2))

    def test_leere_eintraege_werden_uebersprungen(self):
        self.assertEqual(len(planner.parse_tariff(" ; ;02:00-06:00=low; ")), 1)
        self.assertEqual(planner.parse_tariff(""), [])

    def test_unbekannte_stufe(self):
        with self.assertRaises(ValueError):
            planner.parse_tariff("02:00-06:00=billig@0.1")

    def test_kaputte_zeit(self):
        with self.assertRaises(ValueError):
            planner.parse_tariff("02-06=low")


class TestTariffWindowDuration(unittest.TestCase):
    def test_am_selben_tag(self):
        self.assertEqual(planner.TariffWindow(time(2), time(6), "low").duration, timedelta(hours=4))

    def test_ueber_mitternacht(self):
        self.assertEqual(planner.TariffWindow(time(22), time(2), "low").duration, timedelta(hours=4))

    def test_gleicher_start_und_ende_ist_ganzer_tag(self):
        self.assertEqual(planner.TariffWindow(time(0), time(0), "low").duration, timedelta(hours=24))


class TestFenster(unittest.TestCase):
    def setUp(self):
        self.w = planner.parse_tariff(OCTOPUS)

    def test_current_level(self):
        erwartet = {
            dt(1): "normal",
            dt(2): "low",
            dt(5, 59): "low",
            dt(6): "normal",  # Fensterende ist exklusiv
            dt(12): "low",
            dt(16): "normal",
            dt(18): "high",
            dt(20, 59): "high",
            dt(21): "normal",
        }
        for zeit, stufe in erwartet.items():
            with self.subTest(zeit=zeit):
                self.assertEqual(planner.current_level(self.w, zeit), stufe)

    def test_current_price(self):
        self.assertEqual(planner.current_price(self.w, dt(3), 0.27), 0.18)
        self.assertEqual(planner.current_price(self.w, dt(19), 0.27), 0.35)
        self.assertEqual(planner.current_price(self.w, dt(10), 0.27), 0.27)

    def test_fenster_ohne_preis_nimmt_normalpreis(self):
        w = planner.parse_tariff("02:00-06:00=low")
        self.assertEqual(planner.current_price(w, dt(3), 0.27), 0.27)

    def test_fenster_ueber_mitternacht(self):
        w = planner.parse_tariff("22:00-02:00=low@0.1")
        frueh = planner.current_window(w, dt(1))
        self.assertEqual((frueh.start, frueh.end), (dt(22, tag=1), dt(2)))
        spaet = planner.current_window(w, dt(23))
        self.assertEqual((spaet.start, spaet.end), (dt(22), dt(2, tag=3)))
        self.assertIsNone(planner.current_window(w, dt(2)))

    def test_occurrences_sortiert_und_vollstaendig(self):
        occ = planner.occurrences(self.w, dt(10))
        self.assertEqual(len(occ), 3 * 5)  # 1 Tag zurück, heute, 3 Tage voraus
        self.assertEqual(occ, sorted(occ, key=lambda o: o.start))
        self.assertEqual(occ[0].start, dt(2, tag=1))

    def test_relevant_low_window(self):
        erwartet = {
            dt(1): dt(2),
            dt(3): dt(2),  # laufendes Fenster
            dt(6): dt(12),  # Fenster gerade zu Ende
            dt(7): dt(12),
            dt(15, 59): dt(12),
            dt(17): dt(2, tag=3),
        }
        for zeit, start in erwartet.items():
            with self.subTest(zeit=zeit):
                self.assertEqual(planner.relevant_low_window(self.w, zeit).start, start)

    def test_next_low_after(self):
        self.assertEqual(planner.next_low_after(self.w, dt(6)).start, dt(12))
        self.assertEqual(planner.next_low_after(self.w, dt(16)).start, dt(2, tag=3))
        # Start genau zum Zeitpunkt zählt mit
        self.assertEqual(planner.next_low_after(self.w, dt(2)).start, dt(2))

    def test_ohne_niedrigtarif(self):
        w = planner.parse_tariff("18:00-21:00=high@0.35")
        self.assertIsNone(planner.relevant_low_window(w, dt(10)))
        self.assertIsNone(planner.next_low_after(w, dt(10)))

    def test_key_ist_startzeit(self):
        self.assertEqual(planner.relevant_low_window(self.w, dt(7)).key, "2026-11-02T12:00:00")

    def test_zeitzonenbehaftete_zeiten(self):
        tz = timezone(timedelta(hours=1))
        jetzt = datetime(2026, 11, 2, 3, 0, tzinfo=tz)
        o = planner.current_window(self.w, jetzt)
        self.assertEqual(o.end, datetime(2026, 11, 2, 6, 0, tzinfo=tz))


class TestBilanz(unittest.TestCase):
    PROFIL = [float(h) for h in range(24)]  # Stunde h verbraucht h kW

    def test_hourly_sum_volle_stunden(self):
        self.assertAlmostEqual(planner.hourly_sum(self.PROFIL, dt(6), dt(9)), 6 + 7 + 8)

    def test_hourly_sum_anteilig(self):
        self.assertAlmostEqual(planner.hourly_sum(self.PROFIL, dt(6, 30), dt(8, 15)), 0.5 * 6 + 7 + 0.25 * 8)

    def test_hourly_sum_ueber_mitternacht(self):
        self.assertAlmostEqual(planner.hourly_sum(self.PROFIL, dt(23), dt(1, tag=3)), 23 + 0)

    def test_hourly_sum_leerer_zeitraum(self):
        self.assertEqual(planner.hourly_sum(self.PROFIL, dt(9), dt(9)), 0.0)
        self.assertEqual(planner.hourly_sum(self.PROFIL, dt(9), dt(8)), 0.0)

    def test_pv_sum(self):
        fc = [(dt(10), 2.0), (dt(11), 4.0)]
        self.assertAlmostEqual(planner.pv_sum(fc, dt(10), dt(12)), 6.0)
        self.assertAlmostEqual(planner.pv_sum(fc, dt(10, 30), dt(11, 30)), 1.0 + 2.0)
        self.assertEqual(planner.pv_sum(fc, dt(12), dt(16)), 0.0)
        self.assertEqual(planner.pv_sum([], dt(0), dt(23)), 0.0)

    def test_mean_temp(self):
        fc = [(dt(h), float(h)) for h in range(24)]
        self.assertAlmostEqual(planner.mean_temp(fc, dt(6), dt(9)), 7.0)  # Ende exklusiv
        self.assertIsNone(planner.mean_temp(fc, dt(6, 10), dt(6, 50)))
        self.assertIsNone(planner.mean_temp([], dt(0), dt(23)))


class TestTemperatur(unittest.TestCase):
    def test_hp_daily_model(self):
        self.assertAlmostEqual(planner.hp_daily_model(10, MODELL), 35 + 54.3 - 32)
        self.assertAlmostEqual(planner.hp_daily_model(0, MODELL), 35 + 54.3)
        self.assertAlmostEqual(planner.hp_daily_model(20, MODELL), 35 + 8)  # Mindestverbrauch WP

    def test_temp_correction(self):
        self.assertAlmostEqual(planner.temp_correction(5, 10, MODELL), 73.3 / 57.3)
        self.assertAlmostEqual(planner.temp_correction(10, 10, MODELL), 1.0)

    def test_temp_correction_begrenzt(self):
        self.assertEqual(planner.temp_correction(0, 10, MODELL), 1.5)  # 89,3/57,3 = 1,56
        self.assertEqual(planner.temp_correction(25, 5, MODELL), 0.7)  # 43/73,3 = 0,59

    def test_temp_correction_ohne_daten(self):
        self.assertEqual(planner.temp_correction(None, 10, MODELL), 1.0)
        self.assertEqual(planner.temp_correction(5, None, MODELL), 1.0)


class TestBuildPlan(unittest.TestCase):
    def plan(self, jetzt, profil_kw=1.0, **kw):
        windows = planner.parse_tariff(OCTOPUS)
        args = dict(
            window=planner.relevant_low_window(windows, jetzt),
            windows=windows,
            profile_kw=[profil_kw] * 24,
            pv_forecast=[],
            temp_forecast=[],
            t_history=None,
            hp_model=MODELL,
            capacity_kwh=KAPAZITAET,
            safety=1.5,
            buffer_pct=10,
            min_soc=25,
            max_soc=95,
        )
        args.update(kw)
        return planner.build_plan(**args)

    def test_mittagsfenster_deckt_16_bis_02(self):
        p = self.plan(dt(12))
        self.assertEqual((p.window_start, p.window_end), (dt(12), dt(16)))
        self.assertEqual((p.cover_start, p.cover_end), (dt(16), dt(2, tag=3)))
        self.assertEqual(p.window_key, dt(12).isoformat())
        self.assertEqual(p.consumption_kwh, 10.0)
        self.assertEqual(p.temp_factor, 1.0)
        self.assertEqual(p.need_kwh, 15.0)  # 10 kWh × 1,5
        # 15 / 32,6 = 46,0 % + 10 Puffer = 56,0 -> auf 5 gerundet 55
        self.assertEqual(p.target_soc, 55)

    def test_nachtfenster_deckt_06_bis_12_abzueglich_pv(self):
        pv = [(dt(9), 2.0), (dt(10), 2.0), (dt(11), 2.0), (dt(12), 5.0)]  # 12 Uhr liegt außerhalb
        p = self.plan(dt(1), profil_kw=2.0, pv_forecast=pv)
        self.assertEqual((p.cover_start, p.cover_end), (dt(6), dt(12)))
        self.assertEqual(p.pv_kwh, 6.0)
        self.assertEqual(p.need_kwh, 12.0)  # 12 kWh × 1,5 − 6
        # 12 / 32,6 = 36,8 % + 10 = 46,8 -> 45
        self.assertEqual(p.target_soc, 45)

    def test_puffer_sind_prozentpunkte_soc(self):
        ohne = self.plan(dt(12), buffer_pct=0)
        mit = self.plan(dt(12), buffer_pct=10)
        self.assertEqual(mit.target_soc - ohne.target_soc, 10)

    def test_pv_ueber_bedarf_ergibt_mindestziel(self):
        pv = [(dt(6) + timedelta(hours=i), 9.0) for i in range(6)]
        p = self.plan(dt(1), pv_forecast=pv)
        self.assertEqual(p.need_kwh, 0.0)
        self.assertEqual(p.target_soc, 25)

    def test_obergrenze(self):
        p = self.plan(dt(12), profil_kw=5.0)
        self.assertEqual(p.target_soc, 95)

    def test_temperaturfaktor(self):
        temp = [(dt(16) + timedelta(hours=i), 5.0) for i in range(10)]
        temp.append((dt(14), 30.0))  # außerhalb des Deckungszeitraums
        p = self.plan(dt(12), temp_forecast=temp, t_history=10.0)
        self.assertEqual(p.t_forecast, 5.0)
        self.assertEqual(p.t_history, 10.0)
        self.assertEqual(p.temp_factor, round(73.3 / 57.3, 3))
        self.assertAlmostEqual(p.consumption_kwh, round(10 * 73.3 / 57.3, 2))
        # 12,79 × 1,5 = 19,19 kWh -> 58,9 % + 10 = 68,9 -> 70
        self.assertEqual(p.target_soc, 70)

    def test_reason(self):
        p = self.plan(dt(12))
        self.assertIn("16:00–02:00", p.reason)
        self.assertIn("Ziel 55 %", p.reason)

    def test_ohne_folgefenster_zwoelf_stunden(self):
        windows = planner.parse_tariff("02:00-06:00=low")
        fenster = planner.WindowOccurrence(dt(2), dt(6), "low", None)
        p = self.plan(dt(1), window=fenster, windows=[w for w in windows if w.level != "low"])
        self.assertEqual(p.cover_end, dt(18))


class TestChargePower(unittest.TestCase):
    def leistung(self, **kw):
        args = dict(
            soc=50, target_soc=80, capacity_kwh=KAPAZITAET, now=dt(2), window_end=dt(6), min_w=1500, max_w=8500
        )
        args.update(kw)
        return planner.charge_power_w(**args)

    def test_ziel_kurz_vor_fensterende(self):
        # 30 % von 32,6 kWh / 0,95 = 10,29 kWh in 3:45 h = 2745 W -> 2800
        self.assertEqual(self.leistung(), 2800)

    def test_wirkungsgrad(self):
        # 9,78 kWh in 3,75 h = 2608 W -> 2700
        self.assertEqual(self.leistung(efficiency=1.0), 2700)

    def test_ziel_erreicht(self):
        self.assertEqual(self.leistung(soc=80), 0)
        self.assertEqual(self.leistung(soc=85), 0)

    def test_mindestleistung(self):
        self.assertEqual(self.leistung(soc=79), 1500)

    def test_hoechstleistung(self):
        self.assertEqual(self.leistung(soc=0, target_soc=95, now=dt(5)), 8500)

    def test_in_den_letzten_15_minuten_volle_leistung(self):
        self.assertEqual(self.leistung(soc=79, now=dt(5, 50)), 8500)
        self.assertEqual(self.leistung(soc=79, now=dt(7)), 8500)

    def test_nie_unter_pv_ueberschuss(self):
        self.assertEqual(self.leistung(pv_surplus_w=4000), 4000)
        self.assertEqual(self.leistung(pv_surplus_w=4050), 4100)
        self.assertEqual(self.leistung(pv_surplus_w=20000), 8500)

    def test_zeitzonenbehaftete_zeiten(self):
        tz = timezone(timedelta(hours=1))
        p = self.leistung(now=dt(2).replace(tzinfo=tz), window_end=dt(6).replace(tzinfo=tz))
        self.assertEqual(p, 2800)


class TestPvImFenster(unittest.TestCase):
    # Mittagsfenster 12–16 Uhr, Haus 1 kW, sonniger Tag
    PROGNOSE = [(dt(h), kw) for h, kw in [(12, 9.0), (13, 8.0), (14, 6.0), (15, 0.5)]]

    def test_surplus(self):
        profil = [1.0] * 24
        self.assertAlmostEqual(planner.surplus(profil, self.PROGNOSE, dt(12), dt(16)), 8 + 7 + 5)
        self.assertAlmostEqual(planner.surplus(profil, self.PROGNOSE, dt(13, 30), dt(16)), 3.5 + 5)
        self.assertAlmostEqual(planner.surplus(profil, [], dt(12), dt(16)), 0.0)

    def test_surplus_und_deficit_ergaenzen_sich(self):
        profil = [1.0] * 24
        pv = planner.pv_sum(self.PROGNOSE, dt(12), dt(16))
        haus = planner.hourly_sum(profil, dt(12), dt(16))
        bilanz = planner.surplus(profil, self.PROGNOSE, dt(12), dt(16)) - planner.deficit(
            profil, self.PROGNOSE, dt(12), dt(16)
        )
        self.assertAlmostEqual(bilanz, pv - haus)

    def test_grid_charge_target(self):
        # 16,3 kWh PV-Überschuss = 50 % von 32,6 kWh
        self.assertAlmostEqual(planner.grid_charge_target(55, 16.3, KAPAZITAET), 5.0)
        self.assertEqual(planner.grid_charge_target(55, 0.0, KAPAZITAET), 55)
        # PV deckt mehr als das Ziel: gar nicht aus dem Netz laden
        self.assertEqual(planner.grid_charge_target(55, 40.0, KAPAZITAET), 0.0)


class TestSommer(unittest.TestCase):
    # Sonniger Tag: Spitze von 11 bis 15 Uhr über der AC-Grenze von 12 kW
    PROGNOSE = [
        (dt(h), kw)
        for h, kw in [(9, 8.0), (10, 11.0), (11, 14.0), (12, 17.0), (13, 18.0), (14, 15.0), (15, 12.0)]
    ]

    def test_clipping(self):
        kwh, ab, bis = planner.clipping(self.PROGNOSE, dt(5), dt(0, tag=3), 12.0, 12.0)
        self.assertAlmostEqual(kwh, 2 + 5 + 6 + 3)  # 15 Uhr liegt genau auf der Grenze
        self.assertEqual((ab, bis), (dt(11), dt(15)))

    def test_clipping_nur_im_zeitraum(self):
        kwh, ab, bis = planner.clipping(self.PROGNOSE, dt(12, 30), dt(0, tag=3), 12.0, 12.0)
        self.assertAlmostEqual(kwh, 0.5 * 5 + 6 + 3)
        self.assertEqual(ab, dt(12, 30))  # laufende Spitze beginnt jetzt
        self.assertEqual(bis, dt(15))
        self.assertEqual(planner.clipping(self.PROGNOSE, dt(5), dt(11), 12.0, 12.0), (0.0, None, None))
        _, _, bis = planner.clipping(self.PROGNOSE, dt(5), dt(13, 20), 12.0, 12.0)
        self.assertEqual(bis, dt(13, 20))

    def test_clipping_begrenzt_auf_dc_ladeleistung(self):
        kwh, _, _ = planner.clipping([(dt(12), 30.0)], dt(5), dt(0, tag=3), 12.0, 12.0)
        self.assertAlmostEqual(kwh, 12.0)

    def test_kein_clipping_an_trueben_tagen(self):
        fc = [(dt(h), 6.0) for h in range(9, 17)]
        self.assertEqual(planner.clipping(fc, dt(5), dt(0, tag=3), 12.0, 12.0), (0.0, None, None))

    def test_unsortierte_prognose(self):
        _, ab, bis = planner.clipping(list(reversed(self.PROGNOSE)), dt(5), dt(0, tag=3), 12.0, 12.0)
        self.assertEqual((ab, bis), (dt(11), dt(15)))

    def test_summer_soc_ceiling(self):
        # 16,3 kWh = 50 % von 32,6 kWh, dazu 5 % Reserve
        self.assertAlmostEqual(planner.summer_soc_ceiling(16.3, KAPAZITAET, 5), 45.0)
        self.assertEqual(planner.summer_soc_ceiling(0.0, KAPAZITAET, 0), 100.0)
        self.assertEqual(planner.summer_soc_ceiling(40.0, KAPAZITAET, 5), 0.0)


    def test_deficit(self):
        # Haus 1 kW konstant, PV ab 9 Uhr: 8 kW, davor nichts
        profil = [1.0] * 24
        self.assertAlmostEqual(planner.deficit(profil, self.PROGNOSE, dt(5), dt(11)), 4.0)
        self.assertAlmostEqual(planner.deficit(profil, self.PROGNOSE, dt(5, 30), dt(9)), 3.5)
        self.assertAlmostEqual(planner.deficit(profil, self.PROGNOSE, dt(9), dt(11)), 0.0)
        self.assertAlmostEqual(planner.deficit(profil, [(dt(7), 0.4)], dt(7), dt(8)), 0.6)

    def test_peak_charge_limit(self):
        # PV 14,2 kW bei 12 kW AC: 2,2 kW + 0,5 kW Aufschlag, auf 500 W aufgerundet
        self.assertEqual(planner.peak_charge_limit_w(14.2, 12.0, 12000, 500, 500), 3000)
        self.assertEqual(planner.peak_charge_limit_w(14.0, 12.0, 12000, 500, 500), 2500)
        self.assertEqual(planner.peak_charge_limit_w(11.8, 12.0, 12000, 500, 500), 500)
        # Unter der Grenze: Ladesperre
        self.assertEqual(planner.peak_charge_limit_w(11.5, 12.0, 12000, 500, 500), 0)
        self.assertEqual(planner.peak_charge_limit_w(3.0, 12.0, 12000, 500, 500), 0)
        # Nie über die Ladeleistung des Akkus
        self.assertEqual(planner.peak_charge_limit_w(30.0, 12.0, 12000, 500, 500), 12000)

class TestWpOffset(unittest.TestCase):
    KURVE = [(0.0, 2.0), (5.0, 1.0)]

    def test_hp_base_offset(self):
        erwartet = {-3: 2.0, -0.1: 2.0, 0: 1.0, 3: 1.0, 4.9: 1.0, 5: 0.0, 12: 0.0}
        for temp, offset in erwartet.items():
            with self.subTest(temp=temp):
                self.assertEqual(planner.hp_base_offset(temp, self.KURVE), offset)

    def test_hp_base_offset_unsortierte_kurve(self):
        self.assertEqual(planner.hp_base_offset(-3, list(reversed(self.KURVE))), 2.0)

    def test_hp_base_offset_ohne_daten(self):
        self.assertEqual(planner.hp_base_offset(None, self.KURVE), 0.0)
        self.assertEqual(planner.hp_base_offset(-10, []), 0.0)

    def test_parse_curve(self):
        self.assertEqual(planner.parse_curve("0:2, 5:1"), self.KURVE)
        self.assertEqual(planner.parse_curve("−5:3, -2:1.5"), [(-5.0, 3.0), (-2.0, 1.5)])
        self.assertEqual(planner.parse_curve("abc, 1:2"), [(1.0, 2.0)])
        self.assertEqual(planner.parse_curve(""), [])

    def test_parse_model(self):
        self.assertEqual(planner.parse_model("35, 54.3, 3.2, 8"), MODELL)
        with self.assertRaises(ValueError):
            planner.parse_model("35, 54.3, 3.2")
        with self.assertRaises(ValueError):
            planner.parse_model("35, 54.3, x, 8")


class TestZielladung(unittest.TestCase):
    def setUp(self):
        self.w = planner.parse_tariff(OCTOPUS)

    def plan(self, now, bulk, top=0.0, power=11.0, top_power=11.0, puffer=15):
        return planner.ev_plan(
            now, dt(5, 30, 3), bulk, top, power, top_power, self.w, 0.27, timedelta(minutes=puffer)
        )

    def test_next_deadline(self):
        self.assertEqual(planner.next_deadline(dt(22), time(5, 30)), dt(5, 30, 3))
        self.assertEqual(planner.next_deadline(dt(4, tag=3), time(5, 30)), dt(5, 30, 3))
        self.assertEqual(planner.next_deadline(dt(5, 30, 3), time(5, 30)), dt(5, 30, 4))

    def test_spaet_im_niedrigtarif(self):
        p = self.plan(dt(22), 11)
        self.assertFalse(p.charge_now)
        self.assertEqual(p.start, dt(4, 15, 3))
        self.assertIsNone(p.top_start)

    def test_laeuft_wenn_block_erreicht(self):
        self.assertTrue(self.plan(dt(4, 15, 3), 11).charge_now)
        self.assertFalse(self.plan(dt(4, 0, 3), 11).charge_now)

    def test_guenstig_vor_spaet(self):
        # Mittags-Niedrigtarif liegt früher, der Nacht-Niedrigtarif gewinnt
        self.assertEqual(self.plan(dt(11), 11).start, dt(4, 15, 3))
        # Mehr als das Nachtfenster: der Rest in den späten Mittagsstunden
        p = self.plan(dt(11), 11 * 4.25)
        self.assertEqual(p.start, dt(15, 0))

    def test_restladung_vor_zielzeit(self):
        # 90 → 100 %: 7 kWh bei 7 kW = 1 h vor 05:30, Hauptladung 2 h davor
        p = self.plan(dt(1, tag=3), 20, top=7, power=10, top_power=7, puffer=0)
        self.assertFalse(p.charge_now)
        self.assertEqual(p.top_start, dt(4, 30, 3))
        self.assertEqual(p.start, dt(2, 30, 3))
        self.assertTrue(self.plan(dt(4, 30, 3), 0, top=7, top_power=7, puffer=0).charge_now)

    def test_zeit_knapp(self):
        p = self.plan(dt(4, tag=3), 30)
        self.assertTrue(p.charge_now)
        # Der angebrochene Block zählt nur anteilig
        self.assertTrue(self.plan(dt(4, 20, 3), 11).charge_now)

    def test_ziel_erreicht(self):
        p = self.plan(dt(22), 0)
        self.assertFalse(p.charge_now)
        self.assertEqual(p.reason, "Ziel erreicht")



class TestPreisStatistik(unittest.TestCase):
    def setUp(self):
        self.w = planner.parse_tariff(OCTOPUS)

    def test_gewichtet_nach_bezug(self):
        rows = [(dt(3), 10.0, 0.0), (dt(10), 5.0, 0.0), (dt(19), 5.0, 0.0)]
        p = planner.price_stats(rows, dt(0), dt(0, tag=3), self.w, 0.27, 0.0)
        self.assertAlmostEqual(p.kwh, 20.0)
        self.assertAlmostEqual(p.cost, 10 * 0.18 + 5 * 0.27 + 5 * 0.35)
        self.assertAlmostEqual(p.avg, p.cost / 20)

    def test_nur_ab_start_und_ohne_negative(self):
        rows = [(dt(1), 10.0, 0.0), (dt(3), 4.0, 0.0), (dt(4), -1.0, 0.0)]
        p = planner.price_stats(rows, dt(2), dt(6), self.w, 0.27, 0.0)
        self.assertAlmostEqual(p.kwh, 4.0)

    def test_grundpreis_anteilig(self):
        p = planner.price_stats([(dt(3), 10.0, 0.0)], dt(0), dt(0, tag=3), self.w, 0.27, 30.4375)
        self.assertAlmostEqual(p.base_fee, 1.0)
        self.assertAlmostEqual(p.avg_total, (1.8 + 1.0) / 10)

    def test_verlustaufschlag_nur_auf_akkuanteil(self):
        # 10 kWh im Niedrigtarif, davon 6 kWh in den Akku: 10 % Aufschlag auf 6 kWh
        p = planner.price_stats([(dt(3), 10.0, 6.0)], dt(0), dt(6), self.w, 0.27, 0.0, 10)
        self.assertAlmostEqual(p.cost, 1.8)
        self.assertAlmostEqual(p.battery_kwh, 6.0)
        self.assertAlmostEqual(p.loss_cost, 6 * 0.18 * 0.1)
        self.assertAlmostEqual(p.avg, (1.8 + 0.108) / 10)
        # Der Akkuanteil kann den Netzbezug nicht übersteigen
        p = planner.price_stats([(dt(3), 2.0, 5.0)], dt(0), dt(6), self.w, 0.27, 0.0, 10)
        self.assertAlmostEqual(p.battery_kwh, 2.0)

    def test_grid_to_battery(self):
        # Kein PV: alles, was der Akku lädt, kommt aus dem Netz
        self.assertAlmostEqual(planner.grid_to_battery(5.0, 3.0, 0.0, 2.0), 3.0)
        # PV-Überschuss lädt zuerst
        self.assertAlmostEqual(planner.grid_to_battery(1.0, 3.0, 4.0, 2.0), 1.0)
        self.assertAlmostEqual(planner.grid_to_battery(0.5, 1.0, 4.0, 2.0), 0.0)
        # Höchstens der Netzbezug
        self.assertAlmostEqual(planner.grid_to_battery(2.0, 6.0, 0.0, 1.0), 2.0)

    def test_ohne_bezug(self):
        p = planner.price_stats([], dt(0), dt(6), self.w, 0.27, 21.04)
        self.assertIsNone(p.avg)
        self.assertIsNone(p.avg_total)


if __name__ == "__main__":
    unittest.main()
