import os
import jwt
from datetime import datetime, timedelta
from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from gradio_client import Client
from dotenv import load_dotenv
from typing import Optional

# Charger .env
load_dotenv()

# =========================
# CONFIG
# =========================
HF_SPACE_URL = os.getenv("HF_SPACE_URL", "https://themedworld-searchcompay.hf.space")
JWT_SECRET = os.getenv("JWT_SECRET", "your-secret-key")

# =========================
# APP
# =========================
app = FastAPI(title="OSINT API Gateway")

# =========================
# GRADIO CLIENT
# =========================
client = Client(HF_SPACE_URL)

# =========================
# REQUEST MODEL
# =========================
class OSINTRequest(BaseModel):
    company_name: str
    company_handle: str
    country_name: str = "Tunisia"
    country_iso: str = "TN"

# =========================
# JWT VERIFICATION
# =========================
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token manquant")
    
    try:
        scheme, token = authorization.split()
        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Schéma invalide")
        
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Token invalide")
    except ValueError:
        raise HTTPException(status_code=401, detail="Format d'en-tête invalide")

# =========================
# API ENDPOINT
# =========================
@app.post("/predict-osint")
def predict_osint(data: OSINTRequest, token_data: dict = Depends(verify_token)):
    try:
        # Appeler la fonction run_osint du Space Gradio
        result = client.predict(
            company_name=data.company_name,
            company_handle=data.company_handle,
            country_name=data.country_name,
            country_iso=data.country_iso,
            api_name="/run_osint"  # ← Nom de la fonction Gradio
        )

        # result est un tuple : (logs, markdown, json_str)
        logs, markdown, json_str = result

        return {
            "success": True,
            "input": {
                "company_name": data.company_name,
                "company_handle": data.company_handle
            },
            "logs": logs,
            "results_markdown": markdown,
            "results_json": json_str
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# GENERATE TOKEN (debug)
# =========================
@app.post("/generate-token")
def generate_token():
    """Génère un JWT token pour les tests"""
    payload = {
        "exp": datetime.utcnow() + timedelta(days=7),
        "iat": datetime.utcnow(),
        "sub": "osint-user"
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")
    return {"token": token}

@app.get("/health")
def health():
    return {"status": "ok"}