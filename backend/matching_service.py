"""
Notificări automate „Job nou potrivit cu CV-ul tău”.

Rulat din expirare_jobs la fiecare 5 minute: ia joburile publicate de la ultima rulare și le
compară cu CV-urile candidaților (titlu, competențe, poziții). Candidatul primește o notificare
în aplicație pentru fiecare potrivire — maximum MAX_PER_DAY pe zi, ca să nu fie spam.

Respectă regulile pentru minori (fără ture de noapte / peste limitele legale).
"""
import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

import models
import models_v2 as m2
import time_matching as tm

log = logging.getLogger("matching")
MAX_PER_DAY = 3
_last_run: datetime | None = None


def _is_minor(user: models.User, today: date) -> bool:
    b = user.data_nasterii
    return bool(b) and (today.year - b.year - ((today.month, today.day) < (b.month, b.day))) < 18


def notify_cv_matches(db: Session, now: datetime | None = None) -> int:
    global _last_run
    from notificari_service import creeaza_notificare
    from routers.v2_feed import _norm, cv_terms

    now = now or datetime.utcnow()
    since = _last_run or now - timedelta(minutes=10)   # la pornire nu trimitem retroactiv
    _last_run = now

    jobs = db.query(models.Job).filter(
        models.Job.activ == True,  # noqa: E712
        models.Job.blocat_antifrauda != True,  # noqa: E712
        models.Job.creat_la > since, models.Job.creat_la <= now,
    ).all()
    if not jobs:
        return 0

    candidates = db.query(models.User).join(models.CandidatCV, models.CandidatCV.user_id == models.User.id).filter(
        models.User.activ == True, models.User.rol == "candidat",  # noqa: E712
    ).all()
    terms = {u.id: cv_terms(db, u) for u in candidates}
    day_start = datetime(now.year, now.month, now.day)
    sent = 0
    for job in jobs:
        hay = _norm(" ".join(filter(None, [job.titlu, job.categorie, job.cerinte, (job.descriere or "")[:1500]])))
        meta = db.get(m2.JobMeta, job.id)
        shifts = [(s.weekday, s.start_min, s.end_min) for s in db.query(m2.JobShift).filter_by(job_id=job.id).all()]
        minor_ok = tm.is_minor_safe(shifts) and not (meta and meta.contract_type in ("zilier", "services_b2b"))
        for u in candidates:
            if u.id == job.angajator_id:
                continue
            hits = [t for t in terms[u.id] if t in hay]
            if not hits:
                continue
            if _is_minor(u, now.date()) and not minor_ok:
                continue
            already = db.query(models.Notification).filter(
                models.Notification.user_id == u.id, models.Notification.tip == "job_potrivit",
                models.Notification.creat_la >= day_start,
            ).count()
            if already >= MAX_PER_DAY:
                continue
            creeaza_notificare(db, u.id, "job_potrivit",
                               f"🎯 Job nou potrivit cu CV-ul tău: {job.titlu[:60]} ({hits[0]})",
                               f"/static/job-detalii.html?id={job.id}")
            sent += 1
    if sent:
        log.info("[MATCHING] %s notificări trimise pentru %s joburi noi", sent, len(jobs))
    return sent
