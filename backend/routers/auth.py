from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.orm import Session
from database import get_db
import models, schemas
from auth import hash_parola, verifica_parola, creeaza_token, get_user_curent
from security import limiter

router = APIRouter(prefix="/api/auth", tags=["Autentificare"])


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
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    token = creeaza_token({"sub": str(user.id), "rol": user.rol})
    return {"access_token": token, "token_type": "bearer", "rol": user.rol, "nume": user.nume, "user_id": user.id}


@router.post("/login", response_model=schemas.Token)
@limiter.limit("10/minute")
def login(request: Request, credentials: schemas.UserLogin, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(
        models.User.email == credentials.email.lower().strip()
    ).first()

    # Același mesaj indiferent dacă emailul nu există sau parola e greșită (anti-enumeration)
    if not user or not verifica_parola(credentials.parola, user.parola_hash):
        raise HTTPException(status_code=401, detail="Email sau parolă incorectă.")
    if not user.activ:
        raise HTTPException(status_code=403, detail="Contul tău a fost dezactivat.")

    token = creeaza_token({"sub": str(user.id), "rol": user.rol})
    return {"access_token": token, "token_type": "bearer", "rol": user.rol, "nume": user.nume, "user_id": user.id}


@router.get("/utilizator/{user_id}", response_model=schemas.UserOut)
def get_profil_public(user_id: int, db: Session = Depends(get_db)):
    user = db.query(models.User).filter(models.User.id == user_id, models.User.activ == True).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilizatorul nu există.")
    return user


@router.get("/me", response_model=schemas.UserOut)
def get_me(current_user=Depends(get_user_curent)):
    return current_user


@router.put("/me", response_model=schemas.UserOut)
def update_me(data: schemas.UserUpdate, db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user
