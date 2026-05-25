"""
Rulează acest script o singură dată pentru a crea contul de admin.
Exemplu: python creeaza-admin.py
"""
import sys
sys.path.insert(0, "backend")

from backend.database import engine, SessionLocal
from backend import models
from backend.auth import hash_parola

models.Base.metadata.create_all(bind=engine)

db = SessionLocal()

email = "admin@jobpart.ro"
existent = db.query(models.User).filter(models.User.email == email).first()
if existent:
    print(f"Contul admin există deja: {email}")
else:
    admin = models.User(
        nume="Administrator",
        email=email,
        parola_hash=hash_parola("admin123"),
        rol="admin",
        activ=True,
    )
    db.add(admin)
    db.commit()
    print("Cont admin creat cu succes!")
    print(f"  Email: {email}")
    print(f"  Parolă: admin123")
    print("  IMPORTANT: Schimbă parola după primul login!")

db.close()
