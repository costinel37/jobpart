"""
Time-Matching: compară disponibilitatea candidatului cu turele jobului, în fusuri orare diferite.

Ideea: totul se proiectează pe o "săptămână UTC" de 10 080 de minute (7 × 1440), cu ancora
Luni 00:00 UTC din săptămâna curentă. Fiecare interval local (ex. Luni 18:00–22:00 la București)
devine unul sau două intervale UTC (două dacă trece peste granița săptămânii).
Folosim săptămâna CURENTĂ ca referință, deci ora de vară/iarnă e corectă pentru ce vede utilizatorul acum.
"""
from datetime import date, datetime, time, timedelta, timezone
from functools import lru_cache
from math import asin, cos, radians, sin, sqrt
from typing import Iterable, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

WEEK = 7 * 1440
Interval = tuple[int, int]  # [start, end) în minute din săptămâna UTC


@lru_cache(maxsize=256)
def tz(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def is_valid_tz(name: str) -> bool:
    try:
        ZoneInfo(name)
        return True
    except (ZoneInfoNotFoundError, ValueError):
        return False


def week_anchor(now: Optional[datetime] = None) -> date:
    """Data de Luni (UTC) a săptămânii curente."""
    now = now or datetime.now(timezone.utc)
    d = now.astimezone(timezone.utc).date()
    return d - timedelta(days=d.weekday())


def to_utc_intervals(slots: Iterable[tuple[int, int, int]], tz_name: str,
                     anchor: Optional[date] = None) -> list[Interval]:
    """slots = [(weekday, start_min, end_min)] în ora locală → intervale UTC, sortate și unite."""
    anchor = anchor or week_anchor()
    zone = tz(tz_name)
    anchor_utc = datetime.combine(anchor, time(0), timezone.utc)
    out: list[Interval] = []
    for weekday, start, end in slots:
        day = anchor + timedelta(days=weekday)
        local_start = datetime.combine(day, time(0), zone) + timedelta(minutes=start)
        offset = int((local_start.astimezone(timezone.utc) - anchor_utc).total_seconds() // 60)
        length = end - start
        s = offset % WEEK
        e = s + length
        if e <= WEEK:
            out.append((s, e))
        else:  # trece peste Duminică 24:00 UTC → se împarte în două
            out.append((s, WEEK))
            out.append((0, e - WEEK))
    return merge(out)


def merge(intervals: list[Interval]) -> list[Interval]:
    res: list[Interval] = []
    for s, e in sorted(intervals):
        if res and s <= res[-1][1]:
            res[-1] = (res[-1][0], max(res[-1][1], e))
        else:
            res.append((s, e))
    return res


def overlap_minutes(a: list[Interval], b: list[Interval]) -> int:
    """Intersecția a două liste sortate și unite (two-pointer, O(n+m))."""
    i = j = total = 0
    while i < len(a) and j < len(b):
        lo, hi = max(a[i][0], b[j][0]), min(a[i][1], b[j][1])
        if lo < hi:
            total += hi - lo
        if a[i][1] < b[j][1]:
            i += 1
        else:
            j += 1
    return total


def total_minutes(intervals: list[Interval]) -> int:
    return sum(e - s for s, e in intervals)


def coverage(job_utc: list[Interval], cand_utc: list[Interval]) -> tuple[float, int, int]:
    """Cât % din turele jobului acoperă candidatul. Job fără ture = flexibil = 100%."""
    required = total_minutes(job_utc)
    if required == 0:
        return 1.0, 0, 0
    ov = overlap_minutes(job_utc, cand_utc)
    return ov / required, ov, required


def utc_intervals_to_local(intervals: list[Interval], tz_name: str,
                           anchor: Optional[date] = None) -> list[dict]:
    """Inversul: intervale UTC → [{weekday, start, end}] în ora privitorului (pentru afișare)."""
    anchor = anchor or week_anchor()
    zone = tz(tz_name)
    anchor_utc = datetime.combine(anchor, time(0), timezone.utc)
    res = []
    for s, e in intervals:
        ls = (anchor_utc + timedelta(minutes=s)).astimezone(zone)
        le = (anchor_utc + timedelta(minutes=e)).astimezone(zone)
        # tăiem la miezul nopții locale, ca fiecare bucată să fie într-o singură zi
        cur = ls
        while cur < le:
            midnight = datetime.combine(cur.date() + timedelta(days=1), time(0), zone)
            stop = min(le, midnight)
            res.append({
                "weekday": cur.weekday(),
                "start": cur.hour * 60 + cur.minute,
                "end": 1440 if stop == midnight else stop.hour * 60 + stop.minute,
            })
            cur = stop
    return sorted(res, key=lambda x: (x["weekday"], x["start"]))


# Codul Muncii — minori (16–17 ani): max. 6h/zi, 30h/săpt. (art. 112), fără muncă de noapte 22:00–06:00 (art. 128)
MINOR_MAX_DAY_MIN = 6 * 60
MINOR_MAX_WEEK_MIN = 30 * 60
NIGHT = ((0, 6 * 60), (22 * 60, 1440))


def is_minor_safe(local_shifts: Iterable[tuple[int, int, int]]) -> bool:
    """Turele în ora locală a jobului respectă limitele legale pentru minori?
    Program flexibil (fără ture) = permis; angajatorul răspunde de programul efectiv."""
    per_day: dict[int, int] = {}
    for weekday, start, end in local_shifts:
        if any(start < ne and end > ns for ns, ne in NIGHT):
            return False
        per_day[weekday] = per_day.get(weekday, 0) + (end - start)
    return all(v <= MINOR_MAX_DAY_MIN for v in per_day.values()) and sum(per_day.values()) <= MINOR_MAX_WEEK_MIN


def tz_diff_hours(tz_a: str, tz_b: str, now: Optional[datetime] = None) -> float:
    """Câte ore e tz_b înaintea lui tz_a acum (ex. București vs New York = -7)."""
    now = now or datetime.now(timezone.utc)
    off_a = now.astimezone(tz(tz_a)).utcoffset() or timedelta(0)
    off_b = now.astimezone(tz(tz_b)).utcoffset() or timedelta(0)
    return (off_b - off_a).total_seconds() / 3600


# ─────────────────────────── navetă ───────────────────────────

def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    dlat, dlng = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng / 2) ** 2
    return 6371 * 2 * asin(sqrt(a))


# Factorii de ocol transformă distanța în linie dreaptă în distanță reală pe străzi.
COMMUTE_PROFILES = {
    "walk":    {"speed_kmh": 4.8,  "detour": 1.30, "overhead_min": 0},
    "transit": {"speed_kmh": 18.0, "detour": 1.40, "overhead_min": 7},   # 7 min = mers la stație + așteptare
}


def commute_minutes(km: float, mode: str = "transit") -> int:
    """Estimare (fără API de rutare). Pentru transit, distanțele foarte scurte se fac pe jos."""
    walk = COMMUTE_PROFILES["walk"]
    walk_min = km * walk["detour"] / walk["speed_kmh"] * 60
    if mode == "walk":
        return round(walk_min)
    p = COMMUTE_PROFILES["transit"]
    transit_min = km * p["detour"] / p["speed_kmh"] * 60 + p["overhead_min"]
    return round(min(walk_min, transit_min))


def max_km_for_minutes(max_min: int, mode: str) -> float:
    w = COMMUTE_PROFILES["walk"]
    walk_km = max_min * w["speed_kmh"] / 60 / w["detour"]
    if mode == "walk":
        return walk_km
    p = COMMUTE_PROFILES["transit"]
    return max(walk_km, max(0, max_min - p["overhead_min"]) * p["speed_kmh"] / 60 / p["detour"])


def bbox_for_minutes(lat: float, max_min: int, mode: str) -> tuple[float, float]:
    """Pre-filtru SQL ieftin: distanța maximă posibilă în max_min minute → (Δlat, Δlng) în grade."""
    km = max_km_for_minutes(max_min, mode)
    return km / 111.0, km / (111.0 * max(cos(radians(lat)), 0.01))
