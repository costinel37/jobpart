from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from database import get_db
import models
from auth import require_rol

router = APIRouter(prefix="/api/alerts", tags=["Job Alerts"])


class AlertCreate(BaseModel):
    categorie: Optional[str] = None
    oras: Optional[str] = None
    salariu_min: Optional[int] = None


class AlertOut(BaseModel):
    id: int
    categorie: Optional[str]
    oras: Optional[str]
    salariu_min: Optional[int]
    activ: bool

    class Config:
        from_attributes = True


@router.get("", response_model=List[AlertOut])
def lista_alerts(db: Session = Depends(get_db), current_user=Depends(require_rol("candidat"))):
    return db.query(models.JobAlert).filter(
        models.JobAlert.user_id == current_user.id
    ).all()


@router.post("", response_model=AlertOut)
def creeaza_alert(
    data: AlertCreate,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    if not data.categorie and not data.oras:
        raise HTTPException(status_code=400, detail="Specifică cel puțin o categorie sau un oraș.")

    existent = db.query(models.JobAlert).filter(
        models.JobAlert.user_id == current_user.id,
        models.JobAlert.categorie == data.categorie,
        models.JobAlert.oras == data.oras,
    ).first()
    if existent:
        raise HTTPException(status_code=400, detail="Ai deja o alertă pentru aceste criterii.")

    alert = models.JobAlert(
        user_id=current_user.id,
        categorie=data.categorie,
        oras=data.oras,
        salariu_min=data.salariu_min,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return alert


@router.delete("/{alert_id}")
def sterge_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    alert = db.query(models.JobAlert).filter(
        models.JobAlert.id == alert_id,
        models.JobAlert.user_id == current_user.id
    ).first()
    if not alert:
        raise HTTPException(status_code=404, detail="Alerta nu există.")
    db.delete(alert)
    db.commit()
    return {"mesaj": "Alertă ștearsă."}
