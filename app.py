import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from gradio_client import Client
from dotenv import load_dotenv

# Charger .env
load_dotenv()

# =========================
# CONFIG
# =========================
HF_SPACE_URL = os.getenv("HF_SPACE_URL", "https://themedworld-searchcompay.hf.space")
JWT_SECRET = os.getenv("JWT_SECRET", "")

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
# API ENDPOINT
# =========================
@app.post("/predict-osint")
def predict_osint(data: OSINTRequest):
    try:
        result = client.predict(
            company_name=data.company_name,
            company_handle=data.company_handle,
            country_name=data.country_name,
            country_iso=data.country_iso,
            api_name="/predict"  # Adapter selon votre Space
        )

        return {
            "success": True,
            "input": {
                "company_name": data.company_name,
                "company_handle": data.company_handle
            },
            "prediction": result
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health():
    return {"status": "ok"}