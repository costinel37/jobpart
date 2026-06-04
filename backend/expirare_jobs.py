import threading
import logging
import os
from datetime import datetime, timedelta
from database import SessionLocal
import models
from notificari_service import creeaza_notificare
from email_service import (
    email_promovare_expirata, email_promovare_expira_curand,
    email_job_expira_curand, email_job_expirat,
)
from config import UPLOAD_DIR

logger = logging.getLogger(__name__)
_lock = threading.Lock()


def _ruleaza_verificari():
    if not _lock.acquire(blocking=False):
        return  # o altă instanță rulează deja
    try:
        db = SessionLocal()
        now = datetime.utcnow()
        try:
            _verifica_job_expira_curand(db, now)
            _verifica_job_expirat(db, now)
            _verifica_promovare_expira_curand(db, now)
            _verifica_promovare_expirata(db, now)
            _curata_cv_orfane(db)
            _curata_cv_expirate(db, now)
            _curata_date_expirate(db, now)
            _trimite_job_alerts(db, now)
        finally:
            db.close()
    except Exception as e:
        logger.error(f"[EXPIRARE] Eroare task: {e}")
    finally:
        _lock.release()


def _verifica_job_expira_curand(db, now):
    prag = now + timedelta(days=3)
    joburi = db.query(models.Job).filter(
        models.Job.activ == True,
        models.Job.expira_la != None,
        models.Job.expira_la > now,
        models.Job.expira_la <= prag,
        models.Job.avertisment_job == False,
    ).all()
    for job in joburi:
        zile = max(1, (job.expira_la - now).days)
        angajator = db.query(models.User).filter(models.User.id == job.angajator_id).first()
        if angajator:
            creeaza_notificare(
                db, angajator.id, tip="job_expira",
                mesaj=f"Anunțul '{job.titlu}' expiră în {zile} {'zi' if zile == 1 else 'zile'}! Reînnoiește-l.",
                link="/static/dashboard-angajator.html",
            )
            threading.Thread(target=email_job_expira_curand,
                             args=(angajator.email, job.titlu, zile), daemon=True).start()
        job.avertisment_job = True
    if joburi:
        db.commit()


def _verifica_job_expirat(db, now):
    joburi = db.query(models.Job).filter(
        models.Job.activ == True,
        models.Job.expira_la != None,
        models.Job.expira_la <= now,
    ).all()
    for job in joburi:
        angajator = db.query(models.User).filter(models.User.id == job.angajator_id).first()
        if angajator:
            creeaza_notificare(
                db, angajator.id, tip="job_expirat",
                mesaj=f"Anunțul '{job.titlu}' a expirat și nu mai este vizibil. Reînnoiește-l gratuit!",
                link="/static/dashboard-angajator.html",
            )
            threading.Thread(target=email_job_expirat,
                             args=(angajator.email, job.titlu), daemon=True).start()
        job.activ = False
    if joburi:
        db.commit()


def _verifica_promovare_expira_curand(db, now):
    prag = now + timedelta(hours=24)
    joburi = db.query(models.Job).filter(
        models.Job.promovat == True,
        models.Job.promovat_pana > now,
        models.Job.promovat_pana <= prag,
        models.Job.avertisment_expirare == False,
    ).all()
    for job in joburi:
        ore = max(1, int((job.promovat_pana - now).total_seconds() // 3600))
        angajator = db.query(models.User).filter(models.User.id == job.angajator_id).first()
        if angajator:
            creeaza_notificare(
                db, angajator.id, tip="promovare_expira",
                mesaj=f"Promovarea jobului '{job.titlu}' expiră în {ore} ore!",
                link="/static/dashboard-angajator.html",
            )
            threading.Thread(target=email_promovare_expira_curand,
                             args=(angajator.email, job.titlu, ore), daemon=True).start()
        job.avertisment_expirare = True
    if joburi:
        db.commit()


def _verifica_promovare_expirata(db, now):
    joburi = db.query(models.Job).filter(
        models.Job.promovat == True,
        models.Job.promovat_pana < now,
    ).all()
    for job in joburi:
        angajator = db.query(models.User).filter(models.User.id == job.angajator_id).first()
        if angajator:
            creeaza_notificare(
                db, angajator.id, tip="promovare_expirata",
                mesaj=f"Promovarea jobului '{job.titlu}' a expirat. Reînnoiește pentru mai multă vizibilitate.",
                link="/static/dashboard-angajator.html",
            )
            threading.Thread(target=email_promovare_expirata,
                             args=(angajator.email, job.titlu), daemon=True).start()
        job.promovat = False
        job.promovat_pana = None
        job.avertisment_expirare = False
    if joburi:
        db.commit()


def _curata_cv_orfane(db):
    """Șterge fișierele CV de pe disk care nu mai au referință în baza de date."""
    try:
        if not os.path.isdir(UPLOAD_DIR):
            return
        cv_in_db = {
            row[0] for row in
            db.query(models.Application.cv_path)
            .filter(models.Application.cv_path != None)
            .all()
        }
        sterse = 0
        for fisier in os.listdir(UPLOAD_DIR):
            if fisier not in cv_in_db:
                try:
                    os.remove(os.path.join(UPLOAD_DIR, fisier))
                    sterse += 1
                except OSError:
                    pass
        if sterse:
            logger.info(f"[CV CLEANUP] {sterse} fișiere orfane șterse din uploads/")
    except Exception as e:
        logger.error(f"[CV CLEANUP] Eroare: {e}")


def _curata_cv_expirate(db, now):
    """Șterge CV-urile pentru aplicări respinse mai vechi de 30 de zile (GDPR Art. 5(1)(e))."""
    try:
        limita = now - timedelta(days=30)
        aplicari = db.query(models.Application).filter(
            models.Application.status == "respinsa",
            models.Application.creat_la < limita,
            models.Application.cv_path != None,
        ).all()
        sterse = 0
        for a in aplicari:
            cale = os.path.join(UPLOAD_DIR, a.cv_path)
            if os.path.exists(cale):
                try:
                    os.remove(cale)
                    sterse += 1
                except OSError:
                    pass
            a.cv_path = None
            a.cv_nume_original = None
        if aplicari:
            db.commit()
        if sterse:
            logger.info(f"[GDPR CLEANUP] {sterse} CV-uri expirate șterse (aplicări respinse > 30 zile)")
    except Exception as e:
        logger.error(f"[GDPR CLEANUP CV] Eroare: {e}")


def _curata_date_expirate(db, now):
    """Anonimizează conturile inactive > 2 ani și șterge mesajele/notificările vechi (GDPR Art. 5(1)(e))."""
    try:
        # Mesaje mai vechi de 1 an
        limita_mesaje = now - timedelta(days=365)
        sterse_mesaje = db.query(models.Message).filter(
            models.Message.creat_la < limita_mesaje
        ).delete(synchronize_session=False)

        # Notificări mai vechi de 90 de zile
        limita_notif = now - timedelta(days=90)
        sterse_notif = db.query(models.Notification).filter(
            models.Notification.creat_la < limita_notif
        ).delete(synchronize_session=False)

        # Tokeni de resetare parolă expirați
        db.query(models.PasswordReset).filter(
            models.PasswordReset.expira_la < now
        ).delete(synchronize_session=False)

        # Tokeni de verificare email expirați
        db.query(models.EmailVerification).filter(
            models.EmailVerification.expira_la < now
        ).delete(synchronize_session=False)

        db.commit()
        if sterse_mesaje or sterse_notif:
            logger.info(f"[GDPR CLEANUP] Mesaje: {sterse_mesaje}, Notificări: {sterse_notif}")
    except Exception as e:
        logger.error(f"[GDPR CLEANUP DATE] Eroare: {e}")


def porneste_task_expirare(interval_secunde: int = 300):
    """Rulează verificările de expirare la fiecare `interval_secunde` secunde."""
    _ruleaza_verificari()

    def _loop():
        import time
        while True:
            time.sleep(interval_secunde)
            _ruleaza_verificari()

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    logger.info(f"[EXPIRARE] Task pornit, interval: {interval_secunde}s")


def _trimite_job_alerts(db, now):
    """Verifică alertele active și trimite email candidaților pentru joburi noi."""
    from email_service import _trimite_email
    from config import FRONTEND_URL

    alerts = db.query(models.JobAlert).filter(models.JobAlert.activ == True).all()
    for alert in alerts:
        try:
            query = db.query(models.Job).filter(
                models.Job.activ == True,
                models.Job.creat_la > alert.ultima_verificare,
            )
            if alert.categorie:
                query = query.filter(models.Job.categorie == alert.categorie)
            if alert.oras:
                query = query.filter(models.Job.oras.ilike(f"%{alert.oras}%"))
            if alert.salariu_min:
                query = query.filter(models.Job.salariu_min >= alert.salariu_min)

            joburi_noi = query.limit(5).all()
            if not joburi_noi:
                alert.ultima_verificare = now
                db.commit()
                continue

            user = db.query(models.User).filter(models.User.id == alert.user_id, models.User.activ == True).first()
            if not user:
                continue

            lista_html = "".join([
                f'<li style="margin-bottom:8px"><a href="{FRONTEND_URL}/static/job-detalii.html?id={j.id}" style="color:#7c3aed;font-weight:bold">{j.titlu}</a> — {j.companie}, {j.oras}</li>'
                for j in joburi_noi
            ])
            criteriu = f"{alert.categorie or 'Toate categoriile'}" + (f" în {alert.oras}" if alert.oras else "")
            corp = f"""
            <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
              <h2 style="color:#7c3aed">🔔 Joburi noi pentru alerta ta</h2>
              <p>Criterii: <strong>{criteriu}</strong></p>
              <ul style="padding-left:20px">{lista_html}</ul>
              <a href="{FRONTEND_URL}/static/jobs.html" style="display:inline-block;background:#7c3aed;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:12px">
                Vezi toate joburile →
              </a>
              <p style="color:#94a3b8;font-size:12px;margin-top:16px">JobPart · <a href="{FRONTEND_URL}/static/dashboard-candidat.html" style="color:#94a3b8">Dezactivează alerta</a></p>
            </div>"""
            _trimite_email(user.email, f"🔔 {len(joburi_noi)} joburi noi pentru {criteriu}", corp)
            alert.ultima_verificare = now
            db.commit()
            logger.info(f"[ALERT] Trimis {len(joburi_noi)} joburi la {user.email}")
        except Exception as e:
            logger.warning(f"[ALERT] Eroare alert {alert.id}: {e}")


def porneste_keep_alive(interval_secunde: int = 600):
    """Ping la propria adresă ca să nu adoarmă pe Render free tier."""
    import time
    import urllib.request

    app_url = (
        os.getenv("RENDER_EXTERNAL_URL")
        or os.getenv("APP_URL")
        or os.getenv("FRONTEND_URL", "")
    ).rstrip("/")
    if not app_url:
        logger.info("[KEEP-ALIVE] APP_URL negăsit, keep-alive dezactivat (setează RENDER_EXTERNAL_URL)")
        return

    def _loop():
        while True:
            time.sleep(interval_secunde)
            try:
                urllib.request.urlopen(f"{app_url}/ping", timeout=10)
                logger.info("[KEEP-ALIVE] Ping ok")
            except Exception as e:
                logger.warning(f"[KEEP-ALIVE] Ping eșuat: {e}")

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    logger.info(f"[KEEP-ALIVE] Pornit, interval: {interval_secunde}s, URL: {app_url}")
