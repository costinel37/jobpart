from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas
from auth import require_rol

router = APIRouter(prefix="/api/admin", tags=["Admin"])


@router.get("/utilizatori", response_model=List[schemas.UserOut])
def toti_utilizatorii(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    return db.query(models.User).order_by(models.User.creat_la.desc()).all()


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
    db.commit()
    status = "activat" if user.activ else "dezactivat"
    return {"mesaj": f"Utilizatorul a fost {status}."}


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

    user.rol = rol_nou
    db.commit()
    return {"mesaj": f"Rolul a fost schimbat în '{rol_nou}'."}


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

    return {
        "utilizatori": total_utilizatori,
        "candidati": total_candidati,
        "angajatori": total_angajatori,
        "joburi_active": total_joburi,
        "total_aplicari": total_aplicari,
        "aplicari_acceptate": aplicari_acceptate,
    }


@router.get("/toate-joburile", response_model=List[schemas.JobOut])
def toate_joburile(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    return db.query(models.Job).order_by(models.Job.creat_la.desc()).all()


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
    db.commit()
    return {"mesaj": "Job dezactivat de admin."}
