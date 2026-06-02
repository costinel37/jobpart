import os
import threading
import logging
import urllib.request
import urllib.parse
import json

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID", "")


def _trimite_mesaj(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = json.dumps({
            "chat_id": TELEGRAM_CHANNEL_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=10)
        logger.info("[TELEGRAM] Mesaj trimis cu succes")
    except Exception as e:
        logger.warning(f"[TELEGRAM] Eroare trimitere mesaj: {e}")


def notifica_job_nou(job):
    """Trimite notificare în canalul Telegram când apare un job nou."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHANNEL_ID:
        return

    salariu = ""
    if job.salariu_min and job.salariu_max:
        salariu = f"{job.salariu_min:,} – {job.salariu_max:,} RON".replace(",", ".")
    elif job.salariu_min:
        salariu = f"de la {job.salariu_min:,} RON".replace(",", ".")
    else:
        salariu = "Negociabil"

    descriere = ""
    if job.descriere:
        descriere = job.descriere[:120].strip()
        if len(job.descriere) > 120:
            descriere += "..."

    categorie_tag = f"#{job.categorie.lower().replace(' ', '_')}" if job.categorie else ""
    oras_tag = f"#{job.oras.lower().replace(' ', '_').replace('-', '')}" if job.oras else ""

    link = f"https://jobpart.ro/static/job-detalii.html?id={job.id}"

    mesaj = (
        f"🆕 <b>Job nou pe JobPart.ro!</b>\n\n"
        f"💼 <b>{job.titlu}</b>\n"
        f"🏢 {job.companie}\n"
        f"📍 {job.oras}\n"
        f"💰 {salariu}\n"
        f"🏷️ {job.categorie or 'Part-time'}\n"
    )
    if descriere:
        mesaj += f"\n📝 <i>{descriere}</i>\n"

    mesaj += (
        f"\n🔗 <a href='{link}'>Aplică acum →</a>\n\n"
        f"#jobparttime #joburi {categorie_tag} {oras_tag}"
    )

    threading.Thread(target=_trimite_mesaj, args=(mesaj,), daemon=True).start()
