"""
API abonamente v2 — /api/v2/billing  (DOAR pentru angajatori)

JobPart încasează numai abonamentul angajatorului pentru serviciul de publicare/recrutare.
NU procesează salarii și nu intermediază plata muncii între angajator și candidat.

Variabile de mediu (în .env și pe Render):
  BILLING_ENFORCED=1, STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
  STRIPE_PRICE_EMPLOYER_BASIC, STRIPE_PRICE_EMPLOYER_PRO
Fără ele, plățile răspund 503 și angajatorii au acces gratuit complet (ca înainte).
"""
import calendar
import json
import logging
import os
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

import models
import models_v2 as m2
from auth import get_user_curent
from billing_service import _downgrade_to_free, billing_enabled, get_or_create_subscription, subscription_summary
from config import FRONTEND_URL
from database import get_db
from plans import GRACE_DAYS, PLANS, is_candidate, purchasable_plans

router = APIRouter(prefix="/api/v2/billing", tags=["v2 Abonamente"])
log = logging.getLogger("billing")

STRIPE_MIN_TRIAL_SECONDS = 48 * 3600  # Stripe Checkout cere trial_end la cel puțin 48h în viitor


def _stripe():
    key = os.getenv("STRIPE_SECRET_KEY")
    if not key:
        raise HTTPException(503, "Plățile nu sunt configurate încă.")
    import stripe
    stripe.api_key = key
    return stripe


@router.get("/plans")
def list_plans(user=Depends(get_user_curent)):
    return [p.public() for p in purchasable_plans(user.rol)]


@router.get("/me")
def my_subscription(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    return subscription_summary(db, user)


class CheckoutIn(BaseModel):
    plan_code: str


@router.post("/checkout")
def create_checkout(body: CheckoutIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    if is_candidate(user.rol):
        raise HTTPException(403, "Pentru candidați, JobPart este gratuit. Nu există nimic de plătit.")
    if not billing_enabled():
        raise HTTPException(503, "Abonamentele nu sunt active încă. Ai acces gratuit complet.")
    plan = PLANS.get(body.plan_code)
    if not plan or not plan.stripe_price_env or plan.audience != "employer":
        raise HTTPException(400, "Plan invalid.")
    if not plan.stripe_price_id:
        raise HTTPException(503, f"Lipsește {plan.stripe_price_env} în configurare.")
    stripe = _stripe()
    sub = get_or_create_subscription(db, user)

    if sub.provider_subscription_id and sub.status in ("active", "trialing", "past_due"):
        raise HTTPException(409, "Ai deja un abonament. Schimbă planul din portalul de facturare.")

    if not sub.provider_customer_id:
        customer = stripe.Customer.create(email=user.email, name=user.nume, metadata={"user_id": str(user.id)})
        sub.provider_customer_id = customer.id
        db.commit()

    subscription_data = {"metadata": {"user_id": str(user.id), "plan_code": plan.code}}
    # Dacă e încă în luna gratuită, nu-l taxăm până la final
    if sub.status == "trialing" and sub.trial_ends_at:
        remaining = (sub.trial_ends_at - datetime.utcnow()).total_seconds()
        if remaining > STRIPE_MIN_TRIAL_SECONDS:
            subscription_data["trial_end"] = calendar.timegm(sub.trial_ends_at.utctimetuple())

    trial_note = ""
    if "trial_end" in subscription_data:
        trial_note = (f"Nu plătești nimic până la {sub.trial_ends_at:%d.%m.%Y}. După această dată, "
                      f"abonamentul se reînnoiește lunar până îl anulezi. Te anunțăm cu 3 zile înainte. ")

    session = stripe.checkout.Session.create(
        mode="subscription",
        customer=sub.provider_customer_id,
        client_reference_id=str(user.id),
        line_items=[{"price": plan.stripe_price_id, "quantity": 1}],
        subscription_data=subscription_data,
        allow_promotion_codes=True,
        # TVA calculat de Stripe Tax (taxare inversă pentru firme UE cu cod de TVA valid)
        automatic_tax={"enabled": os.getenv("STRIPE_AUTOMATIC_TAX", "1") == "1"},
        billing_address_collection="required",
        customer_update={"address": "auto", "name": "auto"},
        # Firmele își pot introduce CUI/VAT ID pentru factură (taxare inversă intra-UE)
        tax_id_collection={"enabled": True},
        # Acceptarea Termenilor (necesită URL-ul Termenilor setat în Stripe Dashboard → Settings → Public details)
        consent_collection={"terms_of_service": "required"},
        custom_text={"submit": {"message": (trial_note + "Abonament pentru persoane juridice / PFA. "
                                             "Poți anula oricând din contul tău.")[:1200]}},
        success_url=f"{FRONTEND_URL}/static/abonament.html?status=success",
        cancel_url=f"{FRONTEND_URL}/static/abonament.html?status=cancel",
    )
    return {"url": session.url}


@router.post("/portal")
def billing_portal(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    """Portal Stripe: schimbă cardul, schimbă planul, anulează, descarcă facturi."""
    if is_candidate(user.rol):
        raise HTTPException(403, "Pentru candidați, JobPart este gratuit.")
    sub = get_or_create_subscription(db, user)
    if not sub.provider_customer_id:
        raise HTTPException(400, "Nu ai încă o metodă de plată.")
    session = _stripe().billing_portal.Session.create(
        customer=sub.provider_customer_id, return_url=f"{FRONTEND_URL}/static/abonament.html")
    return {"url": session.url}


# ─────────────────────────── webhook ───────────────────────────

def _ts(value):
    return datetime.utcfromtimestamp(value) if value else None


def _period_end(stripe_sub) -> datetime | None:
    # API-urile Stripe recente mută current_period_end pe item-uri
    end = stripe_sub.get("current_period_end")
    if not end:
        items = (stripe_sub.get("items") or {}).get("data") or []
        end = items[0].get("current_period_end") if items else None
    return _ts(end)


def _plan_from_price(price_id: str) -> str | None:
    for p in PLANS.values():
        if p.stripe_price_id and p.stripe_price_id == price_id:
            return p.code
    return None


def _apply_stripe_subscription(db: Session, stripe_sub) -> int | None:
    user_id = int((stripe_sub.get("metadata") or {}).get("user_id") or 0)
    sub = None
    if stripe_sub.get("id"):
        sub = db.query(m2.Subscription).filter_by(provider_subscription_id=stripe_sub["id"]).first()
    if not sub and user_id:
        sub = db.query(m2.Subscription).filter_by(user_id=user_id).first()
    if not sub and stripe_sub.get("customer"):
        sub = db.query(m2.Subscription).filter_by(provider_customer_id=stripe_sub["customer"]).first()
    if not sub:
        log.warning("Webhook: abonament necunoscut %s", stripe_sub.get("id"))
        return None

    user = db.get(models.User, sub.user_id)
    items = (stripe_sub.get("items") or {}).get("data") or []
    price_id = items[0]["price"]["id"] if items else None
    plan_code = _plan_from_price(price_id) or (stripe_sub.get("metadata") or {}).get("plan_code")
    status = stripe_sub.get("status")

    sub.provider_subscription_id = stripe_sub.get("id")
    sub.provider_customer_id = stripe_sub.get("customer") or sub.provider_customer_id
    sub.cancel_at_period_end = bool(stripe_sub.get("cancel_at_period_end"))
    sub.current_period_end = _period_end(stripe_sub)

    if status == "trialing":
        sub.plan_code = plan_code or sub.plan_code   # trial-ul nostru continuă, planul ales se reține
        sub.status = "trialing"
        sub.trial_ends_at = _ts(stripe_sub.get("trial_end")) or sub.trial_ends_at
    elif status == "active":
        sub.plan_code = plan_code or sub.plan_code
        sub.status = "canceled" if sub.cancel_at_period_end else "active"
        sub.grace_until = None
    elif status in ("past_due", "unpaid", "incomplete"):
        sub.status = "past_due"
        sub.grace_until = sub.grace_until or datetime.utcnow() + timedelta(days=GRACE_DAYS)
    elif status in ("canceled", "incomplete_expired"):
        _downgrade_to_free(sub, user.rol if user else "angajator", datetime.utcnow())
        sub.provider_subscription_id = None
    return sub.user_id


@router.post("/webhook", include_in_schema=False)
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    secret = os.getenv("STRIPE_WEBHOOK_SECRET")
    if not secret:
        raise HTTPException(503, "Webhook neconfigurat.")
    stripe = _stripe()
    payload = await request.body()
    try:
        event = stripe.Webhook.construct_event(payload, request.headers.get("stripe-signature", ""), secret)
    except Exception:
        raise HTTPException(400, "Semnătură invalidă.")

    # Idempotență: Stripe poate retrimite același eveniment
    if db.query(m2.PaymentEvent).filter_by(provider_event_id=event["id"]).first():
        return {"received": True, "duplicate": True}

    etype = event["type"]
    obj = event["data"]["object"]
    user_id = None
    amount = currency = None

    if etype == "checkout.session.completed" and obj.get("subscription"):
        user_id = _apply_stripe_subscription(db, stripe.Subscription.retrieve(obj["subscription"]))
    elif etype in ("customer.subscription.created", "customer.subscription.updated", "customer.subscription.deleted"):
        user_id = _apply_stripe_subscription(db, obj)
    elif etype == "invoice.paid":
        amount, currency = obj.get("amount_paid"), (obj.get("currency") or "").upper()
        sub = db.query(m2.Subscription).filter_by(provider_customer_id=obj.get("customer")).first()
        if sub:
            user_id = sub.user_id
            if amount and sub.status == "past_due":
                sub.status, sub.grace_until = "active", None
    elif etype == "invoice.payment_failed":
        sub = db.query(m2.Subscription).filter_by(provider_customer_id=obj.get("customer")).first()
        if sub:
            user_id = sub.user_id
            sub.status = "past_due"
            sub.grace_until = datetime.utcnow() + timedelta(days=GRACE_DAYS)
            from notificari_service import creeaza_notificare
            creeaza_notificare(db, sub.user_id, "plata_esuata",
                               f"Plata abonamentului a eșuat. Actualizează cardul în {GRACE_DAYS} zile ca să nu pierzi accesul.",
                               "/static/abonament.html")

    db.add(m2.PaymentEvent(provider_event_id=event["id"], type=etype, user_id=user_id,
                           amount_minor=amount, currency=currency, payload=json.dumps(obj)[:20000]))
    db.commit()
    return {"received": True}
