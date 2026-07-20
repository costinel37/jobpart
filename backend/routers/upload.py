from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
import os, uuid
from config import UPLOAD_DIR
from database import get_db
from auth import get_user_curent
from security import limiter, verifica_tip_fisier
import models

router = APIRouter(prefix="/api/upload", tags=["Upload"])

EXTENSII_PERMISE = {".pdf", ".doc", ".docx"}
MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5MB


@router.post("/cv")
@limiter.limit("10/minute")
async def upload_cv(
    request: Request,
    fisier: UploadFile = File(...),
    current_user=Depends(get_user_curent)
):
    # Verifică extensia
    extensie = os.path.splitext(fisier.filename or "")[1].lower()
    if extensie not in EXTENSII_PERMISE:
        raise HTTPException(status_code=400, detail="Tip de fișier invalid. Acceptăm PDF, DOC, DOCX.")

    continut = await fisier.read()

    # Verifică dimensiunea
    if len(continut) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Fișierul depășește 5MB.")

    # Verifică magic bytes (conținut real, nu extensie falsificată)
    if not verifica_tip_fisier(continut):
        raise HTTPException(status_code=400, detail="Fișierul nu este un PDF sau Word valid.")

    # Salvează cu nume aleatoriu (nu păstrăm numele original pe disk)
    nume_salvat = f"{current_user.id}_{uuid.uuid4().hex}{extensie}"
    cale = os.path.join(UPLOAD_DIR, nume_salvat)

    with open(cale, "wb") as f:
        f.write(continut)

    return {"cv_path": nume_salvat, "cv_nume_original": fisier.filename}


@router.post("/cv-profil")
@limiter.limit("5/minute")
async def upload_cv_profil(
    request: Request,
    fisier: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    """Salvează CV-ul de profil al candidatului (refolosit la aplicări one-click)."""
    extensie = os.path.splitext(fisier.filename or "")[1].lower()
    if extensie not in EXTENSII_PERMISE:
        raise HTTPException(status_code=400, detail="Tip de fișier invalid. Acceptăm PDF, DOC, DOCX.")
    continut = await fisier.read()
    if len(continut) > MAX_SIZE_BYTES:
        raise HTTPException(status_code=400, detail="Fișierul depășește 5MB.")
    if not verifica_tip_fisier(continut):
        raise HTTPException(status_code=400, detail="Fișierul nu este un PDF sau Word valid.")

    # Șterge CV-ul vechi de pe disk
    if current_user.cv_profil_path:
        cale_veche = os.path.join(UPLOAD_DIR, current_user.cv_profil_path)
        if os.path.exists(cale_veche):
            os.remove(cale_veche)

    nume_salvat = f"{current_user.id}_profil_{uuid.uuid4().hex}{extensie}"
    cale = os.path.join(UPLOAD_DIR, nume_salvat)
    with open(cale, "wb") as f:
        f.write(continut)

    current_user.cv_profil_path = nume_salvat
    current_user.cv_profil_nume = fisier.filename
    db.commit()
    return {"cv_profil_path": nume_salvat, "cv_profil_nume": fisier.filename}


@router.get("/cv-profil/info")
def info_cv_profil(current_user=Depends(get_user_curent)):
    return {
        "cv_profil_path": current_user.cv_profil_path,
        "cv_profil_nume": current_user.cv_profil_nume,
    }


@router.get("/cv/{nume_fisier}")
@limiter.limit("60/minute")
async def descarca_cv(
    request: Request,
    nume_fisier: str,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    # Previne path traversal — verificare strictă că fișierul e în UPLOAD_DIR
    if ".." in nume_fisier or "/" in nume_fisier or "\\" in nume_fisier:
        raise HTTPException(status_code=400, detail="Nume fișier invalid.")

    cale = os.path.join(UPLOAD_DIR, nume_fisier)
    if os.path.abspath(cale) != os.path.join(os.path.abspath(UPLOAD_DIR), nume_fisier):
        raise HTTPException(status_code=400, detail="Nume fișier invalid.")

    if not os.path.exists(cale):
        raise HTTPException(status_code=404, detail="Fișierul nu există.")

    # Admin poate descărca orice CV
    if current_user.rol == "admin":
        return FileResponse(cale, filename=nume_fisier)

    # Candidatul care a uploadat CV-ul (filename începe cu {user_id}_)
    if nume_fisier.startswith(f"{current_user.id}_"):
        return FileResponse(cale, filename=nume_fisier)

    # Angajatorul care a primit o aplicare cu acest CV (doar dacă nu e respinsă)
    if current_user.rol == "angajator":
        from datetime import datetime, timedelta
        aplicare = (
            db.query(models.Application)
            .join(models.Job, models.Application.job_id == models.Job.id)
            .filter(
                models.Application.cv_path == nume_fisier,
                models.Job.angajator_id == current_user.id,
            )
            .first()
        )
        if aplicare:
            # Blochează accesul la CV-ul candidaților respinși (GDPR Art. 5(1)(b))
            if aplicare.status == "respinsa":
                limita = aplicare.creat_la + timedelta(days=30)
                if datetime.utcnow() > limita:
                    raise HTTPException(status_code=403, detail="Accesul la CV a expirat conform politicii GDPR (30 zile după respingere).")
            return FileResponse(cale, filename=nume_fisier)

    raise HTTPException(status_code=403, detail="Nu ai acces la acest fișier.")
