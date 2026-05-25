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


@router.get("/cv-pdf")
def export_cv_pdf(db: Session = Depends(get_db), current_user=Depends(get_user_curent)):
    user = db.query(models.User).filter(models.User.id == current_user.id).first()
    aplicari = db.query(models.Application).filter(
        models.Application.candidat_id == current_user.id
    ).order_by(models.Application.creat_la.desc()).all()
    rating = db.query(func.avg(models.Review.rating), func.count(models.Review.id)).filter(
        models.Review.subiect_id == current_user.id
    ).first()

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)

    styles = getSampleStyleSheet()
    ALBASTRU = colors.HexColor("#2563eb")
    GRI = colors.HexColor("#6b7280")

    stil_titlu = ParagraphStyle("titlu", parent=styles["Title"], textColor=ALBASTRU,
                                 fontSize=26, spaceAfter=4)
    stil_sub = ParagraphStyle("sub", parent=styles["Normal"], textColor=GRI,
                               fontSize=11, spaceAfter=2)
    stil_sectiune = ParagraphStyle("sectiune", parent=styles["Heading2"],
                                    textColor=ALBASTRU, fontSize=13, spaceBefore=14, spaceAfter=6)
    stil_normal = ParagraphStyle("normal", parent=styles["Normal"], fontSize=10, spaceAfter=4)
    stil_bold = ParagraphStyle("bold", parent=styles["Normal"], fontSize=10,
                                fontName="Helvetica-Bold", spaceAfter=2)

    elemente = []

    # Header
    elemente.append(Paragraph(user.nume, stil_titlu))
    if user.rol == "candidat":
        elemente.append(Paragraph("Candidat — Profil JobPart", stil_sub))
    else:
        elemente.append(Paragraph(f"Angajator — {user.oras or ''}", stil_sub))

    info_rand = []
    if user.email: info_rand.append(f"✉ {user.email}")
    if user.telefon: info_rand.append(f"☎ {user.telefon}")
    if user.oras: info_rand.append(f"📍 {user.oras}")
    elemente.append(Paragraph("   |   ".join(info_rand), stil_sub))
    elemente.append(Spacer(1, 8))
    elemente.append(HRFlowable(width="100%", thickness=2, color=ALBASTRU))
    elemente.append(Spacer(1, 8))

    # Rating
    if rating and rating[1] > 0:
        medie = round(float(rating[0]), 1)
        stele = "★" * int(medie) + "☆" * (5 - int(medie))
        elemente.append(Paragraph("Rating JobPart", stil_sectiune))
        elemente.append(Paragraph(f"{stele}  {medie}/5 ({rating[1]} recenzii)", stil_normal))

    # Despre
    if user.despre:
        elemente.append(Paragraph("Despre mine", stil_sectiune))
        elemente.append(Paragraph(user.despre, stil_normal))

    # Activitate
    if aplicari:
        elemente.append(Paragraph("Activitate joburi", stil_sectiune))
        date_tabel = [["Job", "Companie", "Oraș", "Status", "Data"]]
        for a in aplicari[:10]:
            if a.job:
                from datetime import datetime
                data_str = a.creat_la.strftime("%d.%m.%Y") if a.creat_la else "-"
                date_tabel.append([
                    Paragraph(a.job.titlu[:35], stil_normal),
                    Paragraph(a.job.companie[:25], stil_normal),
                    a.job.oras[:15],
                    a.status.capitalize(),
                    data_str,
                ])
        tabel = Table(date_tabel, colWidths=[5*cm, 4*cm, 3*cm, 2.5*cm, 2.5*cm])
        tabel.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), ALBASTRU),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f1f5f9")]),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ]))
        elemente.append(tabel)

    # Footer
    elemente.append(Spacer(1, 20))
    elemente.append(HRFlowable(width="100%", thickness=1, color=GRI))
    elemente.append(Paragraph(
        f"Generat de JobPart • jobpart.ro • {__import__('datetime').datetime.now().strftime('%d.%m.%Y')}",
        ParagraphStyle("footer", parent=styles["Normal"], textColor=GRI, fontSize=8, alignment=1)
    ))

    doc.build(elemente)
    buf.seek(0)

    nume_fisier = f"profil_{user.nume.replace(' ', '_')}_JobPart.pdf"
    return StreamingResponse(buf, media_type="application/pdf",
                             headers={"Content-Disposition": f"attachment; filename={nume_fisier}"})
