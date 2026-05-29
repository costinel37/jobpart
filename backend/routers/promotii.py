from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
from database import get_db
import models
import logging
from auth import get_user_curent, require_rol
from notificari_service import creeaza_notificare

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/promotii", tags=["Promovare"])

PLANURI = {
    "7zile":  {"zile": 7,  "pret": 25, "nume": "Starter",  "descriere": "Ideal pentru joburi urgente"},
    "14zile": {"zile": 14, "pret": 40, "nume": "Standard", "descriere": "Cel mai ales de angajatori"},
    "30zile": {"zile": 30, "pret": 70, "nume": "Premium",  "descriere": "Vizibilitate maximă"},
}


class CererePromoBody(BaseModel):
    job_id: int
    plan: str


class AprobaBody(BaseModel):
    mesaj: Optional[str] = None


@router.get("/planuri")
def get_planuri():
    return [
        {"id": k, "zile": v["zile"], "pret": v["pret"], "nume": v["nume"], "descriere": v["descriere"]}
        for k, v in PLANURI.items()
    ]


@router.post("/cerere")
def trimite_cerere(
    body: CererePromoBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator"))
):
    if body.plan not in PLANURI:
        raise HTTPException(status_code=400, detail="Plan invalid. Alege: 7zile, 14zile sau 30zile.")

    job = db.query(models.Job).filter(
        models.Job.id == body.job_id,
        models.Job.angajator_id == current_user.id,
        models.Job.activ == True,
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Jobul nu există sau nu îți aparține.")

    # Verifică dacă jobul e deja promovat activ
    if job.promovat and job.promovat_pana and job.promovat_pana > datetime.utcnow():
        raise HTTPException(status_code=400, detail="Jobul este deja promovat activ.")

    # Verifică cerere dublă în așteptare
    existent = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.job_id == body.job_id,
        models.PromovareCerere.status == "in_asteptare",
    ).first()
    if existent:
        raise HTTPException(status_code=400, detail="Există deja o cerere în așteptare pentru acest job.")

    plan_info = PLANURI[body.plan]
    cerere = models.PromovareCerere(
        job_id=body.job_id,
        angajator_id=current_user.id,
        plan=body.plan,
        pret=plan_info["pret"],
        status="in_asteptare",
    )
    db.add(cerere)
    db.commit()
    db.refresh(cerere)

    return {
        "id": cerere.id,
        "job_id": cerere.job_id,
        "plan": cerere.plan,
        "pret": cerere.pret,
        "status": cerere.status,
        "mesaj": f"Cererea a fost trimisă! Jobul '{job.titlu}' va fi promovat după aprobare (maxim 24h).",
    }


@router.get("/cereri-mele")
def cereri_mele(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator"))
):
    cereri = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.angajator_id == current_user.id
    ).order_by(models.PromovareCerere.creat_la.desc()).all()

    return [
        {
            "id": c.id,
            "job_id": c.job_id,
            "job_titlu": c.job.titlu if c.job else None,
            "plan": c.plan,
            "pret": c.pret,
            "status": c.status,
            "mesaj_admin": c.mesaj_admin,
            "creat_la": c.creat_la.isoformat(),
            "procesata_la": c.procesata_la.isoformat() if c.procesata_la else None,
        }
        for c in cereri
    ]


@router.get("/cereri")
def toate_cererile(
    status: Optional[str] = Query(None),
    pagina: int = Query(1, ge=1),
    per_pagina: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    q = db.query(models.PromovareCerere)
    if status:
        q = q.filter(models.PromovareCerere.status == status)

    total = q.count()
    cereri = q.order_by(models.PromovareCerere.creat_la.desc()) \
               .offset((pagina - 1) * per_pagina) \
               .limit(per_pagina) \
               .all()

    return {
        "total": total,
        "cereri": [
            {
                "id": c.id,
                "job_id": c.job_id,
                "job_titlu": c.job.titlu if c.job else None,
                "angajator_id": c.angajator_id,
                "angajator_nume": c.angajator.nume if c.angajator else None,
                "plan": c.plan,
                "pret": c.pret,
                "status": c.status,
                "mesaj_admin": c.mesaj_admin,
                "creat_la": c.creat_la.isoformat(),
                "procesata_la": c.procesata_la.isoformat() if c.procesata_la else None,
            }
            for c in cereri
        ]
    }


@router.put("/cereri/{cerere_id}/aproba")
def aproba_cerere(
    cerere_id: int,
    body: AprobaBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    cerere = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.id == cerere_id
    ).first()
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu există.")
    if cerere.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesată.")

    plan_info = PLANURI.get(cerere.plan)
    if not plan_info:
        raise HTTPException(status_code=400, detail="Plan invalid în cerere.")

    # Activează promovarea jobului
    job = db.query(models.Job).filter(models.Job.id == cerere.job_id).first()
    if job:
        job.promovat = True
        job.promovat_pana = datetime.utcnow() + timedelta(days=plan_info["zile"])
        job.avertisment_expirare = False

    cerere.status = "aprobata"
    cerere.procesata_la = datetime.utcnow()
    if body.mesaj:
        cerere.mesaj_admin = body.mesaj

    creeaza_notificare(
        db, cerere.angajator_id,
        tip="promotie_aprobata",
        mesaj=f"Cererea de promovare pentru '{job.titlu if job else 'job'}' a fost aprobată! Jobul este acum promovat {plan_info['zile']} zile.",
        link="/static/dashboard-angajator.html",
    )
    db.commit()

    return {"mesaj": f"Cererea a fost aprobată. Jobul este promovat pentru {plan_info['zile']} zile."}


@router.put("/cereri/{cerere_id}/respinge")
def respinge_cerere(
    cerere_id: int,
    body: AprobaBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    cerere = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.id == cerere_id
    ).first()
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu există.")
    if cerere.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesată.")

    cerere.status = "respinsa"
    cerere.procesata_la = datetime.utcnow()
    cerere.mesaj_admin = body.mesaj

    job = db.query(models.Job).filter(models.Job.id == cerere.job_id).first()
    creeaza_notificare(
        db, cerere.angajator_id,
        tip="promotie_respinsa",
        mesaj=f"Cererea de promovare pentru '{job.titlu if job else 'job'}' a fost respinsă.{' Motiv: ' + body.mesaj if body.mesaj else ''}",
        link="/static/dashboard-angajator.html",
    )
    db.commit()

    return {"mesaj": "Cererea a fost respinsă."}




@router.get("/statistici")
def statistici_promotii(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    total = db.query(models.PromovareCerere).count()
    in_asteptare = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.status == "in_asteptare"
    ).count()
    aprobate = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.status == "aprobata"
    ).count()
    respinse = db.query(models.PromovareCerere).filter(
        models.PromovareCerere.status == "respinsa"
    ).count()

    venituri_totale = db.query(func.sum(models.PromovareCerere.pret)).filter(
        models.PromovareCerere.status == "aprobata"
    ).scalar() or 0

    prima_zi_luna = datetime.utcnow().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    venituri_luna = db.query(func.sum(models.PromovareCerere.pret)).filter(
        models.PromovareCerere.status == "aprobata",
        models.PromovareCerere.procesata_la >= prima_zi_luna,
    ).scalar() or 0

    return {
        "total_cereri": total,
        "in_asteptare": in_asteptare,
        "aprobate": aprobate,
        "respinse": respinse,
        "venituri_totale_ron": int(venituri_totale),
        "venituri_luna_curenta_ron": int(venituri_luna),
    }
