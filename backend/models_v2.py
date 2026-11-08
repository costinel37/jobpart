"""
JobPart v2 — tabele noi pentru scalare internațională, Time-Matching și abonamente.

Principii:
- 100% aditiv: NU modifică tabelele existente (users, jobs). Toate tabelele noi
  se leagă prin FK, deci `Base.metadata.create_all()` le creează automat, fără ALTER.
- Toate datele de timp sunt stocate în UTC. Fusul orar (IANA, ex. "Europe/Bucharest")
  se stochează separat, iar conversia se face la citire.
- Banii se stochează în subunități (cenți/bani) ca Integer — niciodată Float.
"""
from datetime import datetime

from sqlalchemy import (
    Boolean, CheckConstraint, Column, DateTime, Float, ForeignKey, Index,
    Integer, SmallInteger, String, Text, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


# ─────────────────────────── 1. UTILIZATORI (extensie) ───────────────────────────

class UserSettings(Base):
    """Setări internaționale per utilizator (1-la-1 cu users)."""
    __tablename__ = "user_settings"

    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    timezone = Column(String(64), nullable=False, default="Europe/Bucharest")  # IANA
    locale = Column(String(10), nullable=False, default="ro")                  # ro / en / ...
    currency = Column(String(3), nullable=False, default="RON")                # ISO 4217
    country_code = Column(String(2), nullable=True)                            # ISO 3166-1
    # Locația de referință pentru calculul navetei (nu adresa exactă — GDPR)
    home_lat = Column(Float, nullable=True)
    home_lng = Column(Float, nullable=True)
    max_commute_min = Column(SmallInteger, nullable=False, default=20)
    commute_mode = Column(String(10), nullable=False, default="transit")       # walk / transit
    accepts_remote = Column(Boolean, nullable=False, default=True)
    # Rating agregat (cache, recalculat la fiecare recenzie nouă)
    rating_avg = Column(Float, nullable=True)
    rating_count = Column(Integer, nullable=False, default=0)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class AvailabilitySlot(Base):
    """
    Interval liber săptămânal al candidatului, exprimat în ora LOCALĂ a utilizatorului
    (user_settings.timezone). Conversia în UTC se face la matching, pentru săptămâna
    curentă — astfel trecerea la ora de vară/iarnă (DST) e tratată corect.
    """
    __tablename__ = "availability_slots"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_avail_weekday"),
        CheckConstraint("start_min >= 0 AND end_min <= 1440 AND start_min < end_min", name="ck_avail_range"),
        Index("ix_avail_user", "user_id"),
    )

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    weekday = Column(SmallInteger, nullable=False)    # 0 = Luni ... 6 = Duminică
    start_min = Column(SmallInteger, nullable=False)  # minute de la 00:00 (ex. 14:30 = 870)
    end_min = Column(SmallInteger, nullable=False)


# ─────────────────────────── 2. JOBURI INTERNAȚIONALE ───────────────────────────

class JobMeta(Base):
    """Date internaționale per job (1-la-1 cu jobs). Joburile vechi fără rând aici
    sunt tratate ca: local, RON, Europe/Bucharest, program flexibil."""
    __tablename__ = "job_meta"

    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True)
    is_remote = Column(Boolean, nullable=False, default=False)
    country_code = Column(String(2), nullable=False, default="RO")
    timezone = Column(String(64), nullable=False, default="Europe/Bucharest")
    currency = Column(String(3), nullable=False, default="RON")
    pay_min_minor = Column(Integer, nullable=True)   # în subunități (bani / cenți)
    pay_max_minor = Column(Integer, nullable=True)
    pay_period = Column(String(10), nullable=False, default="hour")  # hour / day / month / task
    # Forma legală de angajare — obligatorie pentru joburi noi (evită munca nedeclarată).
    # cim_part_time / cim_full_time / zilier (L. 52/2011) / services_b2b (PFA/SRL) /
    # internship (L. 176/2018) / foreign_contract (angajator din afara RO, remote)
    contract_type = Column(String(20), nullable=True)
    languages = Column(Text, nullable=True)           # JSON: [{"code":"en","level":"B2"}]
    min_weekly_hours = Column(SmallInteger, nullable=True)
    cover_image_url = Column(String(500), nullable=True)   # pentru cardul din feed
    accent_color = Column(String(7), nullable=True)        # ex. "#B4FF39"
    auto_refresh_at = Column(DateTime, nullable=True)      # Pro: următorul refresh automat
    refreshed_at = Column(DateTime, nullable=True)         # sortare în feed

    job = relationship("Job")


class JobTranslation(Base):
    """Titlu/descriere în mai multe limbi. Fallback: textul original din jobs."""
    __tablename__ = "job_translations"
    __table_args__ = (UniqueConstraint("job_id", "locale"),)

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    locale = Column(String(10), nullable=False)
    title = Column(String(200), nullable=False)
    description = Column(Text, nullable=False)


class JobShift(Base):
    """Intervalele în care jobul cere prezență, în ora locală a jobului (job_meta.timezone).
    Fără niciun rând = program flexibil (compatibil cu oricine)."""
    __tablename__ = "job_shifts"
    __table_args__ = (
        CheckConstraint("weekday BETWEEN 0 AND 6", name="ck_shift_weekday"),
        CheckConstraint("start_min >= 0 AND end_min <= 1440 AND start_min < end_min", name="ck_shift_range"),
    )

    id = Column(Integer, primary_key=True)
    job_id = Column(Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True)
    weekday = Column(SmallInteger, nullable=False)
    start_min = Column(SmallInteger, nullable=False)
    end_min = Column(SmallInteger, nullable=False)


class FxRate(Base):
    """Curs valutar față de EUR (actualizat zilnic de un task; vezi currency.py)."""
    __tablename__ = "fx_rates"

    currency = Column(String(3), primary_key=True)
    per_eur = Column(Float, nullable=False)          # câte unități = 1 EUR
    updated_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────── 3. ABONAMENTE ───────────────────────────

class Subscription(Base):
    """
    Un singur abonament curent per utilizator. Planurile sunt definite în cod (plans.py),
    iar aici se reține doar codul planului + starea.

    status:
      trialing   — luna gratuită (acces complet)
      active     — plătit
      past_due   — plata a eșuat, perioadă de grație
      canceled   — anulat, acces până la current_period_end
      free       — fără plan plătit (candidați: mereu gratis; angajatori: doar citire)
    """
    __tablename__ = "subscriptions"
    __table_args__ = (Index("ix_sub_status_end", "status", "current_period_end"),)

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False)
    plan_code = Column(String(32), nullable=False)       # trial / employer_basic / employer_pro / candidate_free / candidate_premium
    status = Column(String(16), nullable=False)
    trial_started_at = Column(DateTime, nullable=True)
    trial_ends_at = Column(DateTime, nullable=True)
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False)
    grace_until = Column(DateTime, nullable=True)
    # Procesator de plăți (Stripe)
    provider = Column(String(16), nullable=True, default="stripe")
    provider_customer_id = Column(String(64), nullable=True, index=True)
    provider_subscription_id = Column(String(64), nullable=True, unique=True)
    trial_reminder_sent = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    user = relationship("User")


class PaymentEvent(Base):
    """Jurnal de webhook-uri — garantează idempotența (Stripe poate retrimite același eveniment)."""
    __tablename__ = "payment_events"

    id = Column(Integer, primary_key=True)
    provider_event_id = Column(String(80), unique=True, nullable=False)
    type = Column(String(80), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    amount_minor = Column(Integer, nullable=True)
    currency = Column(String(3), nullable=True)
    payload = Column(Text, nullable=True)
    processed_at = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────── 4. CHAT ÎN TIMP REAL ───────────────────────────

class ChatMessage(Base):
    """
    Mesaj de chat între angajator și candidat. Conversația = o aplicare (applications.id),
    deci doar părțile care au deja o legătură (candidatul a aplicat) pot vorbi.

    kind:
      text               — mesaj normal
      accept / reject    — acțiune rapidă a angajatorului (schimbă și statusul aplicării)
      interview          — propunere de interviu (meta: {"when": ISO UTC, "where": "...", "mode": "online|onsite"})
      interview_yes/no   — răspunsul candidatului la propunere (meta: {"ref": id_propunere})
    """
    __tablename__ = "chat_messages"
    __table_args__ = (Index("ix_chat_app_id", "application_id", "id"),)

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    sender_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind = Column(String(16), nullable=False, default="text")
    body = Column(Text, nullable=False)
    meta = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    read_at = Column(DateTime, nullable=True)
