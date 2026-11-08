from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import json

from database import get_db
import models
from auth import get_user_curent, get_user_optional, require_rol
from security import limiter

router = APIRouter(prefix="/api/candidati", tags=["Candidați CV"])


def _parse(text: Optional[str], default):
    if not text:
        return default
    try:
        return json.loads(text)
    except Exception:
        return default


def _curata_lista(items: Optional[list], campuri: List[str], max_items: int = 20) -> list:
    """Păstrează doar câmpurile permise (string-uri scurtate) și elimină intrările goale."""
    rezultat = []
    for item in (items or [])[:max_items]:
        if not isinstance(item, dict):
            continue
        curat = {}
        for c in campuri:
            val = str(item.get(c) or "").strip()
            curat[c] = val[:1000] if c == "descriere" else val[:150]
        if any(curat.values()):
            rezultat.append(curat)
    return rezultat


def _cv_to_dict(cv: models.CandidatCV, user: models.User) -> dict:
    return {
        "user_id": user.id,
        "nume": user.nume,
        "titlu_profesional": cv.titlu_profesional,
        "oras": user.oras,
        "email": user.email,
        "telefon": user.telefon,
        "despre": user.despre,
        "experienta": _parse(cv.experienta, []),
        "educatie": _parse(cv.educatie, []),
        "competente": _parse(cv.competente, []),
        "limbi": _parse(cv.limbi, []),
        "permis_auto": cv.permis_auto,
        "disponibilitate": cv.disponibilitate,
        "cv_vizibil": cv.cv_vizibil,
        "actualizat_la": cv.actualizat_la.isoformat() if cv.actualizat_la else None,
    }


class CVBody(BaseModel):
    titlu_profesional: Optional[str] = None
    experienta: Optional[list] = None
    educatie: Optional[list] = None
    competente: Optional[list] = None
    limbi: Optional[list] = None
    permis_auto: bool = False
    disponibilitate: Optional[str] = None
    cv_vizibil: bool = False  # GDPR: vizibil doar dacă candidatul alege explicit


@router.get("/cv")
def get_cv_propriu(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    """Returnează propriul CV structurat."""
    cv = db.query(models.CandidatCV).filter(models.CandidatCV.user_id == current_user.id).first()
    if not cv:
        return {
            "user_id": current_user.id,
            "nume": current_user.nume,
            "titlu_profesional": None,
            "oras": current_user.oras,
            "email": current_user.email,
            "telefon": current_user.telefon,
            "despre": current_user.despre,
            "experienta": [],
            "educatie": [],
            "competente": [],
            "limbi": [],
            "permis_auto": False,
            "disponibilitate": None,
            "cv_vizibil": False,
            "actualizat_la": None,
        }
    return _cv_to_dict(cv, current_user)


@router.put("/cv")
@limiter.limit("20/minute")
def salveaza_cv(request: Request, body: CVBody, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    """Salvează/actualizează propriul CV structurat."""
    cv = db.query(models.CandidatCV).filter(models.CandidatCV.user_id == current_user.id).first()
    if not cv:
        cv = models.CandidatCV(user_id=current_user.id)
        db.add(cv)

    cv.titlu_profesional = (body.titlu_profesional or "")[:200] or None
    cv.experienta = json.dumps(_curata_lista(body.experienta, ["companie", "pozitie", "perioada", "descriere"]), ensure_ascii=False)
    cv.educatie = json.dumps(_curata_lista(body.educatie, ["institutie", "nivel", "domeniu", "an"]), ensure_ascii=False)
    cv.competente = json.dumps([str(c).strip()[:60] for c in (body.competente or []) if str(c).strip()][:30], ensure_ascii=False)
    cv.limbi = json.dumps(_curata_lista(body.limbi, ["limba", "nivel"]), ensure_ascii=False)
    cv.permis_auto = body.permis_auto
    cv.disponibilitate = (body.disponibilitate or "")[:50] or None
    cv.cv_vizibil = body.cv_vizibil
    cv.actualizat_la = datetime.utcnow()

    db.commit()
    db.refresh(cv)
    return _cv_to_dict(cv, current_user)


@router.get("/{user_id}")
def get_cv_public(user_id: int, db: Session = Depends(get_db), viewer=Depends(get_user_optional)):
    """CV public al unui candidat. Datele de contact apar doar pentru angajatori, admini și titular."""
    user = db.query(models.User).filter(
        models.User.id == user_id,
        models.User.activ == True,
        models.User.rol == "candidat",
    ).first()
    if not user:
        raise HTTPException(status_code=404, detail="Candidatul nu există.")

    este_titular = viewer is not None and viewer.id == user_id
    cv = db.query(models.CandidatCV).filter(models.CandidatCV.user_id == user_id).first()
    if not cv or (not cv.cv_vizibil and not este_titular):
        raise HTTPException(status_code=404, detail="CV-ul nu este public.")

    rezultat = _cv_to_dict(cv, user)
    rezultat["este_titular"] = este_titular
    if not (este_titular or (viewer and viewer.rol in ("angajator", "admin"))):
        rezultat["email"] = None
        rezultat["telefon"] = None
    return rezultat


@router.get("")
def lista_candidati(
    skip: int = 0,
    limit: int = 20,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator", "admin")),
):
    """Lista candidaților cu CV public — pentru angajatori (planul trebuie să includă baza de CV-uri)."""
    from billing_service import get_entitlements
    if not get_entitlements(db, current_user)[1].cv_database:
        raise HTTPException(status_code=402, detail="Baza de CV-uri este disponibilă în planul Pro.")
    cvuri = (
        db.query(models.CandidatCV)
        .join(models.User, models.CandidatCV.user_id == models.User.id)
        .filter(
            models.CandidatCV.cv_vizibil == True,
            models.User.activ == True,
            models.User.rol == "candidat",
        )
        .order_by(models.CandidatCV.actualizat_la.desc())
        .offset(skip)
        .limit(min(limit, 50))
        .all()
    )
    rezultate = []
    for cv in cvuri:
        rezultate.append({
            "user_id": cv.user.id,
            "nume": cv.user.nume,
            "titlu_profesional": cv.titlu_profesional,
            "oras": cv.user.oras,
            "competente": _parse(cv.competente, [])[:5],
            "disponibilitate": cv.disponibilitate,
            "actualizat_la": cv.actualizat_la.isoformat() if cv.actualizat_la else None,
        })
    return rezultate
