from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
from typing import Optional
from pydantic import BaseModel
import logging

from database import get_db
import models
from auth import require_rol, get_user_curent
from notificari_service import creeaza_notificare
from telegram_service import notifica_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/urgenta", tags=["Cautare Urgenta"])

PRET_RON = 50
OPTIUNI_ZILE = {1: 50, 3: 50}  # ambele variante = 50 RON


class CerereUrgentaBody(BaseModel):
    zile: int          # 1 sau 3
    oras: Optional[str] = None
    categorie: Optional[str] = None


class AprobaBody(BaseModel):
    mesaj: Optional[str] = None


@router.post("/cerere")
def trimite_cerere_urgenta(
    body: CerereUrgentaBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    if body.zile not in OPTIUNI_ZILE:
        raise HTTPException(status_code=400, detail="Alege 1 sau 3 zile.")

    # Verifica cerere activa deja
    activa = db.query(models.CautareUrgenta).filter(
        models.CautareUrgenta.candidat_id == current_user.id,
        models.CautareUrgenta.status == "aprobata",
        models.CautareUrgenta.activa_pana > datetime.utcnow(),
    ).first()
    if activa:
        raise HTTPException(status_code=400, detail="Ai deja o cautare urgenta activa.")

    in_asteptare = db.query(models.CautareUrgenta).filter(
        models.CautareUrgenta.candidat_id == current_user.id,
        models.CautareUrgenta.status == "in_asteptare",
    ).first()
    if in_asteptare:
        raise HTTPException(status_code=400, detail="Ai deja o cerere in asteptare. Asteapta confirmarea platii.")

    cerere = models.CautareUrgenta(
        candidat_id=current_user.id,
        zile=body.zile,
        pret=PRET_RON,
        oras=body.oras or current_user.oras,
        categorie=body.categorie,
        status="in_asteptare",
    )
    db.add(cerere)
    db.commit()
    db.refresh(cerere)

    # Notifica adminul pe Telegram
    notifica_admin(
        f"🚨 <b>Cerere urgenta noua!</b>\n\n"
        f"👤 Candidat: <b>{current_user.nume}</b>\n"
        f"📍 Oras: {cerere.oras or 'nespecificat'}\n"
        f"🏷 Categorie: {cerere.categorie or 'toate'}\n"
        f"⏱ Durata: {body.zile} {'zi' if body.zile == 1 else 'zile'} — {PRET_RON} RON\n\n"
        f"Aproba din panoul de admin dupa confirmarea platii."
    )

    return {
        "id": cerere.id,
        "status": cerere.status,
        "pret": cerere.pret,
        "zile": cerere.zile,
        "mesaj": f"Cererea a fost trimisa! Trimite {PRET_RON} RON prin transfer bancar si vei fi activat in maxim 24h.",
        "detalii_plata": {
            "titular": "JobPart",
            "iban": "RO49AAAA1B31007593840000",
            "suma": f"{PRET_RON} RON",
            "referinta": f"URGENT-{cerere.id}-{current_user.id}",
        }
    }


@router.get("/cereri-mele")
def cereri_mele(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    cereri = db.query(models.CautareUrgenta).filter(
        models.CautareUrgenta.candidat_id == current_user.id
    ).order_by(models.CautareUrgenta.creat_la.desc()).all()

    return [
        {
            "id": c.id,
            "zile": c.zile,
            "pret": c.pret,
            "oras": c.oras,
            "categorie": c.categorie,
            "status": c.status,
            "activa_pana": c.activa_pana.isoformat() if c.activa_pana else None,
            "mesaj_admin": c.mesaj_admin,
            "notificari_trimise": c.notificari_trimise,
            "creat_la": c.creat_la.isoformat(),
        }
        for c in cereri
    ]


@router.get("/cereri")
def toate_cererile(
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    cereri = db.query(models.CautareUrgenta).order_by(
        models.CautareUrgenta.creat_la.desc()
    ).all()

    return [
        {
            "id": c.id,
            "candidat_id": c.candidat_id,
            "candidat_nume": c.candidat.nume if c.candidat else None,
            "candidat_email": c.candidat.email if c.candidat else None,
            "zile": c.zile,
            "pret": c.pret,
            "oras": c.oras,
            "categorie": c.categorie,
            "status": c.status,
            "activa_pana": c.activa_pana.isoformat() if c.activa_pana else None,
            "mesaj_admin": c.mesaj_admin,
            "notificari_trimise": c.notificari_trimise,
            "creat_la": c.creat_la.isoformat(),
            "procesata_la": c.procesata_la.isoformat() if c.procesata_la else None,
        }
        for c in cereri
    ]


@router.put("/cereri/{cerere_id}/aproba")
def aproba_cerere_urgenta(
    cerere_id: int,
    body: AprobaBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    cerere = db.query(models.CautareUrgenta).filter(
        models.CautareUrgenta.id == cerere_id
    ).first()
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu exista.")
    if cerere.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesata.")

    # Activeaza cautarea urgenta pe candidat
    candidat = db.query(models.User).filter(models.User.id == cerere.candidat_id).first()
    if not candidat:
        raise HTTPException(status_code=404, detail="Candidatul nu mai exista.")

    activa_pana = datetime.utcnow() + timedelta(days=cerere.zile)
    candidat.cautare_urgenta = True
    candidat.cautare_urgenta_pana = activa_pana

    cerere.status = "aprobata"
    cerere.activa_pana = activa_pana
    cerere.procesata_la = datetime.utcnow()
    if body.mesaj:
        cerere.mesaj_admin = body.mesaj

    # Notifica candidatul in-app
    creeaza_notificare(
        db, candidat.id,
        tip="urgenta_aprobata",
        mesaj=f"Cautarea ta urgenta a fost activata! Angajatorii relevanti vor fi notificati. Activa pana pe {activa_pana.strftime('%d.%m.%Y')}.",
        link="/static/dashboard-candidat.html",
    )

    # Trimite notificari in-app la angajatori cu joburi active potrivite
    query_angajatori = db.query(models.User).filter(
        models.User.rol == "angajator",
        models.User.activ == True,
    )
    angajatori = query_angajatori.all()

    notificari_trimise = 0
    for angajator in angajatori:
        # Verifica daca angajatorul are joburi active in orasul/categoria candidatului
        q_job = db.query(models.Job).filter(
            models.Job.angajator_id == angajator.id,
            models.Job.activ == True,
        )
        if cerere.oras:
            q_job = q_job.filter(models.Job.oras.ilike(f"%{cerere.oras}%"))
        if cerere.categorie:
            q_job = q_job.filter(models.Job.categorie == cerere.categorie)

        if q_job.first():
            creeaza_notificare(
                db, angajator.id,
                tip="candidat_urgent",
                mesaj=f"🚨 Candidat nou cauta job urgent! {candidat.nume} cauta activ in {cerere.oras or 'Romania'}{(' — ' + cerere.categorie) if cerere.categorie else ''}. Vezi profilul sau!",
                link=f"/static/profil-public.html?id={candidat.id}" if hasattr(candidat, 'id') else "/static/jobs.html",
            )
            notificari_trimise += 1

    cerere.notificari_trimise = notificari_trimise
    db.commit()

    # Notificare Telegram canal
    from telegram_service import _trimite_mesaj
    _trimite_mesaj(
        f"🚨 <b>Candidat cauta job urgent!</b>\n\n"
        f"👤 <b>{candidat.nume}</b>\n"
        f"📍 {cerere.oras or 'Romania'}\n"
        f"🏷 {cerere.categorie or 'Orice domeniu'}\n"
        f"⏱ Disponibil {cerere.zile} {'zi' if cerere.zile == 1 else 'zile'}\n\n"
        f"#cautareurgenta #jobparttime"
    )

    return {
        "mesaj": f"Cererea aprobata. {notificari_trimise} angajatori notificati in-app. Anunt publicat pe Telegram.",
        "notificari_trimise": notificari_trimise,
    }


@router.put("/cereri/{cerere_id}/respinge")
def respinge_cerere_urgenta(
    cerere_id: int,
    body: AprobaBody,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("admin"))
):
    cerere = db.query(models.CautareUrgenta).filter(
        models.CautareUrgenta.id == cerere_id
    ).first()
    if not cerere:
        raise HTTPException(status_code=404, detail="Cererea nu exista.")
    if cerere.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Cererea a fost deja procesata.")

    cerere.status = "respinsa"
    cerere.procesata_la = datetime.utcnow()
    cerere.mesaj_admin = body.mesaj

    creeaza_notificare(
        db, cerere.candidat_id,
        tip="urgenta_respinsa",
        mesaj=f"Cererea de cautare urgenta a fost respinsa.{' Motiv: ' + body.mesaj if body.mesaj else ' Contacteaza-ne pentru detalii.'}",
        link="/static/dashboard-candidat.html",
    )
    db.commit()
    return {"mesaj": "Cererea a fost respinsa."}
