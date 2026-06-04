from pydantic import BaseModel, EmailStr, field_validator
from typing import Optional
from datetime import datetime, date
import re

_TAG_RE = re.compile(r'<[^>]+>')

def _strip(v: Optional[str]) -> Optional[str]:
    if v is None:
        return v
    return _TAG_RE.sub('', v).strip() or None


# --- Auth ---
class UserRegister(BaseModel):
    nume: str
    email: EmailStr
    parola: str
    rol: str = "candidat"
    telefon: Optional[str] = None
    oras: Optional[str] = None
    gdpr_consimtit: bool = False
    newsletter_consimtit: bool = False
    data_nasterii: Optional[date] = None

    @field_validator('gdpr_consimtit')
    @classmethod
    def valideaza_gdpr(cls, v: bool) -> bool:
        if not v:
            raise ValueError('Trebuie să accepți Politica de Confidențialitate pentru a te înregistra.')
        return v

    @field_validator('data_nasterii')
    @classmethod
    def valideaza_varsta(cls, v: Optional[date]) -> Optional[date]:
        if v is None:
            raise ValueError('Data nașterii este obligatorie.')
        from datetime import date as date_type
        varsta = (date_type.today() - v).days // 365
        if varsta < 16:
            raise ValueError('Trebuie să ai cel puțin 16 ani pentru a te înregistra.')
        return v

class UserLogin(BaseModel):
    email: EmailStr
    parola: str

class Token(BaseModel):
    access_token: str
    token_type: str
    rol: str
    nume: str
    user_id: int

class UserOut(BaseModel):
    id: int
    nume: str
    email: str
    rol: str
    telefon: Optional[str]
    oras: Optional[str]
    despre: Optional[str]
    activ: bool
    email_confirmat: bool = False
    creat_la: datetime

    class Config:
        from_attributes = True

class PublicUserOut(BaseModel):
    id: int
    nume: str
    rol: str
    despre: Optional[str]
    membru_din: Optional[str] = None

    class Config:
        from_attributes = True

class UserUpdate(BaseModel):
    nume: Optional[str] = None
    telefon: Optional[str] = None
    oras: Optional[str] = None
    despre: Optional[str] = None

    @field_validator('nume', 'telefon', 'oras', 'despre', mode='before')
    @classmethod
    def sanitizeaza_profil(cls, v):
        return _strip(v)


# --- Jobs ---
class JobCreate(BaseModel):
    titlu: str
    descriere: str
    cerinte: Optional[str] = None
    beneficii: Optional[str] = None
    companie: str
    oras: str
    tip_program: str = "part-time"
    salariu_min: Optional[int] = None
    salariu_max: Optional[int] = None
    categorie: Optional[str] = None

    @field_validator('titlu', 'descriere', 'cerinte', 'beneficii', 'companie', 'oras', 'categorie', mode='before')
    @classmethod
    def sanitizeaza_job(cls, v):
        return _strip(v)

class JobOut(BaseModel):
    id: int
    titlu: str
    descriere: str
    cerinte: Optional[str]
    beneficii: Optional[str]
    companie: str
    oras: str
    tip_program: str
    salariu_min: Optional[int]
    salariu_max: Optional[int]
    categorie: Optional[str]
    lat: Optional[float]
    lng: Optional[float]
    activ: bool
    expira_la: Optional[datetime]
    promovat: bool
    promovat_pana: Optional[datetime]
    creat_la: datetime
    angajator_id: int

    class Config:
        from_attributes = True


# --- Applications ---
class ApplicationCreate(BaseModel):
    job_id: int
    scrisoare: Optional[str] = None
    cv_path: Optional[str] = None
    cv_nume_original: Optional[str] = None

    @field_validator('scrisoare', mode='before')
    @classmethod
    def sanitizeaza_scrisoare(cls, v):
        return _strip(v)

class ApplicationOut(BaseModel):
    id: int
    scrisoare: Optional[str]
    cv_path: Optional[str]
    cv_nume_original: Optional[str]
    status: str
    creat_la: datetime
    candidat_id: int
    candidat_nume: str = ""
    job_id: int
    job: Optional[JobOut] = None

    class Config:
        from_attributes = True

class ApplicationStatusUpdate(BaseModel):
    status: str
    motiv_respingere: Optional[str] = None


# --- Reviews ---
class ReviewCreate(BaseModel):
    subiect_id: int
    rating: int
    comentariu: Optional[str] = None

    @field_validator('comentariu', mode='before')
    @classmethod
    def sanitizeaza_comentariu(cls, v):
        return _strip(v)

    @field_validator('rating')
    @classmethod
    def valideaza_rating(cls, v: int) -> int:
        if not 1 <= v <= 5:
            raise ValueError('Rating-ul trebuie să fie între 1 și 5.')
        return v

class ReviewOut(BaseModel):
    id: int
    autor_id: int
    autor_nume: str = ""
    subiect_id: int
    rating: int
    comentariu: Optional[str]
    creat_la: datetime

    class Config:
        from_attributes = True

class RatingMedie(BaseModel):
    medie: float
    total: int
