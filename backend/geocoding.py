import urllib.request
import urllib.parse
import json
import logging
import time

logger = logging.getLogger(__name__)

# Cache simplu în memorie pentru a nu supraîncărca Nominatim
_cache: dict = {}
_LAST_REQUEST = 0.0


def geocodeaza_oras(oras: str, tara: str = "Romania") -> tuple[float, float] | None:
    """Returnează (lat, lng) pentru un oraș sau None dacă nu găsește."""
    cheie = f"{oras.lower()},{tara.lower()}"
    if cheie in _cache:
        return _cache[cheie]

    global _LAST_REQUEST
    # Nominatim cere max 1 request/secundă
    acum = time.time()
    if acum - _LAST_REQUEST < 1.1:
        time.sleep(1.1 - (acum - _LAST_REQUEST))
    _LAST_REQUEST = time.time()

    try:
        query = urllib.parse.urlencode({
            "q": f"{oras}, {tara}",
            "format": "json",
            "limit": 1,
            "countrycodes": "ro",
        })
        url = f"https://nominatim.openstreetmap.org/search?{query}"
        req = urllib.request.Request(url, headers={"User-Agent": "JobPart-App/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            date = json.loads(r.read())

        if date:
            lat = float(date[0]["lat"])
            lng = float(date[0]["lon"])
            _cache[cheie] = (lat, lng)
            return lat, lng

    except Exception as e:
        logger.warning(f"Geocodare eșuată pentru '{oras}': {e}")

    _cache[cheie] = None
    return None


def distanta_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Distanța Haversine între două coordonate în km."""
    from math import radians, sin, cos, sqrt, atan2
    R = 6371
    dlat = radians(lat2 - lat1)
    dlng = radians(lng2 - lng1)
    a = sin(dlat/2)**2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlng/2)**2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))
