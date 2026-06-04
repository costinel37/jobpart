import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import logging
from config import MAIL_USERNAME, MAIL_PASSWORD, MAIL_FROM, MAIL_SERVER, MAIL_PORT, MAIL_STARTTLS, FRONTEND_URL

logger = logging.getLogger(__name__)


def _trimite_email(destinatar: str, subiect: str, corp_html: str):
    """Trimitere email prin SMTP. Eșuează silențios dacă SMTP nu e configurat."""
    if not MAIL_USERNAME or not MAIL_PASSWORD:
        logger.info(f"[EMAIL SIMULAT] Către: {destinatar} | Subiect: {subiect}")
        return

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subiect
        msg["From"] = MAIL_FROM
        msg["To"] = destinatar
        msg.attach(MIMEText(corp_html, "html", "utf-8"))

        with smtplib.SMTP(MAIL_SERVER, MAIL_PORT, timeout=10) as server:
            if MAIL_STARTTLS:
                server.starttls()
            server.login(MAIL_USERNAME, MAIL_PASSWORD)
            server.sendmail(MAIL_FROM, destinatar, msg.as_string())
        logger.info(f"Email trimis către {destinatar}")
    except Exception as e:
        logger.error(f"Eroare email către {destinatar}: {e}")


def email_aplicare_noua(email_angajator: str, titlu_job: str, companie: str,
                         nume_candidat: str, job_id: int, aplicare_id: int):
    subiect = f"Aplicare nouă pentru {titlu_job} - JobPart"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#2563eb">Ai primit o aplicare nouă!</h2>
      <p>Candidatul <strong>{nume_candidat}</strong> a aplicat la jobul tău:</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
        <p style="margin:4px 0;color:#64748b">{companie}</p>
      </div>
      <a href="{FRONTEND_URL}/static/dashboard-angajator.html"
         style="display:inline-block;background:#2563eb;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Vezi aplicarea
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_angajator, subiect, corp)


def email_job_expira_curand(email_angajator: str, titlu_job: str, zile_ramase: int):
    subiect = f"⚠️ Jobul '{titlu_job}' expiră în {zile_ramase} zile"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#f59e0b">⚠️ Jobul expiră în curând!</h2>
      <p>Anunțul tău va expira în <strong>{zile_ramase} {'zi' if zile_ramase == 1 else 'zile'}</strong>:</p>
      <div style="background:#fef3c7;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #f59e0b">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
      </div>
      <p>Reînnoiește anunțul pentru încă 30 de zile gratuit din dashboard-ul tău.</p>
      <a href="{FRONTEND_URL}/static/dashboard-angajator.html"
         style="display:inline-block;background:#f59e0b;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Reînnoiește anunțul
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_angajator, subiect, corp)


def email_job_expirat(email_angajator: str, titlu_job: str):
    subiect = f"📋 Anunțul '{titlu_job}' a expirat"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#64748b">Anunțul a expirat</h2>
      <p>Anunțul tău nu mai este vizibil candidaților:</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
      </div>
      <p>Reînnoiește anunțul gratuit pentru încă 30 de zile.</p>
      <a href="{FRONTEND_URL}/static/dashboard-angajator.html"
         style="display:inline-block;background:#2563eb;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Reînnoiește acum
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_angajator, subiect, corp)


def email_promovare_expira_curand(email_angajator: str, titlu_job: str, ore_ramase: int):
    subiect = f"⚠️ Promovarea jobului '{titlu_job}' expiră în {ore_ramase} ore"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#f59e0b">⚠️ Promovarea expiră curând!</h2>
      <p>Promovarea jobului tău expiră în mai puțin de <strong>{ore_ramase} ore</strong>:</p>
      <div style="background:#fef3c7;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #f59e0b">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
      </div>
      <p>Reînnoiește promovarea pentru a continua să atragi candidați calificați.</p>
      <a href="{FRONTEND_URL}/static/dashboard-angajator.html"
         style="display:inline-block;background:#f59e0b;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Reînnoiește promovarea
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_angajator, subiect, corp)


def email_promovare_expirata(email_angajator: str, titlu_job: str):
    subiect = f"📋 Promovarea jobului '{titlu_job}' a expirat"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#64748b">Promovarea a expirat</h2>
      <p>Promovarea jobului tău a expirat și nu mai apare primul în lista de căutare:</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
      </div>
      <p>Reactivează promovarea pentru a atrage din nou mai mulți candidați.</p>
      <a href="{FRONTEND_URL}/static/dashboard-angajator.html"
         style="display:inline-block;background:#2563eb;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Reactivează promovarea
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_angajator, subiect, corp)


def email_confirmare_cont(email: str, token: str):
    link = f"{FRONTEND_URL}/static/confirmare-email.html?token={token}"
    subiect = "Confirmă-ți contul JobPart"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#2563eb">Bun venit pe JobPart!</h2>
      <p>Confirmă adresa de email pentru a-ți activa contul:</p>
      <a href="{link}"
         style="display:inline-block;background:#2563eb;color:white;padding:14px 28px;
                border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0">
        Confirmă contul
      </a>
      <p style="color:#94a3b8;font-size:13px">Link-ul expiră în 24 de ore. Dacă nu ai creat un cont, ignoră acest email.</p>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email, subiect, corp)


def email_resetare_parola(email: str, token: str):
    link = f"{FRONTEND_URL}/static/resetare-parola.html?token={token}"
    subiect = "Resetare parolă JobPart"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#2563eb">Resetare parolă</h2>
      <p>Ai solicitat resetarea parolei. Apasă butonul de mai jos:</p>
      <a href="{link}"
         style="display:inline-block;background:#2563eb;color:white;padding:14px 28px;
                border-radius:8px;text-decoration:none;font-weight:bold;margin:16px 0">
        Resetează parola
      </a>
      <p style="color:#94a3b8;font-size:13px">Link-ul expiră în 1 oră. Dacă nu tu ai solicitat, ignoră acest email.</p>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email, subiect, corp)


def email_confirmare_aplicare(email_candidat: str, titlu_job: str, companie: str, oras: str):
    subiect = f"✅ Aplicarea ta la '{titlu_job}' a fost înregistrată"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:#7c3aed">✅ Aplicare înregistrată cu succes!</h2>
      <p>Aplicarea ta a fost trimisă angajatorului. Îți vom trimite un email când aceasta este vizualizată sau procesată.</p>
      <div style="background:#f5f3ff;border-radius:8px;padding:16px;margin:16px 0;border-left:4px solid #7c3aed">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
        <p style="margin:4px 0;color:#6d28d9">{companie} · {oras}</p>
      </div>
      <a href="{FRONTEND_URL}/static/dashboard-candidat.html"
         style="display:inline-block;background:#7c3aed;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold">
        Vezi aplicările mele
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma #1 de joburi part-time din România</p>
    </div>"""
    _trimite_email(email_candidat, subiect, corp)


def email_status_schimbat(email_candidat: str, titlu_job: str, companie: str, status_nou: str, motiv: str = None):
    status_labels = {
        "vizualizata": ("Aplicarea ta a fost vizualizată", "#f59e0b", "👀"),
        "acceptata": ("Felicitări! Aplicarea ta a fost acceptată", "#10b981", "🎉"),
        "respinsa": ("Aplicarea ta a fost respinsă", "#ef4444", "📋"),
    }
    titlu_status, culoare, emoji = status_labels.get(
        status_nou, ("Status aplicare actualizat", "#2563eb", "📬")
    )
    subiect = f"{emoji} {titlu_status} - {titlu_job}"
    corp = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:auto;padding:20px">
      <h2 style="color:{culoare}">{emoji} {titlu_status}</h2>
      <p>Aplicarea ta la jobul de mai jos a fost actualizată:</p>
      <div style="background:#f1f5f9;border-radius:8px;padding:16px;margin:16px 0">
        <p style="margin:0;font-size:18px;font-weight:bold">{titlu_job}</p>
        <p style="margin:4px 0;color:#64748b">{companie}</p>
      </div>
      {'<p style="color:#10b981;font-weight:bold">Te vor contacta în curând pentru pașii următori!</p>' if status_nou == "acceptata" else ''}
      {f'<div style="background:#fef2f2;border-radius:8px;padding:12px;margin:12px 0;border-left:4px solid #ef4444"><p style="margin:0;color:#dc2626"><strong>Motiv:</strong> {motiv}</p></div>' if motiv and status_nou == "respinsa" else ''}
      <a href="{FRONTEND_URL}/static/dashboard-candidat.html"
         style="display:inline-block;background:#2563eb;color:white;padding:12px 24px;
                border-radius:8px;text-decoration:none;font-weight:bold">
        Vezi aplicările mele
      </a>
      <p style="color:#94a3b8;font-size:12px;margin-top:24px">JobPart - Platforma de joburi part-time</p>
    </div>"""
    _trimite_email(email_candidat, subiect, corp)
