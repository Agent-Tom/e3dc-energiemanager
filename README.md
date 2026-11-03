# Energiemanager (E3DC) für Home Assistant

Eigene Integration zur Steuerung von E3DC-Hausakku, E3DC-Wallboxen und einer SG-Ready-Wärmepumpe nach Stromtarif, Wetter- und PV-Prognose.

## Funktionen

- **Stromtarif mit mehreren Zeitfenstern** (Stufen `low`, `normal`, `high`, je mit Preis)
- **Netzladung im Niedrigtarif**: Ziel-SoC aus stündlichem Verbrauchsprofil (Recorder-Statistik), Temperaturkorrektur nach Wärmepumpen-Modell und Solcast-Prognose für den Zeitraum bis zum nächsten Niedrigtarif-Fenster. Was die PV bis Fensterende über den Hausverbrauch hinaus liefert, wird nicht aus dem Netz geladen. Die Ladeleistung wird so gewählt, dass das Ziel erst kurz vor Fensterende erreicht wird.
- **Akku im Niedrigtarif halten**: Entladung gesperrt, das Haus läuft günstig aus dem Netz.
- **Sommer-Modus**: Sagt die PV-Prognose für heute Leistung über der AC-Grenze voraus, lädt der Akku morgens nur bis zu einer Ladegrenze und bleibt dann bis zur Spitze gesperrt (optional aktive Entladung, unter Berücksichtigung des Hausverbrauchs bis dahin). In der Spitze nimmt der Akku nur die PV-Leistung über der AC-Grenze auf, der Rest wird eingespeist. So ist mittags genau so viel Platz frei, wie sonst abgeregelt würde. Der Sensor „Sommer: PV über AC-Grenze“ zeigt die erwartete Energie, Beginn und Ende der Spitze, die Ladegrenze und die aktuelle Ladebegrenzung.
- **Wallboxen** (E3DC RSCP) mit je einem Modus: Aus, Sofort laden, Nur Niedrigtarif, PV-Überschuss + Niedrigtarif.
- **Wärmepumpe**: SG-Ready „Einschaltempfehlung“ im Niedrigtarif und bei PV-Überschuss, optional Sperre im Hochtarif. Kälter/Wärmer-Anhebung nach Temperaturprognose plus Boost im Niedrigtarif.

## Voraussetzungen

- Integration **E3DC Remote Storage Control Protocol** (`e3dc_rscp`)
- **Solcast PV Forecast** (Sensoren mit Attribut `detailedHourly`)
- Eine Wetter-Entität mit stündlicher Vorhersage
- Recorder mit Langzeitstatistik für den Hausverbrauchssensor

## Installation über HACS

1. HACS → ⋮ → Benutzerdefinierte Repositories → URL dieses Repos, Typ „Integration“
2. „Energiemanager (E3DC)“ herunterladen, Home Assistant neu starten
3. Einstellungen → Geräte & Dienste → Integration hinzufügen → Energiemanager

## Tarif-Format

```
02:00-06:00=low@0.18; 12:00-16:00=low@0.18; 18:00-21:00=high@0.35
```

Zeiten außerhalb der Fenster gelten als `normal` mit dem Normalpreis.

## Erste Inbetriebnahme – wichtig

Der **Simulationsmodus ist nach der Installation eingeschaltet**. Die Integration rechnet dann alles und zeigt ihre Entscheidungen im Sensor „Akku-Entscheidung“ an, schaltet aber nichts. Erst wenn die Entscheidungen ein paar Tage plausibel aussehen, den Simulationsmodus ausschalten.

Vorher alle anderen Steuerungen abschalten, die dieselben Geräte bedienen, sonst arbeiten sie gegeneinander, zum Beispiel:

- E3DC Maestro: „Regelung aktiv“ aus
- Automationen für Netzlade-Ziel, SG-Ready und Wärmepumpen-Solltemperatur

## Wichtige Entitäten

| Entität | Bedeutung |
|---|---|
| Sensor „Netzlade-Ziel“ | Ziel-SoC des laufenden oder nächsten Niedrigtarif-Fensters, Attribute mit der Rechnung |
| Sensor „Akku-Entscheidung“ | Was gerade mit dem Akku passiert und warum |
| Sensor „Netzladeleistung“ | Aktuelle Netzladeleistung |
| Select „Wallbox … Modus“ | Lademodus je Wallbox |
| Schalter „Simulationsmodus“ | Nur rechnen, nichts schalten |

## Hinweise zur E3DC-Ansteuerung

- Netzladung: `e3dc_rscp.set_power_mode` mit Modus 4 (Netzladen), wird alle 20 s erneuert.
- Entladesperre und Ladesperre: `e3dc_rscp.set_power_limits`, aufgehoben mit `clear_power_limits`.
- Beim Entladen der Integration oder beim Ausschalten von „Regelung aktiv“ wird der Akku wieder dem E3DC überlassen (Modus 0, Grenzen gelöscht).

## Wärmepumpen-Modell

Tagesverbrauch ≈ `base + max(min, a − b·T)`, Standard `35, 54.3, 3.2, 8`. Der Temperaturfaktor ist `Modell(T Prognose) / Modell(T Historie)`, begrenzt auf 0,7–1,5.
