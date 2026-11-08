"""
Abonamente pentru ANGAJATORI: trial 30 zile → tarif, drepturi (entitlements), limite de postare.
Candidații nu au abonament: platforma e gratuită pentru ei, mereu.

Activare: abonamentele se aplică DOAR când în mediu sunt setate
    BILLING_ENFORCED=1  și  STRIPE_SECRET_KEY
Până atunci, angajatorii au acces complet (ca înainte), fără trial pornit și fără blocări —
altfel ar fi blocați după 30 de zile fără nicio modalitate de plată.

Mașina de stări (Subscription.status):

    (prim acces după activare) ──► trialing ──(trial expirat, fără card)──► free
                                      │
                                      └──(checkout Stripe)──► trialing* ──(final trial, plată OK)──► active
    active ──(plată eșuată)──► past_due ──(3 zile)──► free
    active ──(anulare)──► canceled ──(final perioadă plătită)──► free

    * Nu se taxează nimic până la finalul lunii gratuite.
"""
import os
from datetime import datetime, timedelta
from typing import Optional

from fastapi import Depends, HTTPException
from sqlalchemy.orm import Session

import models
import models_v2 as m2
from auth import get_user_curent
from database import get_db
from plans import GRACE_DAYS, PLANS, TRIAL_DAYS, JOB_VALIDITY_DAYS, Plan, free_plan_for_role, is_candidate

TRIAL_REMINDER_DAYS = 3

# Înainte de activarea abonamentelor: acces complet pentru angajatori
LAUNCH_PLAN = Plan("launch", "employer", "Acces gratuit", 0, None, JOB_VALIDITY_DAYS, None, True)


def billing_enabled() -> bool:
    return os.getenv("BILLING_ENFORCED") == "1" and bool(os.getenv("STRIPE_SECRET_KEY"))


# ─────────────────────────── citire / creare ───────────────────────────

def get_or_create_subscription(db: Session, user: models.User, now: Optional[datetime] = None) -> m2.Subscription:
    now = now or datetime.utcnow()
    sub = db.query(m2.Subscription).filter_by(user_id=user.id).first()
    if sub:
        return sub
    sub = m2.Subscription(
        user_id=user.id, plan_code="trial", status="trialing",
        trial_started_at=now, trial_ends_at=now + timedelta(days=TRIAL_DAYS),
        current_period_start=now, current_period_end=now + timedelta(days=TRIAL_DAYS),
    )
    db.add(sub)
    db.commit()
    db.refresh(sub)
    return sub


def _downgrade_to_free(sub: m2.Subscription, rol: str, now: datetime) -> None:
    sub.plan_code = free_plan_for_role(rol).code
    sub.status = "free"
    sub.current_period_start = now
    sub.current_period_end = None
    sub.cancel_at_period_end = False
    sub.grace_until = None


def reconcile(sub: m2.Subscription, rol: str, now: datetime) -> bool:
    """Tranziții bazate pe timp (plasă de siguranță dacă un webhook Stripe întârzie)."""
    if sub.status == "trialing" and sub.trial_ends_at and now >= sub.trial_ends_at:
        if sub.provider_subscription_id:
            sub.status = "past_due"
            sub.grace_until = sub.trial_ends_at + timedelta(days=GRACE_DAYS)
        else:
            _downgrade_to_free(sub, rol, now)
        return True
    if sub.status == "past_due" and sub.grace_until and now >= sub.grace_until:
        _downgrade_to_free(sub, rol, now)
        return True
    if sub.status in ("active", "canceled") and sub.current_period_end:
        grace = timedelta(days=GRACE_DAYS if sub.status == "active" else 0)
        if now >= sub.current_period_end + grace:
            _downgrade_to_free(sub, rol, now)
            return True
    return False


def effective_plan(sub: m2.Subscription, rol: str, now: Optional[datetime] = None) -> Plan:
    now = now or datetime.utcnow()
    if sub.status == "trialing" and sub.trial_ends_at and now < sub.trial_ends_at:
        return PLANS["trial"]
    if sub.status in ("active", "past_due", "canceled") and sub.plan_code in PLANS:
        return PLANS[sub.plan_code]
    return free_plan_for_role(rol)


def get_entitlements(db: Session, user: models.User) -> tuple[Optional[m2.Subscription], Plan]:
    if is_candidate(user.rol):
        return None, PLANS["candidate_free"]
    if user.rol == "admin":
        return None, PLANS["employer_pro"]
    if not billing_enabled():
        return None, LAUNCH_PLAN
    now = datetime.utcnow()
    sub = get_or_create_subscription(db, user, now)
    if reconcile(sub, user.rol, now):
        db.commit()
    return sub, effective_plan(sub, user.rol, now)


def subscription_summary(db: Session, user: models.User) -> dict:
    sub, plan = get_entitlements(db, user)
    now = datetime.utcnow()
    days_left = None
    if sub and sub.status == "trialing" and sub.trial_ends_at:
        days_left = max(0, (sub.trial_ends_at - now).days)
    return {
        "billing_enabled": billing_enabled(),
        "status": sub.status if sub else ("free" if is_candidate(user.rol) else "launch"),
        "plan": plan.public(),
        "subscribed_plan_code": sub.plan_code if sub else plan.code,
        "trial_ends_at": sub.trial_ends_at if sub else None,
        "trial_days_left": days_left,
        "current_period_end": sub.current_period_end if sub else None,
        "cancel_at_period_end": sub.cancel_at_period_end if sub else False,
        "active_jobs": None if is_candidate(user.rol) else _count_active_jobs(db, user.id),
        "has_payment_method": bool(sub and sub.provider_subscription_id),
    }


# ─────────────────────────── guards pentru alte routere ───────────────────────────

def _count_active_jobs(db: Session, user_id: int) -> int:
    return db.query(models.Job).filter(
        models.Job.angajator_id == user_id,
        models.Job.activ == True,  # noqa: E712
        models.Job.blocat_antifrauda != True,  # noqa: E712
    ).count()


def assert_can_post_job(db: Session, user: models.User) -> Plan:
    """De apelat în POST /api/jobs și la reactivarea unui job. Aruncă 402 dacă limita e atinsă."""
    _, plan = get_entitlements(db, user)
    if plan.max_active_jobs is None:
        return plan
    if plan.max_active_jobs == 0:
        raise HTTPException(402, detail="Luna gratuită s-a încheiat. Alege un abonament (Basic sau Pro) ca să postezi joburi.")
    if _count_active_jobs(db, user.id) >= plan.max_active_jobs:
        raise HTTPException(402, detail=f"Planul {plan.name} permite maximum {plan.max_active_jobs} joburi active. "
                                        f"Dezactivează un anunț sau treci pe Pro.")
    return plan


def job_expiry(plan: Plan, now: Optional[datetime] = None) -> datetime:
    return (now or datetime.utcnow()) + timedelta(days=plan.job_validity_days)


def require_feature(feature: str):
    """Dependency FastAPI: `Depends(require_feature("cv_database"))`."""
    def checker(user=Depends(get_user_curent), db: Session = Depends(get_db)):
        _, plan = get_entitlements(db, user)
        if not getattr(plan, feature, False):
            raise HTTPException(402, detail="Funcția aceasta e disponibilă în planul Pro.")
        return user
    return checker


# ─────────────────────────── task periodic ───────────────────────────

def sweep(db: Session, now: Optional[datetime] = None) -> dict:
    """Rulat din expirare_jobs la fiecare 5 minute."""
    stats = {"downgraded": 0, "reminded": 0, "refreshed": 0}
    if not billing_enabled():
        return stats
    from notificari_service import creeaza_notificare
    now = now or datetime.utcnow()

    due = db.query(m2.Subscription, models.User.rol).join(models.User, models.User.id == m2.Subscription.user_id).filter(
        m2.Subscription.status.in_(["trialing", "past_due", "active", "canceled"])
    ).all()
    for sub, rol in due:
        if reconcile(sub, rol, now) and sub.status == "free":
            stats["downgraded"] += 1
    db.commit()

    soon = db.query(m2.Subscription).filter(
        m2.Subscription.status == "trialing",
        m2.Subscription.trial_reminder_sent == False,  # noqa: E712
        m2.Subscription.trial_ends_at <= now + timedelta(days=TRIAL_REMINDER_DAYS),
    ).all()
    for sub in soon:
        sub.trial_reminder_sent = True
        msg = ("Luna gratuită se termină în curând. Abonamentul ales pornește automat la final — îl poți anula oricând."
               if sub.provider_subscription_id else
               "Luna gratuită pe JobPart se termină în 3 zile. Alege un abonament ca să poți posta în continuare.")
        creeaza_notificare(db, sub.user_id, "trial_expira", msg, "/static/abonament.html")
        stats["reminded"] += 1

    rows = db.query(m2.JobMeta, models.Job).join(models.Job, models.Job.id == m2.JobMeta.job_id).filter(
        models.Job.activ == True,  # noqa: E712
        m2.JobMeta.auto_refresh_at.isnot(None),
        m2.JobMeta.auto_refresh_at <= now,
    ).all()
    for meta, job in rows:
        owner = db.get(models.User, job.angajator_id)
        plan = get_entitlements(db, owner)[1] if owner else None
        if plan and plan.auto_refresh_days:
            meta.refreshed_at = now
            meta.auto_refresh_at = now + timedelta(days=plan.auto_refresh_days)
            job.expira_la = job_expiry(plan, now)
            stats["refreshed"] += 1
        else:
            meta.auto_refresh_at = None
    db.commit()
    return stats
