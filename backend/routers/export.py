from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from io import BytesIO
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, HRFlowable, Table, TableStyle
from database import get_db
import models
from auth import get_user_curent

router = APIRouter(prefix="/api/export", tags=["Export"])


@router.get("/date-personale")
def export_date_personale(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    """Export complet al datelor personale în format JSON (GDPR Art. 20 — dreptul la portabilitate)."""
    user = current_user

    aplicari = db.query(models.Application).filter(
        models.Application.candidat_id == user.id
    ).all()

    mesaje_trimise = db.query(models.Message).filter(
        models.Message.expeditor_id == user.id
    ).order_by(models.Message.creat_la.desc()).all()

    mesaje_primite = db.query(models.Message).filter(
        models.Message.destinatar_id == user.id
    ).order_by(models.Message.creat_la.desc()).all()

    favorite = db.query(models.Favorite).filter(
        models.Favorite.user_id == user.id
    ).all()

    recenzii_date = db.query(models.Review).filter(
        models.Review.autor_id == user.id
    ).all()

    recenzii_primite = db.query(models.Review).filter(
        models.Review.subiect_id == user.id
    ).all()

    def dt(v):
        return v.isoformat() if v else None

    data = {
        "export_gdpr": {
            "data_export": __import__("datetime").datetime.utcnow().isoformat(),
            "nota": "Export date personale conform GDPR Art. 20 — JobPart"
        },
        "profil": {
            "id": user.id,
            "nume": user.nume,
            "email": user.email,
            "rol": user.rol,
            "telefon": user.telefon,
            "oras": user.oras,
            "despre": user.despre,
            "creat_la": dt(user.creat_la),
            "email_confirmat": user.email_confirmat,
            "gdpr_consimtit_la": dt(user.gdpr_consimtit_la),
        },
        "aplicari": [
            {
                "id": a.id,
                "job_id": a.job_id,
                "job_titlu": a.job.titlu if a.job else None,
                "job_companie": a.job.companie if a.job else None,
                "status": a.status,
                "scrisoare": a.scrisoare,
                "cv_nume_original": a.cv_nume_original,
                "creat_la": dt(a.creat_la),
            }
            for a in aplicari
        ],
        "mesaje_trimise": [
            {
                "id": m.id,
                "destinatar_id": m.destinatar_id,
                "subiect": m.subiect,
                "continut": m.continut,
                "creat_la": dt(m.creat_la),
            }
            for m in mesaje_trimise
        ],
        "mesaje_primite": [
            {
                "id": m.id,
                "expeditor_id": m.expeditor_id,
                "subiect": m.subiect,
                "continut": m.continut,
                "citit": m.citit,
                "creat_la": dt(m.creat_la),
            }
            for m in mesaje_primite
        ],
        "favorite_joburi": [
            {"job_id": f.job_id, "creat_la": dt(f.creat_la)}
            for f in favorite
        ],
        "recenzii_date": [
            {
                "id": r.id,
                "subiect_id": r.subiect_id,
                "rating": r.rating,
                "comentariu": r.comentariu,
                "creat_la": dt(r.creat_la),
            }
            for r in recenzii_date
        ],
        "recenzii_primite": [
            {
                "id": r.id,
                "autor_id": r.autor_id,
                "rating": r.rating,
                "comentariu": r.comentariu,
                "creat_la": dt(r.creat_la),
            }
            for r in recenzii_primite
        ],
    }

    import json
    continut = json.dumps(data, ensure_ascii=False, indent=2)
    return StreamingResponse(
        iter([continut]),
        media_type="application/json",
        headers={"Content-Disposition": f"attachment; filename=date_personale_jobpart_{user.id}.json"}
    )


@router.get("/cv-pdf")
def export_cv_pdf(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    import json as _json
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    cv = db.query(models.CandidatCV).filter(models.CandidatCV.user_id == current_user.id).first()
    rating = db.query(func.avg(models.Review.rating), func.count(models.Review.id)).filter(
        models.Review.subiect_id == current_user.id
    ).first()

    def jp(text, default):
        if not text:
            return default
        try:
            return _json.loads(text)
        except Exception:
            return default

    experienta = jp(cv.experienta if cv else None, [])
    educatie = jp(cv.educatie if cv else None, [])
    competente = jp(cv.competente if cv else None, [])
    limbi = jp(cv.limbi if cv else None, [])

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    VIOLET = colors.HexColor("#7c3aed")
    GRI = colors.HexColor("#6b7280")
    GRI_DESCHIS = colors.HexColor("#f5f3ff")

    stil_titlu = ParagraphStyle("titlu", parent=styles["Title"], textColor=VIOLET,
                                 fontSize=24, spaceAfter=2)
    stil_subtitlu = ParagraphStyle("subtitlu", parent=styles["Normal"], textColor=VIOLET,
                                    fontSize=13, spaceAfter=2, fontName="Helvetica-Oblique")
    stil_sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=GRI,
                               fontSize=10, spaceAfter=2)
    stil_sectiune = ParagraphStyle("sectiune", parent=styles["Heading2"],
                                    textColor=VIOLET, fontSize=12, spaceBefore=14, spaceAfter=4,
                                    fontName="Helvetica-Bold")
    stil_normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, spaceAfter=3)
    stil_bold = ParagraphStyle("bold", parent=styles["Normal"], fontSize=10,
                                fontName="Helvetica-Bold", spaceAfter=1)
    stil_italic = ParagraphStyle("italic", parent=styles["Normal"], fontSize=9,
                                  fontName="Helvetica-Oblique", textColor=GRI, spaceAfter=3)

    elemente = []

    # Header
    elemente.append(Paragraph(user.nume, stil_titlu))
    if cv and cv.titlu_profesional:
        elemente.append(Paragraph(cv.titlu_profesional, stil_subtitlu))

    info_rand = []
    if user.email: info_rand.append(f"{user.email}")
    if user.telefon: info_rand.append(f"{user.telefon}")
    if user.oras: info_rand.append(f"{user.oras}")
    elemente.append(Paragraph("  |  ".join(info_rand), stil_sub))
    elemente.append(Spacer(1, 6))
    elemente.append(HRFlowable(width="100%", thickness=2, color=VIOLET))
    elemente.append(Spacer(1, 6))

    # Disponibilitate + permis
    if cv:
        badges = []
        if cv.disponibilitate:
            badges.append(f"Disponibil: {cv.disponibilitate}")
        if cv.permis_auto:
            badges.append("Permis auto: DA")
        if badges:
            elemente.append(Paragraph("  •  ".join(badges), stil_sub))
            elemente.append(Spacer(1, 4))

    # Rating
    if rating and rating[1] > 0:
        medie = round(float(rating[0]), 1)
        stele = "★" * int(medie) + "☆" * (5 - int(medie))
        elemente.append(Paragraph(f"Rating JobPart: {stele}  {medie}/5 ({rating[1]} recenzii)", stil_sub))
        elemente.append(Spacer(1, 4))

    # Despre
    if user.despre:
        elemente.append(Paragraph("Despre mine", stil_sectiune))
        elemente.append(HRFlowable(width="100%", thickness=0.5, color=VIOLET))
        elemente.append(Spacer(1, 4))
        elemente.append(Paragraph(user.despre, stil_normal))

    # Experiență
    if experienta:
        elemente.append(Paragraph("Experiență profesională", stil_sectiune))
        elemente.append(HRFlowable(width="100%", thickness=0.5, color=VIOLET))
        for exp in experienta:
            elemente.append(Spacer(1, 5))
            pozitie = exp.get("pozitie", "")
            companie = exp.get("companie", "")
            perioada = exp.get("perioada", "")
            descriere = exp.get("descriere", "")
            if pozitie:
                elemente.append(Paragraph(f"{pozitie} — {companie}", stil_bold))
            elif companie:
                elemente.append(Paragraph(companie, stil_bold))
            if perioada:
                elemente.append(Paragraph(perioada, stil_italic))
            if descriere:
                elemente.append(Paragraph(descriere, stil_normal))

    # Educație
    if educatie:
        elemente.append(Paragraph("Educație", stil_sectiune))
        elemente.append(HRFlowable(width="100%", thickness=0.5, color=VIOLET))
        for edu in educatie:
            elemente.append(Spacer(1, 5))
            institutie = edu.get("institutie", "")
            nivel = edu.get("nivel", "")
            domeniu = edu.get("domeniu", "")
            an = edu.get("an", "")
            linie1 = " — ".join(filter(None, [nivel, domeniu]))
            if linie1:
                elemente.append(Paragraph(linie1, stil_bold))
            if institutie:
                elemente.append(Paragraph(institutie, stil_normal))
            if an:
                elemente.append(Paragraph(str(an), stil_italic))

    # Competențe
    if competente:
        elemente.append(Paragraph("Competențe", stil_sectiune))
        elemente.append(HRFlowable(width="100%", thickness=0.5, color=VIOLET))
        elemente.append(Spacer(1, 4))
        elemente.append(Paragraph("  •  ".join(str(c) for c in competente), stil_normal))

    # Limbi
    if limbi:
        elemente.append(Paragraph("Limbi străine", stil_sectiune))
        elemente.append(HRFlowable(width="100%", thickness=0.5, color=VIOLET))
        elemente.append(Spacer(1, 4))
        randuri_limbi = []
        for l in limbi:
            limba = l.get("limba", "")
            nivel = l.get("nivel", "")
            if limba:
                randuri_limbi.append(f"{limba}: {nivel}" if nivel else limba)
        elemente.append(Paragraph("  •  ".join(randuri_limbi), stil_normal))

    # Footer
    elemente.append(Spacer(1, 20))
    elemente.append(HRFlowable(width="100%", thickness=1, color=GRI))
    from datetime import datetime as _dt
    elemente.append(Paragraph(
        f"CV generat de JobPart.ro  •  {_dt.now().strftime('%d.%m.%Y')}",
        ParagraphStyle("footer", parent=styles["Normal"], textColor=GRI, fontSize=8, alignment=1)
    ))

    doc.build(elemente)
    buf.seek(0)

    nume_fisier = f"CV_{user.nume.replace(' ', '_')}_JobPart.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={nume_fisier}"})
