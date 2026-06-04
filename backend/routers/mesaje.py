from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel, field_validator
from typing import List, Optional
from datetime import datetime
import re
from database import get_db
import models
from auth import get_user_curent
from notificari_service import creeaza_notificare
from security import limiter

router = APIRouter(prefix="/api/mesaje", tags=["Mesaje"])

_TAG_RE = re.compile(r'<[^>]+>')

def _strip_html(v: str) -> str:
    return _TAG_RE.sub('', v).strip()


class MesajCreate(BaseModel):
    destinatar_id: int
    subiect: str
    continut: str

    @field_validator('subiect')
    @classmethod
    def valideaza_subiect(cls, v: str) -> str:
        v = _strip_html(v)
        if not v:
            raise ValueError('Subiectul nu poate fi gol.')
        if len(v) > 200:
            raise ValueError('Subiectul nu poate depăși 200 de caractere.')
        return v

    @field_validator('continut')
    @classmethod
    def valideaza_continut(cls, v: str) -> str:
        v = _strip_html(v)
        if not v:
            raise ValueError('Conținutul mesajului nu poate fi gol.')
        if len(v) > 5000:
            raise ValueError('Mesajul nu poate depăși 5000 de caractere.')
        return v


class MesajOut(BaseModel):
    id: int
    expeditor_id: int
    expeditor_nume: str = ""
    destinatar_id: int
    destinatar_nume: str = ""
    subiect: str
    continut: str
    citit: bool
    creat_la: datetime

    class Config:
        from_attributes = True


@router.get("/cauta-utilizatori")
def cauta_utilizatori(
    q: str = Query(..., min_length=2),
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    """Caută utilizatori după nume pentru formularul de mesaj nou."""
    users = (
        db.query(models.User)
        .filter(
            models.User.activ == True,
            models.User.id != current_user.id,
            models.User.nume.ilike(f"%{q}%"),
        )
        .limit(10)
        .all()
    )
    return [{"id": u.id, "nume": u.nume, "rol": u.rol} for u in users]


@router.post("", response_model=MesajOut)
@limiter.limit("20/minute")
def trimite_mesaj(request: Request, data: MesajCreate, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    if data.destinatar_id == current_user.id:
        raise HTTPException(status_code=400, detail="Nu poți trimite mesaj ție însuți.")
    destinatar = db.query(models.User).filter(models.User.id == data.destinatar_id, models.User.activ == True).first()
    if not destinatar:
        raise HTTPException(status_code=404, detail="Destinatarul nu există.")

    msg = models.Message(
        expeditor_id=current_user.id,
        destinatar_id=data.destinatar_id,
        subiect=data.subiect.strip(),
        continut=data.continut.strip(),
    )
    db.add(msg)
    db.commit()
    db.refresh(msg)

    creeaza_notificare(
        db, data.destinatar_id,
        tip="mesaj_nou",
        mesaj=f"Mesaj nou de la {current_user.nume}: {data.subiect[:60]}",
        link="/static/mesaje.html",
    )

    out = MesajOut.model_validate(msg)
    out.expeditor_nume = current_user.nume
    out.destinatar_nume = destinatar.nume
    return out


@router.get("/inbox", response_model=List[MesajOut])
def inbox(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    msgs = db.query(models.Message).filter(
        models.Message.destinatar_id == current_user.id
    ).order_by(models.Message.creat_la.desc()).all()
    rezultate = []
    for m in msgs:
        out = MesajOut.model_validate(m)
        out.expeditor_nume = m.expeditor.nume if m.expeditor else ""
        out.destinatar_nume = m.destinatar.nume if m.destinatar else ""
        rezultate.append(out)
    return rezultate


@router.get("/trimise", response_model=List[MesajOut])
def trimise(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    msgs = db.query(models.Message).filter(
        models.Message.expeditor_id == current_user.id
    ).order_by(models.Message.creat_la.desc()).all()
    rezultate = []
    for m in msgs:
        out = MesajOut.model_validate(m)
        out.expeditor_nume = m.expeditor.nume if m.expeditor else ""
        out.destinatar_nume = m.destinatar.nume if m.destinatar else ""
        rezultate.append(out)
    return rezultate


@router.put("/{msg_id}/citit")
def marcheaza_citit(msg_id: int, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    msg = db.query(models.Message).filter(
        models.Message.id == msg_id,
        models.Message.destinatar_id == current_user.id
    ).first()
    if not msg:
        raise HTTPException(status_code=404, detail="Mesajul nu există.")
    msg.citit = True
    db.commit()
    return {"mesaj": "Marcat ca citit."}


@router.get("/necitite/count")
def numar_necitite(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    count = db.query(models.Message).filter(
        models.Message.destinatar_id == current_user.id,
        models.Message.citit == False
    ).count()
    return {"count": count}
