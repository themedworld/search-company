import os
import jwt
from datetime import datetime, timedelta
from typing import Optional

from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
from gradio_client import Client
from dotenv import load_dotenv

# =========================
# LOAD ENV
# =========================
load_dotenv()

HF_SPACE_URL = os.getenv(
    "HF_SPACE_URL",
    "https://themedworld-searchcompay.hf.space"
)

JWT_SECRET = os.getenv("JWT_SECRET", "super-secret-key")

# =========================
# APP
# =========================
app = FastAPI(title="OSINT API Gateway")

# =========================
# CLIENT
# =========================
client = Client(HF_SPACE_URL)

# =========================
# MODEL
# =========================
class OSINTRequest(BaseModel):
    company_name: str
    company_handle: str
    country_name: str = "Tunisia"
    country_iso: str = "TN"

# =========================
# JWT VERIFY
# =========================
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Token manquant")

    try:
        scheme, token = authorization.split()

        if scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Bearer requis")

        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return payload

    except Exception:
        raise HTTPException(status_code=401, detail="Token invalide")

# =========================
# COMMON FUNCTION
# =========================
def run_osint(data: OSINTRequest):
    result = client.predict(
        company_name=data.company_name,
        company_handle=data.company_handle,
        country_name=data.country_name,
        country_iso=data.country_iso,
        api_name="/run_osint"
    )

    logs, markdown, json_str = result

    return {
        "success": True,
        "input": data.dict(),
        "logs": logs,
        "results_markdown": markdown,
        "results_json": json_str
    }

# =========================
# API 1 : TEST SANS JWT
# =========================
@app.post("/predict-osint-test")
def predict_osint_test(data: OSINTRequest):
    return run_osint(data)

# =========================
# API 2 : AVEC JWT
# =========================
@app.post("/predict-osint")
def predict_osint(
    data: OSINTRequest,
    token_data: dict = Depends(verify_token)
):
    return run_osint(data)

# =========================
# GENERATE TOKEN
# =========================
@app.post("/generate-token")
def generate_token():
    payload = {
        "sub": "user-osint",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(days=7)
    }

    token = jwt.encode(payload, JWT_SECRET, algorithm="HS256")

    return {"token": token}

# =========================
# HEALTH
# =========================
@app.get("/health")
def health():
    return {"status": "ok"}
