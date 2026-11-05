# CLAUDE.md – Energiemanager (E3DC)

Eigene Home-Assistant-Integration (`custom_components/energiemanager`), die die Integration **E3DC Maestro** ablösen soll. Besitzer: Thomas. Kommunikation auf **Deutsch**.

## Ziel

Steuerung von Hausakku, Wallboxen und Wärmepumpe nach Stromtarif, Wetter- und PV-Prognose:

1. Stromtarif mit mehreren Zeitfenstern (low / normal / high, je mit Preis)
2. Netzladung im Niedrigtarif auf Basis von Verbrauchshistorie, Temperaturprognose und PV-Prognose
3. Sommer: morgens Platz im Akku schaffen für die Mittags-PV
4. Wallboxsteuerung mit Modi: Aus, Sofort laden (Netz), Nur Niedrigtarif, Nur PV-Überschuss, PV-Überschuss + Niedrigtarif; dazu Zielladung (Ladestand oder kWh bis Uhrzeit)
5. Wärmepumpe im Niedrigtarif: SG-Ready „Einschaltempfehlung“ + Temperaturanhebung
6. Temperaturanhebung der Wärmepumpe abhängig von der Temperaturprognose

## Stand

- **v0.1.0**, Code komplett, aber **noch nie in einer echten HA-Instanz gelaufen**.
- Geprüft: `planner.py` mit Unit-Tests (`tests/test_planner.py`), `py_compile` und `pyflakes` sauber.
- Startet standardmäßig im **Simulationsmodus** (rechnet und zeigt an, schaltet nichts).

## Architektur

| Datei | Inhalt |
|---|---|
| `planner.py` | Reine Rechenlogik ohne HA-Importe: Tarif-Parser, Fensterberechnung, Verbrauchs-/PV-Bilanz, Ladeziel, Ladeleistung, WP-Offset. Gut unit-testbar. |
| `coordinator.py` | `DataUpdateCoordinator` (30 s): lädt Recorder-Statistik (alle 6 h), Wettervorhersage (alle 30 min), plant und steuert Akku, Wallboxen, Wärmepumpe |
| `config_flow.py` | Einrichtung in 3 Schritten (Akku/Prognosen, Tarif, Wallboxen/WP) und Options-Menü |
| `sensor.py`, `switch.py`, `number.py`, `select.py` | Entitäten. Switch/Number/Select speichern Einstellungen per Restore im `coordinator.settings` |
| `const.py` | Konfigurationsschlüssel, Defaults, Einstellungs-Entitäten |

## Thomas' Installation (HA-Prod)

**Akku / PV (E3DC S10E Pro, über Integration `e3dc_rscp`)**
- SoC: `sensor.s10e_pro_state_of_charge`
- Hausverbrauch: `sensor.s10e_pro_house_consumption` (Einheit **kW**)
- Kapazität 32,6 kWh. 12 kW AC, die Akkus können zusätzlich 12 kW DC aufnehmen.
- Dienste: `e3dc_rscp.set_power_mode` (power_mode "0"–"4", power_value W), `set_power_limits` (max_charge/max_discharge W), `clear_power_limits`, `manual_charge`, `set_wallbox_max_charge_current` – alle mit `device_id`
- PV: Hauptdach 28 Module NO (67°) + 38 Module SW (247°), je 375 W, 30° Neigung. Garagen-PV ca. 1,5 kWp, 20° Neigung. Verschattung nur im Winter.
- PV-Prognose: Solcast, `sensor.solcast_pv_forecast_prognose_heute` / `_morgen`, Attribut `detailedHourly` mit `period_start`, `pv_estimate`, `pv_estimate10`, `pv_estimate90` (stündlicher Mittelwert in kW)

**Tarif: Octopus Heat**
- low 02–06 und 12–16 Uhr (18,25 ct), high 18–21 Uhr (30,26 ct), sonst normal (25,25 ct); Grundpreis 21,04 €/Monat; seit 01.09.2026, Vertrag bis 14.02.2028
- Netzbezug-Zähler: `sensor.s10e_pro_consumption_from_grid_today` (kWh, total_increasing, täglicher Reset) – Grundlage der Ø-Strompreis-Sensoren

**Wallboxen (E3DC, über `e3dc_rscp`)** – Präfixe `garage` und `carport`
- `switch.<wb>_sun_mode`, `button.<wb>_toggle_charging`, `binary_sensor.<wb>_charging`, `binary_sensor.<wb>_plug`, `number.<wb>_max_charge_current`, `sensor.<wb>_phases`
- `sensor.<wb>_energy_all` (kWh) zählt die Energie seit dem Anstecken (steht vor dem Anstecken auf 0)
- Auto: NIO EL6, 100-kWh-Akku (etwa 90 kWh nutzbar); `sensor.el6_battery_state_of_charge`, Ladelimit im Auto `sensor.el6_maximum_state_of_charge`. Lädt an beiden Wallboxen.

**Wärmepumpe Remko (über MQTT)**
- Kälter/Wärmer-Offset: `number.remko_mqtt_kalter_warmer`
- SG-Ready über zwei Shelly-Relais: `switch.sg_ready1` (Kontakt 1), `switch.sg_ready2` (Kontakt 2)
  - Status 0 normal = aus/aus, Status 1 Sperre = an/aus, Status 3 Empfehlung = aus/an
- E3DC meldet PV-Überschuss: `sensor.s10e_pro_sg_ready` = `released`
- Leistungsmesser an der WP vorhanden

**Sonstiges**
- Wetter: `weather.forecast_home` (met.no, stündlich ca. 48 h)
- Außentemperatur: `sensor.ws2900_v2_02_03_outdoor_temperature_2`

## Designentscheidungen (mit Thomas abgestimmt)

- **Ladeziel je Niedrigtarif-Fenster** = Bedarf bis zum Beginn des nächsten Niedrigtarif-Fensters. Nachtfenster deckt 06–12 Uhr, Mittagsfenster deckt 16–02 Uhr.
- **Bedarf** = stündliches Verbrauchsprofil (Mittel der letzten 14 Tage aus der Recorder-Statistik) × Temperaturfaktor × **Sicherheitsfaktor 1,5** − PV (**Solcast P10**, pessimistisch), dann + **10 % Puffer**, begrenzt auf **25–95 %**, auf 5 % gerundet.
- **Temperaturfaktor** = Modell(T-Prognose im Deckungszeitraum) / Modell(T-Mittel Historie), begrenzt 0,7–1,5. Modell aus Thomas' Messdaten 11/2025–10/2026: Tagesverbrauch ≈ `35 + max(8; 54,3 − 3,2·T)` kWh.
- **Kein Just-in-Time.** Laden beginnt ab Fensterstart, aber mit **begrenzter Leistung**, sodass das Ziel ca. 15 min vor Fensterende erreicht wird. Das schont den Akku (steht nicht lange voll) und verhindert, dass er sich im günstigen Fenster erst leer fährt. Leistung 1500–8500 W, mittags nie unter dem aktuellen PV-Überschuss.
- **PV im Fenster** wird nicht aus dem Netz geladen: Netzladung nur bis Ziel − PV-Überschuss (PV-Prognose minus Verbrauchsprofil) von jetzt bis Fensterende, laufend neu gerechnet. Deckt die PV das Ziel, lädt der Akku im Fenster nur aus PV (an sonnigen Tagen im Mittagsfenster der Normalfall).
- Nach Erreichen des Ziels im Niedrigtarif: **Entladung gesperrt** bis Fensterende.
- Der Plan wird beim Eintritt ins Fenster **eingefroren**, außerhalb wird er als Vorschau laufend neu berechnet.
- WP-Grundoffset aus der Prognose für 07:00 am Folgetag: unter 0 °C +2 K, unter 5 °C +1 K, sonst 0. Im Niedrigtarif zusätzlich +2 K.
- **Zielladung** (Wallbox): gilt täglich, solange der Schalter an ist. Hauptmenge in den günstigsten 15-Minuten-Blöcken vor der Zielzeit, bei gleichem Preis in den spätesten, in jedem Zyklus neu gerechnet. Bei Zielen über 90 % in den günstigen Zeiten nur bis 90 %, der Rest direkt vor der Zielzeit (Wunsch von Thomas: Auto steht nicht lange auf 100 %). Rechnung mit Ladestrom × Phasen × 230 V, 90 % Wirkungsgrad, oberhalb 90 % 70 % der Leistung, 15 min Puffer. Das Ziel wird auf das Ladelimit im Auto begrenzt, sonst würde der Taster endlos umschalten. Der Ladestand aus der NIO-API kommt nur gelegentlich; dazwischen wird er mit `energy_all` fortgeschrieben.
- **Ø Strompreis** (Tag/Monat/Jahr, ab Tarifbeginn) = (Arbeitskosten + Verlustaufschlag) / Netzbezug. Verlustaufschlag: 10 % (einstellbar) auf den Netzstrom, der in den Hausakku fließt; der Anteil je Abschnitt = Akkuladung − max(0, PV − Hausverbrauch), begrenzt auf den Netzbezug. `sensor.s10e_pro_energy_charged_from_grid` taugt dafür nicht (bleibt bei Netzladung über Modus 4 auf 0). Der Hausverbrauch des S10E enthält die Wallboxen (Bilanz geht auf). Die Arbeitskosten im Attribut sind die tatsächlich bezahlten, ohne Aufschlag.
- **Sommer-Modus** richtet sich nach der Abregelung: Aus Solcast **P50** wird die Energie berechnet, die heute noch über der AC-Grenze (12 kW, einstellbar) anfällt und nur der Akku aufnehmen kann (je Stunde höchstens die DC-Ladeleistung). Ab „Sommer: Morgen ab“ lädt der Akku frei bis zur **Ladegrenze** = 100 % − Überschuss/Kapazität − Reserve (5 %). Danach begrenzt `max_charge` die Ladeleistung auf **PV-Leistung − AC-Grenze + 500 W**, auf 500-W-Stufen aufgerundet: vor der Spitze ist das 0 (Ladesperre), in der Spitze genau der Teil, der sonst abgeregelt würde. Ohne diese Begrenzung lüde der E3DC in der Spitze den gesamten Überschuss und wäre voll, bevor die Leistung über der AC-Grenze anfällt. Die Begrenzung bleibt vor der Spitze stehen (kein Takten); in der Spitze fällt sie weg, sobald der SoC mehr als 3 % unter der mitlaufenden Ladegrenze liegt, und endet mit der letzten Prognosestunde über der Grenze. Optional aktive Entladung bis Ladegrenze + Hausverbrauch bis zur Spitze (Profil minus PV-Prognose), nie unter „Sommer: Entladen bis“. Unter 0,5 kWh erwarteter Abregelung passiert nichts. Im Niedrigtarif hat die Netzladung Vorrang; die Halte-Logik (Entladesperre) bekommt die Ladebegrenzung mit dazu.

## Erfahrungen mit Maestro (warum die Ablösung)

- Maestro rechnete den Bedarf viel zu knapp (z. B. 4,1 kWh für 06–12 Uhr), der Akku war vormittags leer.
- Just-in-Time führte dazu, dass sich der Akku im Niedrigtarif zuerst entlud.
- Die Netzladung hat im Minutentakt an/aus getaktet.

## Offene Punkte / zuerst prüfen

1. **Power-Mode 4** von `e3dc_rscp.set_power_mode` – im Quellcode geprüft (hacs-e3dc `master`, Stand 25.10.2026):
   - Modus 4 ist `SetPowerMode.CHARGE_GRID` = Netzladen (0 Normal, 1 Leerlauf, 2 Entladen, 3 Laden). Gesendet wird `EMS_REQ_SET_POWER` mit Modus und Wert. Der zurückgelesene Ist-Modus (`PowerMode`) nutzt eine **andere** Nummerierung (0 Leerlauf, 1 Entladen, 2 Laden).
   - hacs-e3dc hält Modi ≠ 0 **selbst** per Timer alle 10 s (`coordinator.async_set_power_mode`). Das Gerät fällt ohne Neusenden nach ca. 10–30 s auf Normalbetrieb zurück. Unser Nachsetzen alle 20 s (`POWER_MODE_REFRESH_S`) ist damit unnötig, schadet aber nicht (kein zweiter Timer). Sinnvoll höchstens als Wächter mit längerem Intervall: Nach Neustart von HA oder Reload von `e3dc_rscp` ist deren Timer weg.
   - Modus „0“ stoppt nur den Timer und sendet nichts. Das Gerät kehrt erst nach seinem Timeout zum Normalbetrieb zurück.
   - `power_value` muss bei den Modi 2–4 > 0 sein. Eine Obergrenze prüft hacs-e3dc nicht, das muss bei uns liegen (tut `charge_power_w` mit `max_w`).
   - Noch am Gerät beobachten: hacs-e3dc-Issue #303 (Modus 4 fiel nach Minuten mit `RSCP_ERR_ALREADY_IN_USE` zurück). Ist-Modus im Sensor gegen den Sollwert prüfen.
2. **`set_power_limits` / `clear_power_limits`** – im Quellcode geprüft:
   - `max_discharge: 0` wird unverändert gesendet (nur Obergrenze wird gekappt); der Maintainer bestätigt in Issue #175, dass das die Entladung sperrt. Rückgabe „nicht optimal“ (1) erzeugt nur eine Warnung im Log.
   - Die Limits sind die **dauerhaften** Leistungseinstellungen des Geräts (Portal: „Manuell“), kein Keep-alive. Stürzt HA während der Entladesperre ab, bleibt sie stehen. Beim Start setzt unser Coordinator sie zurück (erster Befehl ohne Vorgänger → `clear_power_limits`).
   - `clear_power_limits` sendet nur `EMS_POWER_LIMITS_USED = false`. Die Firmware stellt dann **alle** Werte auf Werkseinstellung zurück, auch die Entlade-Startschwelle (Issue #403). Eigene, im E3DC-Portal gesetzte Leistungswerte gehen bei jedem Aufheben der Sperre verloren. **Mit Thomas klären**, ob er dort eigene Werte nutzt; falls ja, statt `clear_power_limits` mit `set_power_limits` und seinen Werten zurückstellen.
   - Ob ein gesetztes `max_charge` das Netzladen mit Modus 4 deckelt, ist nirgends belegt – am Gerät testen.
3. **Wallbox-Taster** `toggle_charging`: Zuverlässigkeit, Verzögerung bis `binary_sensor.<wb>_charging` nachzieht (Cooldown aktuell 180 s).
4. Recorder-Statistik: Format von `start` in `statistics_during_period` (float vs. datetime) – im Code beides abgefangen, verifizieren.
5. Mögliche Überzählung: Zählt `sensor.s10e_pro_house_consumption` die Wallbox mit? Dann verfälschen Ladevorgänge das Verbrauchsprofil.
6. Sommer-Modus noch nie an einem Tag mit Abregelung beobachtet (Sensor „Sommer: PV über AC-Grenze“, Attribut `ladeleistung_max_w`). Am Gerät prüfen:
   - Hält der E3DC die AC-Leistung bei begrenztem `max_charge` tatsächlich bei 12 kW, oder regelt er trotzdem ab? `sensor.s10e_pro_solar_production` ist die DC-Leistung des Generators; Wandlerverluste sind nicht eingerechnet (der Aufschlag von 500 W deckt sie mit ab).
   - In der Spitze schreibt der Coordinator `set_power_limits` bei jeder 500-W-Stufe neu – das sind dauerhafte Geräteeinstellungen. Wird das zu häufig, Stufe vergrößern oder eine Mindestzeit zwischen zwei Änderungen einbauen. Alternative ohne dauerhafte Einstellung wäre Power-Mode 3 (Laden mit Wert); dessen Verhalten bei zu wenig PV ist aber nicht belegt.
   - Eine Einspeisebegrenzung des Netzbetreibers ist nicht berücksichtigt (dann „Sommer: AC-Grenze“ entsprechend senken; der Hausverbrauch zählt dann nicht mehr zur Grenze).
7. Options-Flow: optionale Felder lassen sich nicht wieder leeren (Werte werden gemergt).
8. Tests: Integrationstest mit `pytest-homeassistant-custom-component` (Unit-Tests für `planner.py` liegen in `tests/test_planner.py`).

## Livegang

Seit 03.11.2026 produktiv (Simulationsmodus aus). Seit 05.11.2026 sind E3DC Maestro (Integration, Cockpit, Dashboard, HACS-Dateien) und die abgelösten Automationen für Netzlade-Ziel, SG-Ready, WP-Solltemperatur und Maestro-Entladung gelöscht; ein Zurückfallen auf den alten Stand ist nicht mehr vorgesehen. Der Energiemanager ist die einzige Steuerung für Akku, Wallboxen und Wärmepumpe.

Thomas nutzt keine eigenen Leistungswerte im E3DC-Portal; `clear_power_limits` (Werkseinstellung) ist damit in Ordnung. `number.remko_mqtt_kalter_warmer` steht nach einem HA-Neustart einige Minuten auf „unknown“; so lange schreibt der Energiemanager die Anhebung nicht.

## Arbeitsweise

- Änderungen klein halten. Nach jeder Änderung die `planner.py`-Tests laufen lassen:
  `python -m unittest discover -s tests -v` (nur Standardbibliothek, läuft auch unter pytest).
  Die Tests laden `planner.py` direkt aus der Datei, weil das Paket-`__init__` Home Assistant importiert.
- Versionsnummer in `manifest.json` erhöhen und passendes GitHub-Release anlegen, damit HACS das Update anbietet.
- Wenn der HA-MCP-Server verbunden ist: Entitäten, Logs und den Sensor „Akku-Entscheidung“ in der echten Installation prüfen, bevor der Simulationsmodus ausgeschaltet wird. Steuernde Aktionen in HA nur nach Rückfrage bei Thomas.
