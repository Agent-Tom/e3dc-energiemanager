"""Reine Rechenlogik: Tarife, Verbrauchs- und PV-Bilanz, Ladeziel.

Keine Home-Assistant-Importe, damit sich alles isoliert testen lässt.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta
import math

LOW, NORMAL, HIGH = "low", "normal", "high"


# ---------------------------------------------------------------- Tarife
@dataclass(frozen=True)
class TariffWindow:
    start: time
    end: time
    level: str
    price: float | None = None

    @property
    def duration(self) -> timedelta:
        s = self.start.hour * 60 + self.start.minute
        e = self.end.hour * 60 + self.end.minute
        if e <= s:
            e += 24 * 60
        return timedelta(minutes=e - s)


@dataclass(frozen=True)
class WindowOccurrence:
    start: datetime
    end: datetime
    level: str
    price: float | None

    @property
    def key(self) -> str:
        return self.start.isoformat()


def _parse_time(txt: str) -> time:
    h, m = txt.strip().split(":")
    h_i, m_i = int(h), int(m)
    if h_i == 24 and m_i == 0:
        return time(0, 0)
    return time(h_i, m_i)


def parse_tariff(text: str) -> list[TariffWindow]:
    """'02:00-06:00=low@0.18; 18:00-21:00=high@0.35' -> Fenster."""
    windows: list[TariffWindow] = []
    for part in text.replace("\n", ";").split(";"):
        part = part.strip()
        if not part:
            continue
        span, _, rest = part.partition("=")
        level, _, price = rest.partition("@")
        level = level.strip().lower() or LOW
        if level not in (LOW, NORMAL, HIGH):
            raise ValueError(f"Unbekannte Tarifstufe '{level}'")
        a, b = span.split("-")
        windows.append(
            TariffWindow(
                _parse_time(a),
                _parse_time(b),
                level,
                float(price.replace(",", ".")) if price.strip() else None,
            )
        )
    return windows


def occurrences(
    windows: list[TariffWindow], around: datetime, days_back: int = 1, days_ahead: int = 3
) -> list[WindowOccurrence]:
    out: list[WindowOccurrence] = []
    base = around.replace(hour=0, minute=0, second=0, microsecond=0)
    for d in range(-days_back, days_ahead + 1):
        day = base + timedelta(days=d)
        for w in windows:
            st = day.replace(hour=w.start.hour, minute=w.start.minute)
            out.append(WindowOccurrence(st, st + w.duration, w.level, w.price))
    out.sort(key=lambda o: o.start)
    return out


def current_window(windows: list[TariffWindow], now: datetime) -> WindowOccurrence | None:
    for o in occurrences(windows, now):
        if o.start <= now < o.end:
            return o
    return None


def current_level(windows: list[TariffWindow], now: datetime) -> str:
    o = current_window(windows, now)
    return o.level if o else NORMAL


def current_price(windows: list[TariffWindow], now: datetime, normal_price: float) -> float:
    o = current_window(windows, now)
    if o and o.price is not None:
        return o.price
    return normal_price


def next_low_after(windows: list[TariffWindow], t: datetime) -> WindowOccurrence | None:
    for o in occurrences(windows, t):
        if o.level == LOW and o.start >= t:
            return o
    return None


def relevant_low_window(windows: list[TariffWindow], now: datetime) -> WindowOccurrence | None:
    """Laufendes Niedrigtarif-Fenster oder das nächste."""
    for o in occurrences(windows, now):
        if o.level == LOW and o.end > now:
            return o
    return None


# ---------------------------------------------------------------- Bilanz
def hourly_sum(profile_kw: list[float], start: datetime, end: datetime) -> float:
    """Energie (kWh) aus einem 24-h-Leistungsprofil (kW je Stunde) über [start, end)."""
    total = 0.0
    t = start
    while t < end:
        nxt = min(end, t.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        frac = (nxt - t).total_seconds() / 3600
        total += profile_kw[t.hour] * frac
        t = nxt
    return total


def pv_sum(forecast: list[tuple[datetime, float]], start: datetime, end: datetime) -> float:
    """PV-Energie (kWh) aus stündlichen Mittelwerten (kW) mit Startzeit, anteilig."""
    total = 0.0
    for p_start, kw in forecast:
        p_end = p_start + timedelta(hours=1)
        a, b = max(p_start, start), min(p_end, end)
        if b > a:
            total += kw * (b - a).total_seconds() / 3600
    return total


def mean_temp(forecast: list[tuple[datetime, float]], start: datetime, end: datetime) -> float | None:
    vals = [t for (d, t) in forecast if start <= d < end]
    return sum(vals) / len(vals) if vals else None


def hp_daily_model(temp: float, model: tuple[float, float, float, float]) -> float:
    base, a, b, min_hp = model
    return base + max(min_hp, a - b * temp)


def temp_correction(
    t_forecast: float | None, t_history: float | None, model: tuple[float, float, float, float]
) -> float:
    if t_forecast is None or t_history is None:
        return 1.0
    f = hp_daily_model(t_forecast, model) / hp_daily_model(t_history, model)
    return max(0.7, min(1.5, f))


@dataclass
class ChargePlan:
    window_key: str
    window_start: datetime
    window_end: datetime
    cover_start: datetime
    cover_end: datetime
    consumption_kwh: float
    temp_factor: float
    pv_kwh: float
    need_kwh: float
    target_soc: int
    t_forecast: float | None = None
    t_history: float | None = None
    reason: str = ""
    details: dict = field(default_factory=dict)


def build_plan(
    *,
    window: WindowOccurrence,
    windows: list[TariffWindow],
    profile_kw: list[float],
    pv_forecast: list[tuple[datetime, float]],
    temp_forecast: list[tuple[datetime, float]],
    t_history: float | None,
    hp_model: tuple[float, float, float, float],
    capacity_kwh: float,
    safety: float,
    buffer_pct: float,
    min_soc: float,
    max_soc: float,
) -> ChargePlan:
    cover_start = window.end
    nxt = next_low_after(windows, window.end)
    cover_end = nxt.start if nxt else cover_start + timedelta(hours=12)

    t_fc = mean_temp(temp_forecast, cover_start, cover_end)
    tf = temp_correction(t_fc, t_history, hp_model)
    cons = hourly_sum(profile_kw, cover_start, cover_end) * tf
    pv = pv_sum(pv_forecast, cover_start, cover_end)
    need = max(cons * safety - pv, 0.0)
    raw = need / capacity_kwh * 100 + buffer_pct
    target = int(round(raw / 5) * 5)
    target = int(max(min_soc, min(max_soc, target)))
    reason = (
        f"Deckung {cover_start:%H:%M}–{cover_end:%H:%M}: Verbrauch {cons:.1f} kWh "
        f"(Temp.-Faktor {tf:.2f}) × {safety:.2f} − PV {pv:.1f} kWh = {need:.1f} kWh "
        f"→ Ziel {target} %"
    )
    return ChargePlan(
        window_key=window.key,
        window_start=window.start,
        window_end=window.end,
        cover_start=cover_start,
        cover_end=cover_end,
        consumption_kwh=round(cons, 2),
        temp_factor=round(tf, 3),
        pv_kwh=round(pv, 2),
        need_kwh=round(need, 2),
        target_soc=target,
        t_forecast=None if t_fc is None else round(t_fc, 1),
        t_history=None if t_history is None else round(t_history, 1),
        reason=reason,
    )


def charge_power_w(
    *,
    soc: float,
    target_soc: float,
    capacity_kwh: float,
    now: datetime,
    window_end: datetime,
    min_w: float,
    max_w: float,
    pv_surplus_w: float = 0.0,
    efficiency: float = 0.95,
    finish_margin: timedelta = timedelta(minutes=15),
) -> int:
    """Leistung so wählen, dass das Ziel kurz vor Fensterende erreicht wird."""
    energy_kwh = max(target_soc - soc, 0) / 100 * capacity_kwh / efficiency
    if energy_kwh <= 0:
        return 0
    hours = (window_end - finish_margin - now).total_seconds() / 3600
    p = max_w if hours <= 0.05 else energy_kwh / hours * 1000
    p = max(p, pv_surplus_w, min_w)
    p = min(p, max_w)
    return int(math.ceil(p / 100) * 100)


# ---------------------------------------------------------------- Sommer
def clipping(
    forecast: list[tuple[datetime, float]],
    start: datetime,
    end: datetime,
    ac_limit_kw: float,
    max_charge_kw: float,
) -> tuple[float, datetime | None, datetime | None]:
    """PV-Energie (kWh) über der AC-Grenze, die nur der Akku aufnehmen kann.

    Liefert (Energie, Beginn, Ende der Überschreitung im Zeitraum [start, end)). Je
    Stunde zählt höchstens die DC-Ladeleistung des Akkus; darüber wird ohnehin
    abgeregelt. Der Hausverbrauch hängt an der AC-Seite und verringert den
    Überschuss nicht.
    """
    total = 0.0
    first: datetime | None = None
    last: datetime | None = None
    for p_start, kw in sorted(forecast):
        excess = min(kw - ac_limit_kw, max_charge_kw)
        if excess <= 0:
            continue
        a, b = max(p_start, start), min(p_start + timedelta(hours=1), end)
        if b <= a:
            continue
        total += excess * (b - a).total_seconds() / 3600
        if first is None:
            first = a
        last = b
    return total, first, last


def summer_soc_ceiling(clip_kwh: float, capacity_kwh: float, reserve_pct: float) -> float:
    """Höchster SoC vor der Mittagsspitze, bei dem der Akku sie noch aufnehmen kann."""
    return max(0.0, min(100.0, 100 - clip_kwh / capacity_kwh * 100 - reserve_pct))



def _net_kw(
    profile_kw: list[float], forecast: list[tuple[datetime, float]], start: datetime, end: datetime
) -> list[tuple[float, float]]:
    """(Stundenanteil, PV − Haus in kW) je angebrochener Stunde in [start, end)."""
    pv = {p.replace(minute=0, second=0, microsecond=0): kw for p, kw in forecast}
    out = []
    t = start
    while t < end:
        hour = t.replace(minute=0, second=0, microsecond=0)
        nxt = min(end, hour + timedelta(hours=1))
        out.append(((nxt - t).total_seconds() / 3600, pv.get(hour, 0.0) - profile_kw[t.hour]))
        t = nxt
    return out


def deficit(profile_kw: list[float], forecast: list[tuple[datetime, float]], start: datetime, end: datetime) -> float:
    """Energie (kWh), die der Akku in [start, end) abgibt, solange PV das Haus nicht deckt."""
    return sum(frac * max(0.0, -net) for frac, net in _net_kw(profile_kw, forecast, start, end))


def surplus(profile_kw: list[float], forecast: list[tuple[datetime, float]], start: datetime, end: datetime) -> float:
    """PV-Energie (kWh) über dem Hausverbrauch in [start, end), die in den Akku gehen kann."""
    return sum(frac * max(0.0, net) for frac, net in _net_kw(profile_kw, forecast, start, end))


def grid_charge_target(target_soc: float, pv_surplus_kwh: float, capacity_kwh: float) -> float:
    """SoC, bis zu dem aus dem Netz geladen wird; den Rest bis zum Ziel bringt die PV im Fenster."""
    return max(0.0, target_soc - pv_surplus_kwh / capacity_kwh * 100)


def peak_charge_limit_w(pv_kw: float, ac_limit_kw: float, max_w: int, margin_w: int, step_w: int) -> int:
    """Ladeleistung, die nur den PV-Anteil über der AC-Grenze in den Akku lässt.

    Mit Aufschlag und auf volle Stufen aufgerundet, damit nichts abgeregelt wird und
    die dauerhaften Leistungsgrenzen nicht bei jeder Wolke neu geschrieben werden.
    """
    need = (pv_kw - ac_limit_kw) * 1000 + margin_w
    if need <= 0:
        return 0
    return min(max_w, math.ceil(need / step_w) * step_w)

def hp_base_offset(temp: float | None, curve: list[tuple[float, float]]) -> float:
    """curve: [(Schwelle °C, Anhebung K)], z. B. [(0, 2), (5, 1)]: unter 0 °C +2, unter 5 °C +1."""
    if temp is None:
        return 0.0
    for thr, val in sorted(curve):
        if temp < thr:
            return val
    return 0.0


def parse_curve(text: str) -> list[tuple[float, float]]:
    out = []
    for part in text.split(","):
        if ":" in part:
            a, b = part.split(":")
            out.append((float(a.strip().replace("−", "-")), float(b.strip())))
    return out


def parse_model(text: str) -> tuple[float, float, float, float]:
    vals = [float(x.strip()) for x in text.split(",")]
    if len(vals) != 4:
        raise ValueError("Modell braucht 4 Werte: base, a, b, min")
    return tuple(vals)  # type: ignore[return-value]


# ---------------------------------------------------------------- E-Auto
EV_SLOT = timedelta(minutes=15)


def next_deadline(now: datetime, at: time) -> datetime:
    """Nächster Zeitpunkt mit der Uhrzeit `at` nach `now` (heute oder morgen)."""
    d = now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    return d if d > now else d + timedelta(days=1)


@dataclass(frozen=True)
class EvPlan:
    charge_now: bool
    start: datetime | None  # erster geplanter Block der Hauptladung
    top_start: datetime | None  # Beginn der Restladung vor der Zielzeit
    reason: str


def ev_plan(
    now: datetime,
    deadline: datetime,
    bulk_kwh: float,
    top_kwh: float,
    power_kw: float,
    top_power_kw: float,
    windows: list[TariffWindow],
    normal_price: float,
    buffer: timedelta = timedelta(0),
) -> EvPlan:
    """Zielladung: Hauptmenge in den günstigsten 15-Minuten-Blöcken, bei gleichem
    Preis in den spätesten; die Restmenge (top) direkt vor der Zielzeit.

    Wird in jedem Zyklus neu gerechnet. Weil die spätesten Blöcke gewählt werden,
    rutscht der laufende Block erst in die Auswahl, wenn er gebraucht wird.
    """
    if bulk_kwh <= 0 and top_kwh <= 0:
        return EvPlan(False, None, None, "Ziel erreicht")
    end = deadline - buffer
    top_start = end - timedelta(hours=top_kwh / top_power_kw) if top_kwh > 0 else end
    top = top_start if top_kwh > 0 else None
    if now >= top_start:
        reason = "Restladung bis zur Zielzeit" if bulk_kwh <= 0 else "Zeit knapp: lädt durchgehend"
        return EvPlan(True, None, top, reason)

    # Blöcke bis zum Beginn der Restladung; der erste und letzte nur anteilig
    slots: list[tuple[datetime, float]] = []
    s = now.replace(minute=now.minute - now.minute % 15, second=0, microsecond=0)
    while s < top_start:
        hours = (min(s + EV_SLOT, top_start) - max(s, now)).total_seconds() / 3600
        slots.append((s, hours))
        s += EV_SLOT
    need_h = bulk_kwh / power_kw if bulk_kwh > 0 else 0.0
    if need_h >= sum(h for _, h in slots):
        return EvPlan(True, slots[0][0] if slots else None, top, "Zeit knapp: lädt durchgehend")

    chosen: list[datetime] = []
    got = 0.0
    for s, h in sorted(slots, key=lambda x: (current_price(windows, x[0], normal_price), -x[0].timestamp())):
        if got >= need_h:
            break
        chosen.append(s)
        got += h
    start = min(chosen) if chosen else None
    now_slot = slots[0][0]
    if now_slot in chosen:
        return EvPlan(True, start, top, "Hauptladung im günstigen Zeitraum")
    if start is None:
        return EvPlan(False, None, top, "Restladung kurz vor der Zielzeit")
    return EvPlan(False, start, top, "wartet auf günstigen Zeitraum")


# ---------------------------------------------------------------- Strompreis-Statistik
@dataclass(frozen=True)
class PriceStats:
    kwh: float
    cost: float  # Arbeitspreis
    base_fee: float  # anteiliger Grundpreis

    @property
    def avg(self) -> float | None:
        """Ø Arbeitspreis je kWh Netzbezug."""
        return self.cost / self.kwh if self.kwh > 0 else None

    @property
    def avg_total(self) -> float | None:
        """Ø Preis je kWh Netzbezug einschließlich Grundpreis."""
        return (self.cost + self.base_fee) / self.kwh if self.kwh > 0 else None


def price_stats(
    rows: list[tuple[datetime, float]],
    start: datetime,
    now: datetime,
    windows: list[TariffWindow],
    normal_price: float,
    base_fee_month: float,
) -> PriceStats:
    """Netzbezug und Kosten ab `start`.

    rows: (Beginn, kWh) je Abschnitt, stündlich oder feiner; jeder Abschnitt
    kostet den Tarifpreis zu seinem Beginn. Der Grundpreis zählt anteilig nach
    Zeit (Monatspreis × 12 / 365,25 je Tag).
    """
    kwh = cost = 0.0
    for t, e in rows:
        if t < start or e <= 0:
            continue
        kwh += e
        cost += e * current_price(windows, t, normal_price)
    days = max(0.0, (now - start).total_seconds() / 86400)
    return PriceStats(round(kwh, 3), round(cost, 4), round(base_fee_month * 12 / 365.25 * days, 4))
