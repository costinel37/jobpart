from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
from database import get_db
import models, schemas
from auth import require_rol, hash_parola
import os, threading
from config import UPLOAD_DIR
from email_service import _trimite_email

router = APIRouter(prefix="/api/admin", tags=["Admin"])



def _log_audit(db: Session, admin_id: int, actiune: str, target_type: str = None, target_id: int = None, detalii: str = None):
    intrare = models.AuditLog(
        admin_id=admin_id,
        actiune=actiune,
        target_type=target_type,
        target_id=target_id,
        detalii=detalii,
    )
    db.add(intrare)


@router.get("/utilizatori", response_model=List[schemas.UserOut])
def toti_utilizatorii(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    return (
        db.query(models.User)
        .order_by(models.User.creat_la.desc())
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
        .all()
    )


@router.get("/utilizatori/count")
def numara_utilizatori(db: Session = Depends(get_db), current_user=Depends(require_rol("admin"))):
    return {"total": db.query(models.User).count()}


@router.put("/utilizatori/{user_id}/toggle-activ")
def toggle_activ(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Nu te poți dezactiva pe tine însuți.")

    user.activ = not user.activ
    stare = "activat" if user.activ else "dezactivat"
    _log_audit(db, current_user.id, f"toggle_activ_{stare}", "user", user_id, f"User {user.email} -> {stare}")
    db.commit()
    return {"mesaj": f"Utilizatorul a fost {stare}."}


@router.put("/utilizatori/{user_id}/schimba-rol")
def schimba_rol(
    user_id: int,
    rol_nou: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    if rol_nou not in ["candidat", "angajator", "admin"]:
        raise HTTPException(status_code=400, detail="Rol invalid.")

    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")

    rol_vechi = user.rol
    user.rol = rol_nou
    _log_audit(db, current_user.id, "schimba_rol", "user", user_id, f"{user.email}: {rol_vechi} -> {rol_nou}")
    db.commit()
    return {"mesaj": f"Rolul a fost schimbat în '{rol_nou}'."}


@router.delete("/utilizatori/{user_id}")
def sterge_utilizator_admin(
    user_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    """Anonimizează datele personale ale unui utilizator (GDPR Art. 17)."""
    user = db.query(models.User).filter(models.User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")
    if user.id == current_user.id:
        raise HTTPException(status_code=400, detail="Nu îți poți șterge propriul cont din admin.")
    if user.rol == "admin":
        raise HTTPException(status_code=400, detail="Nu poți șterge un alt administrator.")

    # Șterge CV-urile de pe disk
    for aplicare in user.aplicari:
        if aplicare.cv_path:
            cale = os.path.join(UPLOAD_DIR, aplicare.cv_path)
            if os.path.exists(cale):
                try:
                    os.remove(cale)
                except OSError:
                    pass
            aplicare.cv_path = None
            aplicare.cv_nume_original = None

    # Anonimizează datele personale
    ts = int(datetime.utcnow().timestamp())
    email_original = user.email
    user.email = f"deleted_{user.id}_{ts}@deleted.jobpart.ro"
    user.nume = "Utilizator Șters"
    user.telefon = None
    user.oras = None
    user.despre = None
    user.parola_hash = "DELETED"
    user.activ = False
    user.email_confirmat = False

    # Șterge mesajele private
    db.query(models.Message).filter(
        (models.Message.expeditor_id == user_id) |
        (models.Message.destinatar_id == user_id)
    ).delete(synchronize_session=False)

    # Șterge tokenurile
    db.query(models.EmailVerification).filter(models.EmailVerification.user_id == user_id).delete()
    db.query(models.PasswordReset).filter(models.PasswordReset.user_id == user_id).delete()

    _log_audit(db, current_user.id, "sterge_utilizator", "user", user_id, f"Email original: {email_original}")
    db.commit()
    return {"mesaj": "Datele personale au fost anonimizate (GDPR Art. 17)."}


@router.get("/statistici")
def statistici(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    total_utilizatori = db.query(models.User).count()
    total_candidati = db.query(models.User).filter(models.User.rol == "candidat").count()
    total_angajatori = db.query(models.User).filter(models.User.rol == "angajator").count()
    total_joburi = db.query(models.Job).filter(models.Job.activ == True).count()
    total_aplicari = db.query(models.Application).count()
    aplicari_acceptate = db.query(models.Application).filter(models.Application.status == "acceptata").count()
    joburi_blocate = db.query(models.Job).filter(models.Job.blocat_antifrauda == True).count()
    parteneri_in_asteptare = db.query(models.PartenerAplicatie).filter(
        models.PartenerAplicatie.status == "in_asteptare"
    ).count()

    return {
        "utilizatori": total_utilizatori,
        "candidati": total_candidati,
        "angajatori": total_angajatori,
        "joburi_active": total_joburi,
        "total_aplicari": total_aplicari,
        "aplicari_acceptate": aplicari_acceptate,
        "joburi_blocate": joburi_blocate,
        "parteneri_in_asteptare": parteneri_in_asteptare,
    }


@router.get("/toate-joburile", response_model=List[schemas.JobOut])
def toate_joburile(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    return (
        db.query(models.Job)
        .order_by(models.Job.creat_la.desc())
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
        .all()
    )


@router.get("/toate-joburile/count")
def numara_joburi_admin(db: Session = Depends(get_db), current_user=Depends(require_rol("admin"))):
    return {"total": db.query(models.Job).count()}


@router.delete("/joburi/{job_id}")
def sterge_job_admin(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există.")
    job.activ = False
    _log_audit(db, current_user.id, "dezactiveaza_job", "job", job_id, f"Job: {job.titlu}")
    db.commit()
    return {"mesaj": "Job dezactivat de admin."}


@router.delete("/joburi/{job_id}/definitiv")
def sterge_job_definitiv(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există.")
    titlu = job.titlu
    db.query(models.Precontract).filter(models.Precontract.job_id == job_id).delete(synchronize_session=False)
    db.query(models.Application).filter(models.Application.job_id == job_id).delete(synchronize_session=False)
    db.query(models.Favorite).filter(models.Favorite.job_id == job_id).delete(synchronize_session=False)
    db.query(models.JobView).filter(models.JobView.job_id == job_id).delete(synchronize_session=False)
    db.query(models.JobLike).filter(models.JobLike.job_id == job_id).delete(synchronize_session=False)
    db.query(models.PromovareCerere).filter(models.PromovareCerere.job_id == job_id).delete(synchronize_session=False)
    db.delete(job)
    _log_audit(db, current_user.id, "sterge_definitiv_job", "job", job_id, f"Job: {titlu}")
    db.commit()
    return {"mesaj": "Job șters definitiv din baza de date."}


@router.get("/audit-log")
def audit_log(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    total = db.query(models.AuditLog).count()
    intrari = (
        db.query(models.AuditLog)
        .order_by(models.AuditLog.creat_la.desc())
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
        .all()
    )
    return {
        "total": total,
        "intrari": [
            {
                "id": i.id,
                "admin_id": i.admin_id,
                "actiune": i.actiune,
                "target_type": i.target_type,
                "target_id": i.target_id,
                "detalii": i.detalii,
                "creat_la": i.creat_la.isoformat(),
            }
            for i in intrari
        ]
    }


@router.get("/joburi-blocate")
def joburi_blocate(
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin")),
):
    total = db.query(models.Job).filter(models.Job.blocat_antifrauda == True).count()
    joburi = (
        db.query(models.Job)
        .filter(models.Job.blocat_antifrauda == True)
        .order_by(models.Job.creat_la.desc())
        .offset((pagina - 1) * per_pagina)
        .limit(per_pagina)
        .all()
    )
    return {
        "total": total,
        "joburi": [
            {
                "id": j.id,
                "titlu": j.titlu,
                "companie": j.companie,
                "oras": j.oras,
                "descriere": (j.descriere or "")[:200],
                "motiv_blocare": j.motiv_blocare,
                "angajator_id": j.angajator_id,
                "creat_la": j.creat_la.isoformat(),
            }
            for j in joburi
        ],
    }


@router.put("/joburi/{job_id}/aproba-antifrauda")
def aproba_job_antifrauda(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin")),
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există.")
    job.activ = True
    job.blocat_antifrauda = False
    job.motiv_blocare = None
    _log_audit(db, current_user.id, "aproba_antifrauda", "job", job_id, f"Job aprobat: {job.titlu}")
    db.commit()
    return {"mesaj": "Job aprobat și activat pe platformă."}


@router.get("/parteneri")
def aplicatii_parteneri(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin")),
):
    aplicatii = (
        db.query(models.PartenerAplicatie)
        .order_by(models.PartenerAplicatie.creat_la.desc())
        .all()
    )
    return [
        {
            "id": a.id,
            "nume_companie": a.nume_companie,
            "website": a.website,
            "email": a.email,
            "url_rss": a.url_rss,
            "tara": a.tara,
            "cui": a.cui,
            "descriere": a.descriere,
            "status": a.status,
            "creat_la": a.creat_la.isoformat(),
        }
        for a in aplicatii
    ]


@router.put("/parteneri/{aplicatie_id}/status")
def actualizeaza_status_partener(
    aplicatie_id: int,
    status: str,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin")),
):
    if status not in ["aprobata", "respinsa", "in_asteptare"]:
        raise HTTPException(status_code=400, detail="Status invalid.")
    apl = db.query(models.PartenerAplicatie).filter(
        models.PartenerAplicatie.id == aplicatie_id
    ).first()
    if not apl:
        raise HTTPException(status_code=404, detail="Aplicație negăsită.")
    apl.status = status
    _log_audit(
        db, current_user.id, f"partener_{status}", "partener", aplicatie_id,
        f"{apl.nume_companie} ({apl.email}) -> {status}"
    )
    db.commit()
    return {"mesaj": f"Status actualizat: {status}."}


class NewsletterBody(BaseModel):
    subiect: str
    corp_html: str
    doar_abonati: bool = True


@router.post("/trimite-newsletter")
def trimite_newsletter(
    body: NewsletterBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    query = db.query(models.User).filter(models.User.activ == True)
    if body.doar_abonati:
        query = query.filter(models.User.newsletter_consimtit == True)
    utilizatori = query.all()

    if not utilizatori:
        return {"mesaj": "Niciun utilizator de notificat.", "trimise": 0}

    def trimite_bulk():
        for u in utilizatori:
            _trimite_email(u.email, body.subiect, body.corp_html)

    threading.Thread(target=trimite_bulk, daemon=True).start()
    return {"mesaj": f"Se trimit {len(utilizatori)} emailuri în fundal.", "trimise": len(utilizatori)}
