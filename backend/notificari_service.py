from sqlalchemy.orm import Session
import models


def creeaza_notificare(db: Session, user_id: int, tip: str, mesaj: str, link: str = None):
    notif = models.Notification(user_id=user_id, tip=tip, mesaj=mesaj, link=link)
    db.add(notif)
    db.commit()
