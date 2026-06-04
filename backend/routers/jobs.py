from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from sqlalchemy import or_, case
from typing import Optional, List
from datetime import datetime, timedelta
import threading
from database import get_db
import models, schemas
from auth import get_user_curent, require_rol
from geocoding import geocodeaza_oras, distanta_km
from telegram_service import notifica_job_nou

ZILE_GRATUIT = 365

router = APIRouter(prefix="/api/jobs", tags=["Joburi"])


def _geocodeaza_async(job_id: int, oras: str):
    """Geocodare în background după ce jobul e salvat."""
    from database import SessionLocal
    db = SessionLocal()
    try:
        coords = geocodeaza_oras(oras)
        if coords:
            job = db.query(models.Job).filter(models.Job.id == job_id).first()
            if job:
                job.lat, job.lng = coords
                db.commit()
    finally:
        db.close()


@router.get("", response_model=List[schemas.JobOut])
def lista_joburi(
    cauta: Optional[str] = Query(None),
    oras: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    salariu_min: Optional[int] = Query(None),
    salariu_max: Optional[int] = Query(None),
    tip_program: Optional[str] = Query(None),
    postate_in: Optional[int] = Query(None),
    sortare: Optional[str] = Query("recent"),
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    now_ts = datetime.utcnow()
    query = db.query(models.Job).filter(
        models.Job.activ == True,
        or_(models.Job.expira_la == None, models.Job.expira_la > now_ts)
    )

    if cauta:
        query = query.filter(or_(
            models.Job.titlu.ilike(f"%{cauta}%"),
            models.Job.companie.ilike(f"%{cauta}%"),
            models.Job.descriere.ilike(f"%{cauta}%"),
            models.Job.oras.ilike(f"%{cauta}%"),
        ))
    if oras:
        query = query.filter(models.Job.oras.ilike(f"%{oras}%"))
    if categorie:
        query = query.filter(models.Job.categorie == categorie)
    if tip_program:
        query = query.filter(models.Job.tip_program == tip_program)
    if salariu_min is not None:
        query = query.filter(models.Job.salariu_min >= salariu_min)
    if salariu_max is not None:
        query = query.filter(models.Job.salariu_max <= salariu_max)
    if postate_in:
        de_la = datetime.utcnow() - timedelta(days=postate_in)
        query = query.filter(models.Job.creat_la >= de_la)

    # Promovate întotdeauna primele
    promovat_col = case((models.Job.promovat == True, 0), else_=1)

    if sortare == "salariu_desc":
        query = query.order_by(promovat_col, models.Job.salariu_max.desc().nullslast())
    elif sortare == "salariu_asc":
        query = query.order_by(promovat_col, models.Job.salariu_min.asc().nullslast())
    else:
        query = query.order_by(promovat_col, models.Job.creat_la.desc())

    return query.offset((pagina - 1) * per_pagina).limit(per_pagina).all()


@router.get("/count")
def numara_joburi(
    cauta: Optional[str] = Query(None),
    oras: Optional[str] = Query(None),
    categorie: Optional[str] = Query(None),
    salariu_min: Optional[int] = Query(None),
    salariu_max: Optional[int] = Query(None),
    tip_program: Optional[str] = Query(None),
    postate_in: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    query = db.query(models.Job).filter(
        models.Job.activ == True,
        or_(models.Job.expira_la == None, models.Job.expira_la > datetime.utcnow())
    )
    if cauta:
        query = query.filter(or_(
            models.Job.titlu.ilike(f"%{cauta}%"),
            models.Job.companie.ilike(f"%{cauta}%"),
        ))
    if oras:
        query = query.filter(models.Job.oras.ilike(f"%{oras}%"))
    if categorie:
        query = query.filter(models.Job.categorie == categorie)
    if tip_program:
        query = query.filter(models.Job.tip_program == tip_program)
    if salariu_min is not None:
        query = query.filter(models.Job.salariu_min >= salariu_min)
    if salariu_max is not None:
        query = query.filter(models.Job.salariu_max <= salariu_max)
    if postate_in:
        de_la = datetime.utcnow() - timedelta(days=postate_in)
        query = query.filter(models.Job.creat_la >= de_la)
    return {"total": query.count()}


@router.get("/nearby", response_model=List[schemas.JobOut])
def joburi_aproape(
    lat: float = Query(...),
    lng: float = Query(...),
    raza_km: float = Query(25, ge=1, le=200),
    db: Session = Depends(get_db)
):
    """Returnează joburile în raza specificată față de coordonatele date."""
    toate = db.query(models.Job).filter(
        models.Job.activ == True,
        models.Job.lat.isnot(None),
        models.Job.lng.isnot(None),
    ).all()

    rezultate = []
    for job in toate:
        dist = distanta_km(lat, lng, job.lat, job.lng)
        if dist <= raza_km:
            rezultate.append((dist, job))

    rezultate.sort(key=lambda x: x[0])
    return [job for _, job in rezultate[:50]]


@router.get("/harta", response_model=List[schemas.JobOut])
def joburi_pentru_harta(db: Session = Depends(get_db)):
    """Toate joburile cu coordonate pentru afișare pe hartă."""
    return db.query(models.Job).filter(
        models.Job.activ == True,
        models.Job.lat.isnot(None),
        models.Job.lng.isnot(None),
    ).all()


@router.get("/mele/toate", response_model=List[schemas.JobOut])
def joburile_mele(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    return db.query(models.Job).filter(
        models.Job.angajator_id == current_user.id
    ).order_by(models.Job.creat_la.desc()).all()


@router.get("/{job_id}", response_model=schemas.JobOut)
def detalii_job(job_id: int, request: Request, db: Session = Depends(get_db)):
    job = db.query(models.Job).filter(models.Job.id == job_id, models.Job.activ == True).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    # Înregistrează vizualizarea unică (IP hash pentru GDPR)
    import hashlib
    ip = request.headers.get("CF-Connecting-IP") or request.headers.get("X-Forwarded-For", "").split(",")[0].strip() or request.client.host
    ip_hash = hashlib.sha256(ip.encode()).hexdigest()[:32]
    try:
        view = models.JobView(job_id=job_id, ip_hash=ip_hash)
        db.add(view)
        db.commit()
    except Exception:
        db.rollback()
    return job


@router.get("/{job_id}/statistici")
def statistici_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Acces interzis.")

    vizualizari = db.query(models.JobView).filter(models.JobView.job_id == job_id).count()
    aplicari = db.query(models.Application).filter(models.Application.job_id == job_id).count()
    acceptate = db.query(models.Application).filter(
        models.Application.job_id == job_id,
        models.Application.status == "acceptata"
    ).count()

    return {
        "vizualizari": vizualizari,
        "aplicari": aplicari,
        "acceptate": acceptate,
        "rata_aplicare": round(aplicari / vizualizari * 100, 1) if vizualizari > 0 else 0,
    }


@router.post("", response_model=schemas.JobOut)
def creeaza_job(
    job_data: schemas.JobCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = models.Job(
        **job_data.model_dump(),
        angajator_id=current_user.id,
        expira_la=datetime.utcnow() + timedelta(days=ZILE_GRATUIT),
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    threading.Thread(target=_geocodeaza_async, args=(job.id, job.oras), daemon=True).start()
    notifica_job_nou(job)
    return job


@router.put("/{job_id}", response_model=schemas.JobOut)
def actualizeaza_job(
    job_id: int,
    job_data: schemas.JobCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai permisiunea să editezi acest job.")

    oras_schimbat = job.oras != job_data.oras
    for field, value in job_data.model_dump(exclude_unset=True).items():
        setattr(job, field, value)
    db.commit()
    db.refresh(job)

    if oras_schimbat:
        threading.Thread(target=_geocodeaza_async, args=(job.id, job.oras), daemon=True).start()
    return job


@router.post("/{job_id}/reinnoire")
def reinnoire_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai permisiunea să reînnoiești acest job.")
    job.activ = True
    job.expira_la = datetime.utcnow() + timedelta(days=ZILE_GRATUIT)
    job.avertisment_job = False
    db.commit()
    return {"mesaj": f"Anunț reînnoit pentru {ZILE_GRATUIT} de zile.", "expira_la": job.expira_la}


@router.post("/{job_id}/promoveaza")
def promoveaza_job(
    job_id: int,
    zile: int = 7,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    """Adminul promovează un job (gratuit sau după confirmare plată)."""
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    job.promovat = True
    job.promovat_pana = datetime.utcnow() + timedelta(days=zile)
    db.commit()
    return {"mesaj": f"Job promovat pentru {zile} zile.", "promovat_pana": job.promovat_pana}


@router.delete("/{job_id}/promoveaza")
def anuleaza_promovare(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    job.promovat = False
    job.promovat_pana = None
    db.commit()
    return {"mesaj": "Promovare anulată."}


@router.delete("/{job_id}")
def sterge_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu a fost găsit.")
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai permisiunea să ștergi acest job.")
    job.activ = False
    db.commit()
    return {"mesaj": "Job dezactivat cu succes."}
