from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, Date, ForeignKey, Enum, Float, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime
import enum
from database import Base


class UserRole(str, enum.Enum):
    candidat = "candidat"
    angajator = "angajator"
    admin = "admin"


class ApplicationStatus(str, enum.Enum):
    trimisa = "trimisa"
    vizualizata = "vizualizata"
    acceptata = "acceptata"
    respinsa = "respinsa"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nume = Column(String(100), nullable=False)
    email = Column(String(150), unique=True, index=True, nullable=False)
    parola_hash = Column(String(255), nullable=False)
    rol = Column(String(20), default=UserRole.candidat)
    telefon = Column(String(20), nullable=True)
    oras = Column(String(100), nullable=True)
    despre = Column(Text, nullable=True)
    activ = Column(Boolean, default=True)
    email_confirmat = Column(Boolean, default=False)
    newsletter_consimtit = Column(Boolean, default=False)
    gdpr_consimtit_la = Column(DateTime, nullable=True)
    data_nasterii = Column(Date, nullable=True)
    parola_schimbata_la = Column(DateTime, nullable=True)
    cv_profil_path = Column(String(500), nullable=True)
    cv_profil_nume = Column(String(255), nullable=True)
    creat_la = Column(DateTime, default=datetime.utcnow)

    joburi_postate = relationship("Job", back_populates="angajator")
    aplicari = relationship("Application", back_populates="candidat")
    favorite = relationship("Favorite", back_populates="user")
    mesaje_trimise = relationship("Message", foreign_keys="Message.expeditor_id", back_populates="expeditor")
    mesaje_primite = relationship("Message", foreign_keys="Message.destinatar_id", back_populates="destinatar")
    notificari = relationship("Notification", back_populates="user")


class Job(Base):
    __tablename__ = "jobs"

    id = Column(Integer, primary_key=True, index=True)
    titlu = Column(String(200), nullable=False)
    descriere = Column(Text, nullable=False)
    cerinte = Column(Text, nullable=True)
    beneficii = Column(Text, nullable=True)
    companie = Column(String(150), nullable=False)
    oras = Column(String(100), nullable=False)
    tip_program = Column(String(50), default="part-time")
    salariu_min = Column(Integer, nullable=True)
    salariu_max = Column(Integer, nullable=True)
    categorie = Column(String(100), nullable=True)
    lat = Column(Float, nullable=True)
    lng = Column(Float, nullable=True)
    activ = Column(Boolean, default=True, index=True)
    expira_la = Column(DateTime, nullable=True)
    avertisment_job = Column(Boolean, default=False)
    promovat = Column(Boolean, default=False)
    promovat_pana = Column(DateTime, nullable=True)
    avertisment_expirare = Column(Boolean, default=False)
    creat_la = Column(DateTime, default=datetime.utcnow)
    angajator_id = Column(Integer, ForeignKey("users.id"))

    angajator = relationship("User", back_populates="joburi_postate")
    aplicari = relationship("Application", back_populates="job")
    favorite = relationship("Favorite", back_populates="job")


class Favorite(Base):
    __tablename__ = "favorites"
    __table_args__ = (UniqueConstraint("user_id", "job_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="favorite")
    job = relationship("Job", back_populates="favorite")


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = (UniqueConstraint("autor_id", "subiect_id"),)

    id = Column(Integer, primary_key=True, index=True)
    autor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subiect_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    rating = Column(Integer, nullable=False)
    comentariu = Column(Text, nullable=True)
    creat_la = Column(DateTime, default=datetime.utcnow)

    autor = relationship("User", foreign_keys=[autor_id])
    subiect = relationship("User", foreign_keys=[subiect_id])


class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    expeditor_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    destinatar_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    subiect = Column(String(200), nullable=False)
    continut = Column(Text, nullable=False)
    citit = Column(Boolean, default=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    expeditor = relationship("User", foreign_keys=[expeditor_id], back_populates="mesaje_trimise")
    destinatar = relationship("User", foreign_keys=[destinatar_id], back_populates="mesaje_primite")


class Notification(Base):
    __tablename__ = "notifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    tip = Column(String(50), nullable=False)  # aplicare_noua, status_schimbat, mesaj_nou, recenzie_noua
    mesaj = Column(String(300), nullable=False)
    link = Column(String(300), nullable=True)
    citit = Column(Boolean, default=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notificari")


class EmailVerification(Base):
    __tablename__ = "email_verifications"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    creat_la = Column(DateTime, default=datetime.utcnow)
    expira_la = Column(DateTime, nullable=False)

    user = relationship("User")


class PasswordReset(Base):
    __tablename__ = "password_resets"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    token = Column(String(64), unique=True, nullable=False, index=True)
    creat_la = Column(DateTime, default=datetime.utcnow)
    expira_la = Column(DateTime, nullable=False)
    folosit = Column(Boolean, default=False)

    user = relationship("User")


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (UniqueConstraint("candidat_id", "job_id"),)

    id = Column(Integer, primary_key=True, index=True)
    scrisoare = Column(Text, nullable=True)
    cv_path = Column(String(500), nullable=True)
    cv_nume_original = Column(String(255), nullable=True)
    status = Column(String(20), default=ApplicationStatus.trimisa)
    creat_la = Column(DateTime, default=datetime.utcnow)
    candidat_id = Column(Integer, ForeignKey("users.id"))
    job_id = Column(Integer, ForeignKey("jobs.id"))

    candidat = relationship("User", back_populates="aplicari")
    job = relationship("Job", back_populates="aplicari")


class JobAlert(Base):
    """Abonament la notificări pentru joburi noi care se potrivesc criteriilor."""
    __tablename__ = "job_alerts"
    __table_args__ = (UniqueConstraint("user_id", "categorie", "oras"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    categorie = Column(String(100), nullable=True)
    oras = Column(String(100), nullable=True)
    salariu_min = Column(Integer, nullable=True)
    activ = Column(Boolean, default=True)
    ultima_verificare = Column(DateTime, default=datetime.utcnow)
    creat_la = Column(DateTime, default=datetime.utcnow)

    user = relationship("User")


class JobLike(Base):
    """Aprecieri unice per job (bazat pe IP hash, fără autentificare)."""
    __tablename__ = "job_likes"
    __table_args__ = (UniqueConstraint("job_id", "ip_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    ip_hash = Column(String(64), nullable=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job")


class JobView(Base):
    """Înregistrează vizualizările unice per job (bazat pe IP hash)."""
    __tablename__ = "job_views"
    __table_args__ = (UniqueConstraint("job_id", "ip_hash"),)

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False, index=True)
    ip_hash = Column(String(64), nullable=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    job = relationship("Job")


class AuditLog(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    actiune = Column(String(100), nullable=False)
    target_type = Column(String(50), nullable=True)
    target_id = Column(Integer, nullable=True)
    detalii = Column(Text, nullable=True)
    creat_la = Column(DateTime, default=datetime.utcnow)

    admin = relationship("User", foreign_keys=[admin_id])


class PromovareCerere(Base):
    __tablename__ = "promotii_cereri"

    id = Column(Integer, primary_key=True, index=True)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    angajator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    plan = Column(String(20), nullable=False)       # "7zile", "14zile", "30zile"
    pret = Column(Integer, nullable=False)           # RON
    status = Column(String(20), default="in_asteptare")  # in_asteptare / aprobata / respinsa
    mesaj_admin = Column(Text, nullable=True)
    creat_la = Column(DateTime, default=datetime.utcnow)
    procesata_la = Column(DateTime, nullable=True)

    job = relationship("Job")
    angajator = relationship("User", foreign_keys=[angajator_id])


class Precontract(Base):
    __tablename__ = "precontracte"

    id = Column(Integer, primary_key=True, index=True)
    aplicare_id = Column(Integer, ForeignKey("applications.id"), nullable=False)
    job_id = Column(Integer, ForeignKey("jobs.id"), nullable=False)
    angajator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    candidat_id = Column(Integer, ForeignKey("users.id"), nullable=False)

    # Detalii job la momentul semnarii
    titlu_job = Column(String(200), nullable=False)
    companie = Column(String(150), nullable=False)
    oras = Column(String(100), nullable=False)
    program = Column(String(100), nullable=False)
    salariu = Column(String(100), nullable=False)
    data_inceput = Column(String(50), nullable=False)
    durata = Column(String(100), nullable=False)
    descriere_scurta = Column(Text, nullable=True)
    disclaimer = Column(Text, nullable=True)

    # Semnaturi
    semnat_angajator = Column(Boolean, default=False)
    semnat_angajator_la = Column(DateTime, nullable=True)
    semnat_candidat = Column(Boolean, default=False)
    semnat_candidat_la = Column(DateTime, nullable=True)

    status = Column(String(20), default="in_asteptare")  # in_asteptare / semnat / refuzat
    creat_la = Column(DateTime, default=datetime.utcnow)

    aplicare = relationship("Application")
    job = relationship("Job")
    angajator = relationship("User", foreign_keys=[angajator_id])
    candidat = relationship("User", foreign_keys=[candidat_id])
