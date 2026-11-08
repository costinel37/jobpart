"""Conversie valutară simplă, cu curs față de EUR.

Sursa: tabelul fx_rates (dacă e populat), altfel valorile implicite de mai jos.
Pentru producție, un task zilnic poate prelua cursul BNR (https://www.bnr.ro/nbrfxrates.xml)
și face upsert în fx_rates.
"""
from sqlalchemy.orm import Session

import models_v2 as m2

SUPPORTED = ("EUR", "RON", "USD", "GBP")
DEFAULT_PER_EUR = {"EUR": 1.0, "RON": 4.97, "USD": 1.08, "GBP": 0.85}


def load_rates(db: Session) -> dict[str, float]:
    rates = dict(DEFAULT_PER_EUR)
    for r in db.query(m2.FxRate).all():
        rates[r.currency] = r.per_eur
    return rates


def convert_minor(amount_minor: int | None, src: str, dst: str, rates: dict[str, float]) -> int | None:
    if amount_minor is None or src == dst:
        return amount_minor
    if src not in rates or dst not in rates:
        return None
    return round(amount_minor / rates[src] * rates[dst])
