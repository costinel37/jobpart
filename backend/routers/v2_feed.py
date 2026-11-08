"""
API v2 — Feed dinamic + Time-Matching + setări internaționale.

  GET  /api/v2/feed                 feed vertical (cursor = offset), filtrat pe disponibilitate + navetă
  GET  /api/v2/availability         calendarul săptămânal al utilizatorului
  PUT  /api/v2/availability
  GET  /api/v2/me/settings          fus orar, limbă, monedă, locație navetă
  PUT  /api/v2/me/settings
  PUT  /api/v2/jobs/{id}/meta       angajatorul setează remote / fus / monedă / ture
"""
import json
from datetime import datetime, timedelta
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

import models
import models_v2 as m2
import time_matching as tm
from auth import get_user_curent, get_user_optional
from billing_service import get_entitlements
from currency import SUPPORTED, convert_minor, load_rates
from database import get_db

router = APIRouter(prefix="/api/v2", tags=["v2 Feed & Time-Matching"])

DEFAULT_TZ = "Europe/Bucharest"


# ─────────────────────────── schemas ───────────────────────────

class SlotIn(BaseModel):
    weekday: int = Field(ge=0, le=6)
    start_min: int = Field(ge=0, le=1439)
    end_min: int = Field(ge=1, le=1440)

    @model_validator(mode="after")
    def _order(self):
        if self.end_min <= self.start_min:
            raise ValueError("end_min trebuie să fie după start_min")
        return self


class AvailabilityIn(BaseModel):
    timezone: str = DEFAULT_TZ
    slots: list[SlotIn] = Field(default_factory=list, max_length=7 * 48)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if not tm.is_valid_tz(v):
            raise ValueError("Fus orar invalid")
        return v


class SettingsIn(BaseModel):
    timezone: Optional[str] = None
    locale: Optional[Literal["ro", "en"]] = None
    currency: Optional[Literal["EUR", "RON", "USD", "GBP"]] = None
    country_code: Optional[str] = Field(None, min_length=2, max_length=2)
    home_lat: Optional[float] = Field(None, ge=-90, le=90)
    home_lng: Optional[float] = Field(None, ge=-180, le=180)
    max_commute_min: Optional[int] = Field(None, ge=5, le=90)
    commute_mode: Optional[Literal["walk", "transit"]] = None
    accepts_remote: Optional[bool] = None

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if v is not None and not tm.is_valid_tz(v):
            raise ValueError("Fus orar invalid")
        return v


CONTRACT_TYPES = Literal["cim_part_time", "cim_full_time", "zilier", "services_b2b", "internship", "foreign_contract"]


class JobMetaIn(BaseModel):
    contract_type: CONTRACT_TYPES  # obligatoriu: forma legală de angajare
    is_remote: bool = False
    country_code: str = Field("RO", min_length=2, max_length=2)
    timezone: str = DEFAULT_TZ
    currency: Literal["EUR", "RON", "USD", "GBP"] = "RON"
    pay_min: Optional[float] = Field(None, ge=0)
    pay_max: Optional[float] = Field(None, ge=0)
    pay_period: Literal["hour", "day", "month", "task"] = "hour"
    languages: list[dict] = Field(default_factory=list, max_length=10)
    cover_image_url: Optional[str] = Field(None, max_length=500)
    accent_color: Optional[str] = Field(None, pattern=r"^#[0-9A-Fa-f]{6}$")
    shifts: list[SlotIn] = Field(default_factory=list, max_length=7 * 48)

    @field_validator("timezone")
    @classmethod
    def _tz(cls, v):
        if not tm.is_valid_tz(v):
            raise ValueError("Fus orar invalid")
        return v


# ─────────────────────────── helpers ───────────────────────────

def _settings(db: Session, user) -> m2.UserSettings:
    s = db.get(m2.UserSettings, user.id)
    if not s:
        s = m2.UserSettings(user_id=user.id)
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def _legacy_pay(job: models.Job) -> tuple[Optional[int], Optional[int], str]:
    """Joburile vechi au salariu în RON fără perioadă. Euristică: ≤ 200 RON = pe oră."""
    ref = job.salariu_max or job.salariu_min
    period = "hour" if ref and ref <= 200 else "month"
    to_minor = lambda v: v * 100 if v is not None else None  # noqa: E731
    return to_minor(job.salariu_min), to_minor(job.salariu_max), period


def _norm(text: str) -> str:
    """Litere mici, fără diacritice (ș→s, ă→a), pentru potrivire robustă CV ↔ job."""
    import unicodedata
    t = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in t if not unicodedata.combining(c))


_STOP = {"si", "sau", "cu", "de", "la", "in", "pe", "din", "pentru", "the", "and", "for", "with", "part", "time",
         "full", "job", "lucru", "munca", "bun", "buna", "nivel", "baza", "avansat", "mediu"}


def cv_terms(db: Session, user) -> list[str]:
    """Termenii din CV (titlu, competențe, poziții anterioare) folosiți la potrivirea cu joburile."""
    if not user or user.rol != "candidat":
        return []
    cv = db.query(models.CandidatCV).filter(models.CandidatCV.user_id == user.id).first()
    if not cv:
        return []
    def js(v):
        try:
            return json.loads(v) if v else []
        except Exception:
            return []
    phrases = [cv.titlu_profesional or ""] + [str(c) for c in js(cv.competente)] +               [str(e.get("pozitie", "")) for e in js(cv.experienta) if isinstance(e, dict)]
    terms: list[str] = []
    for ph in phrases:
        ph = _norm(ph).strip()
        if len(ph) >= 3 and ph not in terms:
            terms.append(ph)                       # expresia întreagă („latte art”)
        for w in ph.replace("/", " ").replace("-", " ").split():
            if len(w) >= 4 and w not in _STOP and w not in terms:
                terms.append(w)                    # cuvinte semnificative („barista”)
            # rădăcina: „ospătară”/„ospătari” → „ospatar”, „vânzătoare” → „vanzato”
            stem = w[:-1] if len(w) >= 6 and w[-1] in "aeiu" else (w[:-2] if len(w) >= 8 and w.endswith(("re", "ri")) else None)
            if stem and stem not in _STOP and stem not in terms:
                terms.append(stem)
    return terms[:40]


# ─────────────────────────── availability & settings ───────────────────────────

@router.get("/availability")
def get_availability(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    s = _settings(db, user)
    slots = db.query(m2.AvailabilitySlot).filter_by(user_id=user.id).order_by(
        m2.AvailabilitySlot.weekday, m2.AvailabilitySlot.start_min).all()
    return {"timezone": s.timezone,
            "slots": [{"weekday": x.weekday, "start_min": x.start_min, "end_min": x.end_min} for x in slots]}


@router.put("/availability")
def put_availability(body: AvailabilityIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    s = _settings(db, user)
    s.timezone = body.timezone
    # Unim intervalele suprapuse pe aceeași zi înainte de salvare
    by_day: dict[int, list] = {}
    for sl in body.slots:
        by_day.setdefault(sl.weekday, []).append((sl.start_min, sl.end_min))
    db.query(m2.AvailabilitySlot).filter_by(user_id=user.id).delete()
    count = minutes = 0
    for day, ivs in by_day.items():
        for a, b in tm.merge(ivs):
            db.add(m2.AvailabilitySlot(user_id=user.id, weekday=day, start_min=a, end_min=b))
            count += 1
            minutes += b - a
    db.commit()
    return {"saved": count, "weekly_hours": round(minutes / 60, 1)}


@router.get("/me/settings")
def get_settings(user=Depends(get_user_curent), db: Session = Depends(get_db)):
    s = _settings(db, user)
    return {c.name: getattr(s, c.name) for c in m2.UserSettings.__table__.columns if c.name != "user_id"}


@router.put("/me/settings")
def put_settings(body: SettingsIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    s = _settings(db, user)
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(s, k, v)
    db.commit()
    return {"ok": True}


# ─────────────────────────── job meta (angajator) ───────────────────────────

@router.put("/jobs/{job_id}/meta")
def put_job_meta(job_id: int, body: JobMetaIn, user=Depends(get_user_curent), db: Session = Depends(get_db)):
    job = db.get(models.Job, job_id)
    if not job:
        raise HTTPException(404, "Jobul nu a fost găsit.")
    if job.angajator_id != user.id and user.rol != "admin":
        raise HTTPException(403, "Nu ai permisiunea.")
    if body.pay_min is not None and body.pay_max is not None and body.pay_max < body.pay_min:
        raise HTTPException(422, "pay_max < pay_min")

    meta = db.get(m2.JobMeta, job_id) or m2.JobMeta(job_id=job_id)
    data = body.model_dump(exclude={"shifts", "pay_min", "pay_max", "languages"})
    for k, v in data.items():
        setattr(meta, k, v)
    meta.pay_min_minor = round(body.pay_min * 100) if body.pay_min is not None else None
    meta.pay_max_minor = round(body.pay_max * 100) if body.pay_max is not None else None
    meta.languages = json.dumps(body.languages)
    _, plan = get_entitlements(db, user)
    if plan.auto_refresh_days and not meta.auto_refresh_at:
        meta.auto_refresh_at = datetime.utcnow() + timedelta(days=plan.auto_refresh_days)
    db.merge(meta)

    db.query(m2.JobShift).filter_by(job_id=job_id).delete()
    for sl in body.shifts:
        db.add(m2.JobShift(job_id=job_id, weekday=sl.weekday, start_min=sl.start_min, end_min=sl.end_min))
    db.commit()
    return {"ok": True}


# ─────────────────────────── FEED ───────────────────────────

@router.get("/feed")
def feed(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    max_min: Optional[int] = Query(None, ge=5, le=90, description="minute maxime de navetă"),
    mode: Optional[Literal["walk", "transit"]] = None,
    remote: Literal["all", "only", "exclude"] = "all",
    min_coverage: float = Query(0.8, ge=0, le=1, description="cât % din ture trebuie să acopere candidatul"),
    match_schedule: bool = True,
    currency: Optional[Literal["EUR", "RON", "USD", "GBP"]] = None,
    tz_name: Optional[str] = Query(None, alias="tz"),
    categorie: Optional[str] = None,
    cursor: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=30),
    user=Depends(get_user_optional),
    db: Session = Depends(get_db),
):
    now = datetime.utcnow()

    # 1. Contextul privitorului (setări salvate, suprascrise de parametri)
    s = _settings(db, user) if user else None
    viewer_tz = tz_name if tz_name and tm.is_valid_tz(tz_name) else (s.timezone if s else DEFAULT_TZ)
    viewer_cur = currency or (s.currency if s else "RON")
    lat = lat if lat is not None else (s.home_lat if s else None)
    lng = lng if lng is not None else (s.home_lng if s else None)
    max_min = max_min or (s.max_commute_min if s else 20)
    mode = mode or (s.commute_mode if s else "transit")

    # Minor (16–17 ani): aplicăm limitele din Codul Muncii
    is_minor = False
    if user and user.data_nasterii:
        today = now.date()
        b = user.data_nasterii
        is_minor = (today.year - b.year - ((today.month, today.day) < (b.month, b.day))) < 18

    cand_utc: list = []
    has_availability = False
    if user and match_schedule:
        slots = db.query(m2.AvailabilitySlot).filter_by(user_id=user.id).all()
        has_availability = bool(slots)
        cand_utc = tm.to_utc_intervals([(x.weekday, x.start_min, x.end_min) for x in slots], viewer_tz)

    # 2. Pre-filtru SQL: activ, ne-blocat, + (remote SAU în raza de navetă)
    q = db.query(models.Job, m2.JobMeta).outerjoin(m2.JobMeta, m2.JobMeta.job_id == models.Job.id).filter(
        models.Job.activ == True,  # noqa: E712
        models.Job.blocat_antifrauda != True,  # noqa: E712
        or_(models.Job.expira_la.is_(None), models.Job.expira_la > now),
    )
    if categorie:
        q = q.filter(models.Job.categorie == categorie)
    is_remote = func.coalesce(m2.JobMeta.is_remote, False)
    if remote == "only":
        q = q.filter(is_remote == True)  # noqa: E712
    elif lat is not None and lng is not None:
        dlat, dlng = tm.bbox_for_minutes(lat, max_min, mode)
        in_box = (models.Job.lat.between(lat - dlat, lat + dlat)) & (models.Job.lng.between(lng - dlng, lng + dlng))
        q = q.filter(in_box if remote == "exclude" else or_(is_remote == True, in_box))  # noqa: E712
    elif remote == "exclude":
        q = q.filter(is_remote == False)  # noqa: E712

    rows = q.order_by(models.Job.promovat.desc(), models.Job.creat_la.desc()).limit(500).all()
    if not rows:
        return {"items": [], "next_cursor": None, "context": _ctx(viewer_tz, viewer_cur, has_availability)}

    job_ids = [j.id for j, _ in rows]
    shifts: dict[int, list] = {}
    for sh in db.query(m2.JobShift).filter(m2.JobShift.job_id.in_(job_ids)).all():
        shifts.setdefault(sh.job_id, []).append((sh.weekday, sh.start_min, sh.end_min))
    employer_ids = {j.angajator_id for j, _ in rows}
    ratings = dict((sid, (avg, cnt)) for sid, avg, cnt in db.query(
        models.Review.subiect_id, func.avg(models.Review.rating), func.count(models.Review.id)
    ).filter(models.Review.subiect_id.in_(employer_ids)).group_by(models.Review.subiect_id).all())
    rates = load_rates(db)
    terms = cv_terms(db, user)

    # 3. Scoring în Python (matching orar + navetă exactă)
    scored = []
    for job, meta in rows:
        job_tz = meta.timezone if meta else DEFAULT_TZ
        remote_job = bool(meta and meta.is_remote)

        commute = None
        if not remote_job and lat is not None and lng is not None:
            if job.lat is None or job.lng is None:
                continue
            commute = tm.commute_minutes(tm.haversine_km(lat, lng, job.lat, job.lng), mode)
            if commute > max_min:
                continue

        job_utc = tm.to_utc_intervals(shifts.get(job.id, []), job_tz)
        shifts_local = tm.utc_intervals_to_local(job_utc, viewer_tz)
        if is_minor:
            # zilierii și serviciile B2B (PFA) nu se aplică minorilor
            if meta and meta.contract_type in ("zilier", "services_b2b"):
                continue
            if not tm.is_minor_safe([(s["weekday"], s["start"], s["end"]) for s in shifts_local]):
                continue
        cov, ov, req = tm.coverage(job_utc, cand_utc) if has_availability else (None, 0, tm.total_minutes(job_utc))
        if cov is not None and cov < min_coverage:
            continue
        sponsored = bool(job.promovat and job.promovat_pana and job.promovat_pana > now)

        fresh_at = (meta.refreshed_at if meta and meta.refreshed_at else None) or job.creat_la or now
        age_days = max(0.0, (now - fresh_at).total_seconds() / 86400)
        hits: list[str] = []
        if terms:
            hay = _norm(" ".join(filter(None, [job.titlu, job.categorie, job.cerinte, (job.descriere or "")[:1500]])))
            hits = [t for t in terms if t in hay]
        score = (
            min(len(hits), 4) * 9
            + (cov if cov is not None else 0.6) * 50
            + max(0, 20 - age_days) * 1.0
            + (15 if sponsored else 0)
            + (max(0, max_min - commute) / max_min * 15 if commute is not None else 8)
        )

        if meta and (meta.pay_min_minor or meta.pay_max_minor):
            pmin, pmax, period, src_cur = meta.pay_min_minor, meta.pay_max_minor, meta.pay_period, meta.currency
        else:
            (pmin, pmax, period), src_cur = _legacy_pay(job), "RON"
        rating = ratings.get(job.angajator_id)

        scored.append((score, {
            "id": job.id,
            "title": job.titlu,
            "company": job.companie,
            "employer_id": job.angajator_id,
            "city": job.oras,
            "category": job.categorie,
            "is_remote": remote_job,
            "country_code": meta.country_code if meta else "RO",
            "job_timezone": job_tz,
            "tz_diff_hours": tm.tz_diff_hours(viewer_tz, job_tz),
            "contract_type": meta.contract_type if meta else None,
            "commute_min": commute,           # estimare (distanță × factor de ocol), nu rutare reală
            "commute_estimated": True,
            "commute_mode": mode if commute is not None else None,
            "match": None if cov is None else {
                "coverage": round(cov, 2), "overlap_min": ov, "required_min": req},
            "flexible_schedule": req == 0,
            "shifts_local": shifts_local,
            "pay": {
                "min": convert_minor(pmin, src_cur, viewer_cur, rates),
                "max": convert_minor(pmax, src_cur, viewer_cur, rates),
                "currency": viewer_cur, "period": period,
                "original": {"min": pmin, "max": pmax, "currency": src_cur},
            },
            "company_rating": {"avg": round(float(rating[0]), 1), "count": rating[1]} if rating else None,
            "sponsored": sponsored,   # trebuie afișat vizibil ca „Promovat” (Directiva Omnibus / P2B)
            "cover_image_url": meta.cover_image_url if meta else None,
            "accent_color": meta.accent_color if meta else None,
            "snippet": (job.descriere or "")[:220],
            "created_at": job.creat_la,
            "cv_hits": hits[:4],
            "reasons": _reasons(hits, cov, commute, remote_job, req == 0),
        }))

    scored.sort(key=lambda x: x[0], reverse=True)
    page = [item for _, item in scored[cursor:cursor + limit]]
    nxt = cursor + limit if cursor + limit < len(scored) else None
    return {"items": page, "next_cursor": nxt, "total": len(scored),
            "context": _ctx(viewer_tz, viewer_cur, has_availability)}


RANKING_DISCLOSURE = (
    "Ordinea anunțurilor: compatibilitatea cu orele tale libere, distanța estimată, "
    "data publicării și promovarea plătită. Anunțurile promovate sunt marcate „Promovat”."
)


def _ctx(viewer_tz, viewer_cur, has_availability):
    return {"timezone": viewer_tz, "currency": viewer_cur,
            "schedule_filter_active": has_availability, "currencies": list(SUPPORTED),
            "ranking_disclosure": RANKING_DISCLOSURE}


def _reasons(hits, cov, commute, remote_job, flexible) -> list[str]:
    r = []
    if hits:
        r.append("Se potrivește cu CV-ul tău: " + ", ".join(hits[:3]))
    if cov is not None and cov >= 0.999:
        r.append("Programul se potrivește 100% cu orele tale libere")
    elif cov is not None and cov >= 0.5:
        r.append(f"Programul se potrivește {round(cov * 100)}% cu orele tale")
    elif flexible:
        r.append("Program flexibil")
    if commute is not None:
        r.append(f"~{commute} min de tine")
    elif remote_job:
        r.append("Remote")
    return r


@router.get("/matches")
def matches(
    lat: Optional[float] = Query(None, ge=-90, le=90),
    lng: Optional[float] = Query(None, ge=-180, le=180),
    limit: int = Query(12, ge=1, le=30),
    user=Depends(get_user_curent),
    db: Session = Depends(get_db),
):
    """Joburi recomandate automat pe baza CV-ului (+ orele libere + navetă, dacă sunt setate)."""
    if user.rol != "candidat":
        raise HTTPException(403, "Recomandările sunt pentru candidați.")
    data = feed(lat=lat, lng=lng, max_min=None, mode=None, remote="all", min_coverage=0.5,
                match_schedule=True, currency=None, tz_name=None, categorie=None,
                cursor=0, limit=100, user=user, db=db)
    # Potrivit = are legătură cu CV-ul SAU are ture fixe care se potrivesc ≥80% cu orele libere
    # (joburile „program flexibil” fără legătură cu CV-ul nu sunt recomandări, doar zgomot)
    items = [i for i in data["items"] if i["cv_hits"] or
             (i["match"] and i["match"]["coverage"] >= 0.8 and not i["flexible_schedule"])]
    items.sort(key=lambda i: (len(i["cv_hits"]), (i["match"] or {}).get("coverage", 0)), reverse=True)
    return {"items": items[:limit], "has_cv": bool(cv_terms(db, user)),
            "schedule_filter_active": data["context"]["schedule_filter_active"]}
