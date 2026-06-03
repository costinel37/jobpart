from datetime import datetime, timedelta
from typing import Optional
import time
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from database import get_db
import models

from config import SECRET_KEY
ALGORITHM = "HS256"
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


def hash_parola(parola: str) -> str:
    return pwd_context.hash(parola)

def verifica_parola(parola: str, hash: str) -> bool:
    return pwd_context.verify(parola, hash)

TOKEN_EXPIRE_ZILE = 7

def creeaza_token(data: dict, expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    now = int(time.time())
    expire = now + int((expires_delta or timedelta(days=TOKEN_EXPIRE_ZILE)).total_seconds())
    to_encode.update({"iat": now, "exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

def get_user_curent(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalid sau expirat",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: int = payload.get("sub")
        token_iat: int = payload.get("iat")
        if user_id is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(models.User).filter(models.User.id == int(user_id)).first()
    if user is None or not user.activ:
        raise credentials_exception

    # Revocă tokenul dacă parola a fost schimbată după emiterea lui.
    # +1s grace period: iat e integer (secunde), parola_schimbata_la are microsecunde —
    # fără grace, un login imediat după reset pare emis "înainte" de schimbare.
    if user.parola_schimbata_la and token_iat:
        token_emis_la = datetime.utcfromtimestamp(token_iat)
        if user.parola_schimbata_la > token_emis_la + timedelta(seconds=1):
            raise credentials_exception

    return user

def require_rol(*roluri):
    def checker(user=Depends(get_user_curent)):
        if user.rol not in roluri:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Acces interzis pentru rolul tău"
            )
        return user
    return checker
