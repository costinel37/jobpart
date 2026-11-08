"""
Catalogul de planuri JobPart v2.

Model de business: JobPart este DOAR intermediar (job board).
- Candidații folosesc platforma GRATUIT, mereu. Nu percepem nicio taxă de la persoanele care
  își caută un loc de muncă (nici „premium”, nici „urgent”).
- Angajatorii plătesc un abonament pentru serviciul de publicitate/recrutare.
- JobPart NU procesează salarii și NU intermediază plata muncii: angajatorul plătește
  candidatul direct, în baza contractului încheiat între ei, în afara platformei.

Prețurile sunt în cenți EUR, fără TVA (B2B). ID-urile de preț Stripe vin din variabile de mediu.
"""
import os
from dataclasses import dataclass
from typing import Optional

TRIAL_DAYS = 30          # prima lună gratuită pentru angajatori
GRACE_DAYS = 3           # după o plată eșuată, accesul mai ține 3 zile
JOB_VALIDITY_DAYS = 30   # înlocuiește vechiul ZILE_GRATUIT = 365


@dataclass(frozen=True)
class Plan:
    code: str
    audience: str                       # employer / candidate / any
    name: str
    price_eur_cents: int
    max_active_jobs: Optional[int]      # None = nelimitat, 0 = nu poate posta
    job_validity_days: int
    auto_refresh_days: Optional[int]    # None = fără refresh automat
    cv_database: bool                   # acces la CV-urile pe care candidații le-au făcut vizibile
    stripe_price_env: Optional[str] = None

    @property
    def stripe_price_id(self) -> Optional[str]:
        return os.getenv(self.stripe_price_env) if self.stripe_price_env else None

    def public(self) -> dict:
        return {
            "code": self.code, "audience": self.audience, "name": self.name,
            "price_eur": self.price_eur_cents / 100,
            "price_note": "+ TVA" if self.price_eur_cents else "",
            "max_active_jobs": self.max_active_jobs,
            "job_validity_days": self.job_validity_days,
            "auto_refresh_days": self.auto_refresh_days,
            "cv_database": self.cv_database,
            "purchasable": self.stripe_price_env is not None,
        }


PLANS: dict[str, Plan] = {p.code: p for p in [
    # Luna gratuită pentru angajatori — acces complet
    Plan("trial", "employer", "Trial 30 zile", 0, None, JOB_VALIDITY_DAYS, 7, True),
    # După trial, fără plată: poate vedea aplicările existente, dar nu poate posta joburi noi
    Plan("employer_free", "employer", "Fără abonament", 0, 0, JOB_VALIDITY_DAYS, None, False),
    Plan("employer_basic", "employer", "Basic", 1900, 3, JOB_VALIDITY_DAYS, None, False, "STRIPE_PRICE_EMPLOYER_BASIC"),
    Plan("employer_pro", "employer", "Pro", 4900, None, JOB_VALIDITY_DAYS, 7, True, "STRIPE_PRICE_EMPLOYER_PRO"),
    # Candidați — gratuit mereu, fără nicio opțiune plătită
    Plan("candidate_free", "candidate", "Gratuit", 0, 0, JOB_VALIDITY_DAYS, None, False),
]}


def is_candidate(rol: str) -> bool:
    return rol == "candidat"


def free_plan_for_role(rol: str) -> Plan:
    return PLANS["candidate_free" if is_candidate(rol) else "employer_free"]


def purchasable_plans(rol: str) -> list[Plan]:
    if is_candidate(rol):
        return []
    return [p for p in PLANS.values() if p.audience == "employer" and p.stripe_price_env]
