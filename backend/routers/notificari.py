from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from datetime import datetime
from typing import Optional
from database import get_db
import models
from auth import get_user_curent

router = APIRouter(prefix="/api/notificari", tags=["Notificări"])


class NotificareOut(BaseModel):
    id: int
    tip: str
    mesaj: str
    link: Optional[str]
    citit: bool
    creat_la: datetime

    class Config:
        from_attributes = True


@router.get("", response_model=List[NotificareOut])
def lista_notificari(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    return db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id
    ).order_by(models.Notification.creat_la.desc()).limit(50).all()


@router.get("/necitite/count")
def numar_necitite(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    count = db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.citit == False
    ).count()
    return {"count": count}


@router.put("/citeste-toate")
def citeste_toate(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    db.query(models.Notification).filter(
        models.Notification.user_id == current_user.id,
        models.Notification.citit == False
    ).update({"citit": True})
    db.commit()
    return {"mesaj": "Toate notificările marcate ca citite."}


@router.delete("/{notif_id}")
def sterge_notificare(notif_id: int, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    db.query(models.Notification).filter(
        models.Notification.id == notif_id,
        models.Notification.user_id == current_user.id
    ).delete()
    db.commit()
    return {"mesaj": "Șters."}
