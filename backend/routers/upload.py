from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from fastapi.responses import FileResponse
import os, uuid
from config import UPLOAD_DIR
from auth import get_user_curent
from security import limiter, verifica_tip_fisier

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


@router.get("/cv/{nume_fisier}")
async def descarca_cv(nume_fisier: str, current_user=Depends(get_user_curent)):
    # Previne path traversal (../../etc/passwd)
    if ".." in nume_fisier or "/" in nume_fisier or "\\" in nume_fisier:
        raise HTTPException(status_code=400, detail="Nume fișier invalid.")

    cale = os.path.join(UPLOAD_DIR, nume_fisier)
    if not os.path.exists(cale):
        raise HTTPException(status_code=404, detail="Fișierul nu există.")

    return FileResponse(cale, filename=nume_fisier)
