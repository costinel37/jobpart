from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from datetime import datetime
from pydantic import BaseModel
from typing import Optional
from io import BytesIO
from database import get_db
import models
from auth import get_user_curent, require_rol
from notificari_service import creeaza_notificare

router = APIRouter(prefix="/api/precontracte", tags=["Precontracte"])

DISCLAIMER = (
    "ATENȚIE: Acest document reprezintă o înțelegere informală între părți și NU constituie "
    "un contract individual de muncă (CIM) în sensul Codului Muncii. Angajarea legală necesită "
    "încheierea unui CIM înregistrat la ITM. JobPart nu este parte în acest acord și nu își "
    "asumă nicio responsabilitate juridică."
)


class CererePrecontract(BaseModel):
    aplicare_id: int
    program: str
    salariu: str
    data_inceput: str
    durata: str
    descriere_scurta: Optional[str] = None


@router.post("")
def creeaza_precontract(
    body: CererePrecontract,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("angajator"))
):
    aplicare = db.query(models.Application).filter(
        models.Application.id == body.aplicare_id
    ).first()
    if not aplicare:
        raise HTTPException(status_code=404, detail="Aplicarea nu există.")
    if aplicare.job.angajator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nu ai acces la această aplicare.")
    if aplicare.status != "acceptata":
        raise HTTPException(status_code=400, detail="Poți genera precontract doar pentru aplicări acceptate.")

    existent = db.query(models.Precontract).filter(
        models.Precontract.aplicare_id == body.aplicare_id,
        models.Precontract.status != "refuzat",
    ).first()
    if existent:
        raise HTTPException(status_code=400, detail="Există deja un precontract pentru această aplicare.")

    precontract = models.Precontract(
        aplicare_id=body.aplicare_id,
        job_id=aplicare.job_id,
        angajator_id=current_user.id,
        candidat_id=aplicare.candidat_id,
        titlu_job=aplicare.job.titlu,
        companie=aplicare.job.companie,
        oras=aplicare.job.oras,
        program=body.program,
        salariu=body.salariu,
        data_inceput=body.data_inceput,
        durata=body.durata,
        descriere_scurta=body.descriere_scurta,
        disclaimer=DISCLAIMER,
        semnat_angajator=True,
        semnat_angajator_la=datetime.utcnow(),
        status="in_asteptare",
    )
    db.add(precontract)
    db.commit()
    db.refresh(precontract)

    creeaza_notificare(
        db, aplicare.candidat_id,
        tip="precontract_nou",
        mesaj=f"{current_user.nume} de la {aplicare.job.companie} ți-a trimis un precontract pentru '{aplicare.job.titlu}'. Verifică și semnează.",
        link=f"/static/precontract.html?id={precontract.id}",
    )

    return {"id": precontract.id, "mesaj": "Precontractul a fost trimis candidatului pentru semnare."}


@router.get("/ale-mele")
def precontractele_mele(
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    if current_user.rol == "angajator":
        lista = db.query(models.Precontract).filter(
            models.Precontract.angajator_id == current_user.id
        ).order_by(models.Precontract.creat_la.desc()).all()
    else:
        lista = db.query(models.Precontract).filter(
            models.Precontract.candidat_id == current_user.id
        ).order_by(models.Precontract.creat_la.desc()).all()

    return [_serializeaza(p) for p in lista]


@router.get("/{precontract_id}")
def get_precontract(
    precontract_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    p = _get_sau_404(precontract_id, db)
    _verifica_acces(p, current_user)
    return _serializeaza(p)


@router.post("/{precontract_id}/semneaza")
def semneaza(
    precontract_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    p = _get_sau_404(precontract_id, db)
    if p.candidat_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nu ai acces la acest precontract.")
    if p.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Precontractul a fost deja procesat.")

    p.semnat_candidat = True
    p.semnat_candidat_la = datetime.utcnow()
    p.status = "semnat"
    db.commit()

    creeaza_notificare(
        db, p.angajator_id,
        tip="precontract_semnat",
        mesaj=f"{current_user.nume} a semnat precontractul pentru '{p.titlu_job}'. Puteți descărca documentul.",
        link=f"/static/precontract.html?id={p.id}",
    )

    return {"mesaj": "Ai semnat precontractul cu succes! Angajatorul a fost notificat."}


@router.post("/{precontract_id}/refuza")
def refuza(
    precontract_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(require_rol("candidat"))
):
    p = _get_sau_404(precontract_id, db)
    if p.candidat_id != current_user.id:
        raise HTTPException(status_code=403, detail="Nu ai acces la acest precontract.")
    if p.status != "in_asteptare":
        raise HTTPException(status_code=400, detail="Precontractul a fost deja procesat.")

    p.status = "refuzat"
    db.commit()

    creeaza_notificare(
        db, p.angajator_id,
        tip="precontract_refuzat",
        mesaj=f"{current_user.nume} a refuzat precontractul pentru '{p.titlu_job}'.",
        link="/static/dashboard-angajator.html",
    )

    return {"mesaj": "Ai refuzat precontractul."}


@router.get("/{precontract_id}/pdf")
def descarca_pdf(
    precontract_id: int,
    db: Session = Depends(get_db),
    current_user=Depends(get_user_curent)
):
    p = _get_sau_404(precontract_id, db)
    _verifica_acces(p, current_user)
    if p.status != "semnat":
        raise HTTPException(status_code=400, detail="PDF-ul este disponibil doar după ce ambele părți au semnat.")

    pdf_bytes = _genereaza_pdf(p)
    return StreamingResponse(
        BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=precontract_{p.id}.pdf"}
    )


def _get_sau_404(precontract_id: int, db: Session) -> models.Precontract:
    p = db.query(models.Precontract).filter(models.Precontract.id == precontract_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Precontractul nu există.")
    return p


def _verifica_acces(p: models.Precontract, current_user):
    if current_user.id not in (p.angajator_id, p.candidat_id) and current_user.rol != "admin":
        raise HTTPException(status_code=403, detail="Nu ai acces la acest precontract.")


def _serializeaza(p: models.Precontract) -> dict:
    return {
        "id": p.id,
        "aplicare_id": p.aplicare_id,
        "job_id": p.job_id,
        "titlu_job": p.titlu_job,
        "companie": p.companie,
        "oras": p.oras,
        "program": p.program,
        "salariu": p.salariu,
        "data_inceput": p.data_inceput,
        "durata": p.durata,
        "descriere_scurta": p.descriere_scurta,
        "disclaimer": p.disclaimer,
        "angajator_id": p.angajator_id,
        "angajator_nume": p.angajator.nume if p.angajator else None,
        "candidat_id": p.candidat_id,
        "candidat_nume": p.candidat.nume if p.candidat else None,
        "semnat_angajator": p.semnat_angajator,
        "semnat_angajator_la": p.semnat_angajator_la.isoformat() if p.semnat_angajator_la else None,
        "semnat_candidat": p.semnat_candidat,
        "semnat_candidat_la": p.semnat_candidat_la.isoformat() if p.semnat_candidat_la else None,
        "status": p.status,
        "creat_la": p.creat_la.isoformat(),
    }


def _genereaza_pdf(p: models.Precontract) -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm
    from reportlab.lib import colors
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable
    from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    import os

    FONT_DIR = "/usr/share/fonts/truetype/dejavu"
    FONT_NORMAL = os.path.join(FONT_DIR, "DejaVuSans.ttf")
    FONT_BOLD = os.path.join(FONT_DIR, "DejaVuSans-Bold.ttf")
    if os.path.exists(FONT_NORMAL) and os.path.exists(FONT_BOLD):
        pdfmetrics.registerFont(TTFont("DejaVu", FONT_NORMAL))
        pdfmetrics.registerFont(TTFont("DejaVu-Bold", FONT_BOLD))
        BASE_FONT = "DejaVu"
        BOLD_FONT = "DejaVu-Bold"
    else:
        BASE_FONT = "Helvetica"
        BOLD_FONT = "Helvetica-Bold"

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=2.5*cm, rightMargin=2.5*cm,
                            topMargin=2.5*cm, bottomMargin=2.5*cm)

    styles = getSampleStyleSheet()
    titlu_style = ParagraphStyle("Titlu", parent=styles["Title"], fontName=BOLD_FONT, fontSize=18, spaceAfter=6, alignment=TA_CENTER)
    subtitlu_style = ParagraphStyle("Subtitlu", parent=styles["Normal"], fontName=BASE_FONT, fontSize=10, textColor=colors.grey, alignment=TA_CENTER, spaceAfter=20)
    sectiune_style = ParagraphStyle("Sectiune", parent=styles["Heading2"], fontName=BOLD_FONT, fontSize=12, textColor=colors.HexColor("#2563eb"), spaceBefore=16, spaceAfter=6)
    normal_style = ParagraphStyle("Normal2", parent=styles["Normal"], fontName=BASE_FONT, fontSize=10, leading=16)
    disclaimer_style = ParagraphStyle("Disc", parent=styles["Normal"], fontName=BASE_FONT, fontSize=8, textColor=colors.grey,
                                      backColor=colors.HexColor("#f8fafc"), borderPad=8, leading=13, alignment=TA_JUSTIFY)
    semn_style = ParagraphStyle("Semn", parent=styles["Normal"], fontName=BASE_FONT, fontSize=10, leading=18)

    def data_fmt(dt):
        if not dt:
            return "—"
        return dt.strftime("%d.%m.%Y %H:%M")

    elemente = []

    elemente.append(Paragraph("PRECONTRACT DE COLABORARE", titlu_style))
    elemente.append(Paragraph("Înțelegere informală — JobPart", subtitlu_style))
    elemente.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
    elemente.append(Spacer(1, 0.4*cm))

    elemente.append(Paragraph("1. PĂRȚILE", sectiune_style))
    date_parti = [
        ["Angajator:", p.angajator.nume if p.angajator else "—", "Candidat:", p.candidat.nume if p.candidat else "—"],
        ["Companie:", p.companie, "Email:", p.candidat.email if p.candidat else "—"],
    ]
    tabel_parti = Table(date_parti, colWidths=[3*cm, 7*cm, 3*cm, 7*cm])
    tabel_parti.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("FONTNAME", (0,0), (-1,-1), BASE_FONT),
        ("FONTNAME", (0,0), (0,-1), BOLD_FONT),
        ("FONTNAME", (2,0), (2,-1), BOLD_FONT),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
    ]))
    elemente.append(tabel_parti)

    elemente.append(Paragraph("2. DETALII JOB", sectiune_style))
    date_job = [
        ["Poziție:", p.titlu_job],
        ["Companie / Locație:", f"{p.companie} — {p.oras}"],
        ["Program de lucru:", p.program],
        ["Remunerație:", p.salariu],
        ["Data estimată de început:", p.data_inceput],
        ["Durată estimată:", p.durata],
    ]
    tabel_job = Table(date_job, colWidths=[5*cm, 12*cm])
    tabel_job.setStyle(TableStyle([
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("FONTNAME", (0,0), (-1,-1), BASE_FONT),
        ("FONTNAME", (0,0), (0,-1), BOLD_FONT),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("ROWBACKGROUNDS", (0,0), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    elemente.append(tabel_job)

    if p.descriere_scurta:
        elemente.append(Paragraph("3. NOTE SUPLIMENTARE", sectiune_style))
        elemente.append(Paragraph(p.descriere_scurta, normal_style))

    elemente.append(Paragraph("4. AVERTISMENT LEGAL", sectiune_style))
    elemente.append(Paragraph(DISCLAIMER, disclaimer_style))

    elemente.append(Paragraph("5. SEMNĂTURI", sectiune_style))
    elemente.append(Spacer(1, 0.3*cm))

    data_semn_ang = data_fmt(p.semnat_angajator_la)
    data_semn_cand = data_fmt(p.semnat_candidat_la)

    tabel_semn = Table([
        [
            Paragraph(f"<b>ANGAJATOR</b><br/>{p.angajator.nume if p.angajator else '—'}<br/>{p.companie}", semn_style),
            Paragraph(f"<b>CANDIDAT</b><br/>{p.candidat.nume if p.candidat else '—'}", semn_style),
        ],
        [
            Paragraph(f"✓ Semnat electronic<br/>Data: {data_semn_ang}", semn_style),
            Paragraph(f"{'✓ Semnat electronic' if p.semnat_candidat else '⏳ În așteptare'}<br/>Data: {data_semn_cand}", semn_style),
        ]
    ], colWidths=[9*cm, 9*cm])
    tabel_semn.setStyle(TableStyle([
        ("BOX", (0,0), (0,-1), 1, colors.HexColor("#2563eb")),
        ("BOX", (1,0), (1,-1), 1, colors.HexColor("#2563eb")),
        ("BACKGROUND", (0,0), (0,0), colors.HexColor("#eff6ff")),
        ("BACKGROUND", (1,0), (1,0), colors.HexColor("#eff6ff")),
        ("PADDING", (0,0), (-1,-1), 10),
        ("FONTSIZE", (0,0), (-1,-1), 10),
        ("FONTNAME", (0,0), (-1,-1), BASE_FONT),
        ("LEFTPADDING", (0,0), (-1,-1), 14),
    ]))
    elemente.append(tabel_semn)

    elemente.append(Spacer(1, 0.5*cm))
    elemente.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    elemente.append(Paragraph(
        f"Document generat pe platforma JobPart · ID #{p.id} · {datetime.utcnow().strftime('%d.%m.%Y')}",
        ParagraphStyle("Footer", parent=styles["Normal"], fontName=BASE_FONT, fontSize=8, textColor=colors.grey, alignment=TA_CENTER, spaceBefore=8)
    ))

    doc.build(elemente)
    return buffer.getvalue()
