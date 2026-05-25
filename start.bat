@echo off
echo Instalare dependente Python...
cd backend
pip install -r requirements.txt
echo.
echo Pornire server JobPart...
echo Accesează aplicația la: http://localhost:8000/static/index.html
echo Documentatie API: http://localhost:8000/docs
echo.
python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000
