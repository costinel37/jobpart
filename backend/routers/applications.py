from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
import threading
from database import get_db
import models, schemas
from auth import get_user_curent, require_rol
from email_service import email_aplicare_noua, email_status_schimbat
from notificari_service import creeaza_notificare

router = APIRouter(prefix="/api/aplicari", tags=["Aplicări"])


def _email_async(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


@router.post("", response_model=schemas.ApplicationOut)
def aplica_la_job(
    data: schemas.ApplicationCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    job = db.query(models.Job).filter(models.Job.id == data.job_id, models.Job.activ == True).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există sau nu mai este activ.")

    existent = db.query(models.Application).filter(
        models.Application.candidat_id == current_user.id,
        models.Application.job_id == data.job_id
    ).first()
    if existent:
        raise HTTPException(status_code=400, detail="Ai aplicat deja la acest job.")

    aplicare = models.Application(
        candidat_id=current_user.id,
        job_id=data.job_id,
        scrisoare=data.scrisoare,
        cv_path=data.cv_path,
        cv_nume_original=data.cv_nume_original,
    )
    db.add(aplicare)
    db.commit()
    db.refresh(aplicare)

    angajator = db.query(models.User).filter(models.User.id == job.angajator_id).first()
    if angajator:
        _email_async(email_aplicare_noua, angajator.email, job.titlu,
                     job.companie, current_user.nume, job.id, aplicare.id)
        creeaza_notificare(db, angajator.id, "aplicare_noua",
                           f"{current_user.nume} a aplicat la '{job.titlu}'",
                           "/static/dashboard-angajator.html")
    return aplicare


@router.get("/ale-mele", response_model=List[schemas.ApplicationOut])
def aplicarile_mele(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    return db.query(models.Application).filter(
        models.Application.candidat_id == current_user.id
    ).order_by(models.Application.creat_la.desc()).all()


@router.get("/pentru-job/{job_id}", response_model=List[schemas.ApplicationOut])
def aplicari_pentru_job(
    job_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    job = db.query(models.Job).filter(models.Job.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există.")
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai acces la aplicările acestui job.")

    return db.query(models.Application).filter(
        models.Application.job_id == job_id
    ).order_by(models.Application.creat_la.desc()).all()


@router.put("/{aplicare_id}/status")
def actualizeaza_status(
    aplicare_id: int,
    data: schemas.ApplicationStatusUpdate,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin"))
):
    if data.status not in ["trimisa", "vizualizata", "acceptata", "respinsa"]:
        raise HTTPException(status_code=400, detail="Status invalid.")

    aplicare = db.query(models.Application).filter(models.Application.id == aplicare_id).first()
    if not aplicare:
        raise HTTPException(status_code=404, detail="Aplicarea nu există.")

    job = aplicare.job
    if job.angajator_id != current_user.id and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai acces la această aplicare.")

    status_vechi = aplicare.status
    aplicare.status = data.status
    db.commit()

    if data.status != status_vechi and data.status in ("vizualizata", "acceptata", "respinsa"):
        candidat = db.query(models.User).filter(models.User.id == aplicare.candidat_id).first()
        if candidat:
            _email_async(email_status_schimbat, candidat.email, job.titlu, job.companie, data.status)
            labels = {"vizualizata": "vizualizată", "acceptata": "acceptată ✅", "respinsa": "respinsă"}
            creeaza_notificare(db, candidat.id, "status_schimbat",
                               f"Aplicarea ta la '{job.titlu}' a fost {labels.get(data.status, data.status)}",
                               "/static/dashboard-candidat.html")

    return {"mesaj": f"Status actualizat la '{data.status}'."}


@router.delete("/{aplicare_id}")
def sterge_aplicare(
    aplicare_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    aplicare = db.query(models.Application).filter(
        models.Application.id == aplicare_id,
        models.Application.candidat_id == current_user.id
    ).first()
    if not aplicare:
        raise HTTPException(status_code=404, detail="Aplicarea nu există.")
    if aplicare.status != "trimisa":
        raise HTTPException(status_code=400, detail="Nu poți retrage o aplicare procesată.")

    db.delete(aplicare)
    db.commit()
    return {"mesaj": "Aplicarea a fost retrasă."}
