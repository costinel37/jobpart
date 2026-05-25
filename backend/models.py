from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, ForeignKey, Enum, Float, UniqueConstraint
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
    activ = Column(Boolean, default=True)
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
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    tip = Column(String(50), nullable=False)  # aplicare_noua, status_schimbat, mesaj_nou, recenzie_noua
    mesaj = Column(String(300), nullable=False)
    link = Column(String(300), nullable=True)
    citit = Column(Boolean, default=False)
    creat_la = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="notificari")


class Application(Base):
    __tablename__ = "applications"

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
