from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from pydantic import BaseModel
import secrets
import threading
from database import get_db
import models, schemas
from auth import hash_parola, verifica_parola, creeaza_token, get_user_curent
from schemas import PublicUserOut
from security import limiter
from email_service import email_confirmare_cont, email_resetare_parola

router = APIRouter(prefix="/api/auth", tags=["Autentificare"])


def _token_unic() -> str:
    return secrets.token_urlsafe(48)


@router.post("/register", response_model=schemas.Token)
@limiter.limit("5/minute")
def register(request: Request, user_data: schemas.UserRegister, db: Session = Depends(get_db)):
    if user_data.rol not in ["candidat", "angajator"]:
        raise HTTPException(status_code=400, detail="Rol invalid.")

    if len(user_data.parola) < 8:
        raise HTTPException(status_code=400, detail="Parola trebuie să aibă minim 8 caractere.")

    existent = db.query(models.User).filter(models.User.email == user_data.email).first()
    if existent:
        raise HTTPException(status_code=400, detail="Email-ul este deja înregistrat.")

    user = models.User(
        nume=user_data.nume.strip(),
        email=user_data.email.lower().strip(),
        parola_hash=hash_parola(user_data.parola),
        rol=user_data.rol,
        telefon=user_data.telefon,
        oras=user_data.oras,
        email_confirmat=False,
        newsletter_consimtit=user_data.newsletter_consimtit,
        gdpr_consimtit_la=datetime.utcnow(),
        data_nasterii=user_data.data_nasterii,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    # Trimite email confirmare
    token = _token_unic()
    verificare = models.EmailVerification(
        user_id=user.id,
        token=token,
        expira_la=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(verificare)
    db.commit()
    threading.Thread(target=email_confirmare_cont, args=(user.email, token), daemon=True).start()

    access_token = creeaza_token({"sub": str(user.id), "rol": user.rol})
    return {"access_token": access_token, "token_type": "bearer", "rol": user.rol, "nume": user.nume, "user_id": user.id}


@router.post("/login", response_model=schemas.Token)
@limiter.limit("10/minute")
def login(request: Request, credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.email == credentials.email.lower().strip()
    ).first()

    if not user or not verifica_parola(credentials.parola, user.parola_hash):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă.")
    if not user.activ:
        raise HTTPException(status_code=403, detail="Contul tău a fost dezactivat.")

    access_token = creeaza_token({"sub": str(user.id), "rol": user.rol})
    return {"access_token": access_token, "token_type": "bearer", "rol": user.rol, "nume": user.nume, "user_id": user.id}


@router.post("/confirma-email")
def confirma_email(token: str, db: Session = Depends(get_db)):
    verificare = db.query(models.EmailVerification).filter(
        models.EmailVerification.token == token,
        models.EmailVerification.expira_la > datetime.utcnow(),
    ).first()
    if not verificare:
        raise HTTPException(status_code=400, detail="Link invalid sau expirat.")

    user = db.query(models.User).filter(models.User.id == verificare.user_id).first()
    if user:
        user.email_confirmat = True
    db.delete(verificare)
    db.commit()
    return {"mesaj": "Email confirmat cu succes! Te poți autentifica."}


@router.post("/retrimite-confirmare")
@limiter.limit("3/minute")
def retrimite_confirmare(request: Request, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    if current_user.email_confirmat:
        raise HTTPException(status_code=400, detail="Email-ul este deja confirmat.")

    db.query(models.EmailVerification).filter(
        models.EmailVerification.user_id == current_user.id
    ).delete()

    token = _token_unic()
    verificare = models.EmailVerification(
        user_id=current_user.id,
        token=token,
        expira_la=datetime.utcnow() + timedelta(hours=24),
    )
    db.add(verificare)
    db.commit()
    threading.Thread(target=email_confirmare_cont, args=(current_user.email, token), daemon=True).start()
    return {"mesaj": "Email de confirmare retrimis."}


class CerereResetareDate(BaseModel):
    email: str


@router.post("/reseteaza-parola/cerere")
@limiter.limit("3/minute")
def cerere_resetare(request: Request, data: CerereResetareDate, db: Session = Depends(get_db)):
    email = data.email
    user = db.query(models.User).filter(
        models.User.email == email.lower().strip(),
        models.User.activ == True
    ).first()
    # Același răspuns indiferent dacă emailul există (anti-enumeration)
    if user:
        db.query(models.PasswordReset).filter(
            models.PasswordReset.user_id == user.id
        ).delete()
        token = _token_unic()
        reset = models.PasswordReset(
            user_id=user.id,
            token=token,
            expira_la=datetime.utcnow() + timedelta(hours=1),
        )
        db.add(reset)
        db.commit()
        threading.Thread(target=email_resetare_parola, args=(user.email, token), daemon=True).start()
    return {"mesaj": "Dacă emailul există, vei primi un link de resetare."}


class ResetareParolaDate(BaseModel):
    token: str
    parola_noua: str


@router.post("/reseteaza-parola/confirma")
def confirma_resetare(data: ResetareParolaDate, db: Session = Depends(get_db)):
    token = data.token
    parola_noua = data.parola_noua
    if len(parola_noua) < 8:
        raise HTTPException(status_code=400, detail="Parola trebuie să aibă minim 8 caractere.")

    reset = db.query(models.PasswordReset).filter(
        models.PasswordReset.token == token,
        models.PasswordReset.expira_la > datetime.utcnow(),
        models.PasswordReset.folosit == False,
    ).first()
    if not reset:
        raise HTTPException(status_code=400, detail="Link invalid sau expirat.")

    user = db.query(models.User).filter(models.User.id == reset.user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")

    user.parola_hash = hash_parola(parola_noua)
    user.parola_schimbata_la = datetime.utcnow()
    reset.folosit = True
    db.commit()
    return {"mesaj": "Parola a fost schimbată cu succes! Te poți autentifica."}


@router.get("/utilizator/{user_id}", response_model=PublicUserOut)
def get_profil_public(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id, models.User.activ == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")
    luni_ro = ["ian", "feb", "mar", "apr", "mai", "iun", "iul", "aug", "sep", "oct", "nov", "dec"]
    membru_din = f"{luni_ro[user.creat_la.month - 1]} {user.creat_la.year}"
    return PublicUserOut(
        id=user.id,
        nume=user.nume,
        rol=user.rol,
        despre=user.despre,
        membru_din=membru_din,
    )


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user=Depends(get_user_curent)):
    return current_user


@router.put("/me", response_model=schemas.UserOut)
@limiter.limit("20/minute")
def update_me(request: Request, data: schemas.UserUpdate, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


class SchimbaParolaDate(BaseModel):
    parola_curenta: str
    parola_noua: str


@router.put("/me/schimba-parola")
@limiter.limit("5/minute")
def schimba_parola(request: Request, data: SchimbaParolaDate, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    if len(data.parola_noua) < 8:
        raise HTTPException(status_code=400, detail="Parola trebuie să aibă minim 8 caractere.")
    if not verifica_parola(data.parola_curenta, current_user.parola_hash):
        raise HTTPException(status_code=400, detail="Parola curentă este incorectă.")
    current_user.parola_hash = hash_parola(data.parola_noua)
    current_user.parola_schimbata_la = datetime.utcnow()
    db.commit()
    return {"mesaj": "Parola a fost schimbată cu succes!"}


class StergeContDate(BaseModel):
    parola_curenta: str


@router.delete("/me")
def sterge_cont(data: StergeContDate, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    if not verifica_parola(data.parola_curenta, current_user.parola_hash):
        raise HTTPException(status_code=400, detail="Parola incorectă. Ștergerea contului a fost anulată.")
    import os as _os
    from config import UPLOAD_DIR

    # Șterge CV-urile de pe disk
    for aplicare in current_user.aplicari:
        if aplicare.cv_path:
            cale = _os.path.join(UPLOAD_DIR, aplicare.cv_path)
            if _os.path.exists(cale):
                _os.remove(cale)
            aplicare.cv_path = None
            aplicare.cv_nume_original = None

    # Anonimizează datele personale (păstrăm înregistrările pentru integritate referențială)
    ts = int(datetime.utcnow().timestamp())
    current_user.email = f"deleted_{current_user.id}_{ts}@deleted.jobpart.ro"
    current_user.nume = "Utilizator Șters"
    current_user.telefon = None
    current_user.oras = None
    current_user.despre = None
    current_user.parola_hash = "DELETED"
    current_user.activ = False
    current_user.email_confirmat = False

    # Șterge mesajele private
    db.query(models.Message).filter(
        (models.Message.expeditor_id == current_user.id) |
        (models.Message.destinatar_id == current_user.id)
    ).delete(synchronize_session=False)

    # Șterge tokenurile de verificare/resetare
    db.query(models.EmailVerification).filter(models.EmailVerification.user_id == current_user.id).delete()
    db.query(models.PasswordReset).filter(models.PasswordReset.user_id == current_user.id).delete()

    db.commit()
    return {"mesaj": "Contul tău a fost șters. Datele personale au fost anonimizate."}
