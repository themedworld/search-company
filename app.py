import os
import jwt
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Depends, Header, BackgroundTasks
from fastapi.responses import JSONResponse
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
# GLOBAL STATE MANAGEMENT
# =========================

class OSINTSession:
    def __init__(self):
        self.progress = 0.0  # 0 to 100
        self.status = "idle"  # idle, running, stopped, completed, error
        self.result = None
        self.logs = []
        self.stop_flag = False
        self.lock = threading.Lock()

# Global session storage (in production, use Redis or database)
sessions: Dict[str, OSINTSession] = {}

def get_or_create_session(session_id: str) -> OSINTSession:
    if session_id not in sessions:
        sessions[session_id] = OSINTSession()
    return sessions[session_id]

# =========================
# MODELS
# =========================

class OSINTRequest(BaseModel):
    company_name: str
    company_handle: str
    country_name: str = "Tunisia"
    country_iso: str = "TN"
    session_id: Optional[str] = None  # Pour tracker la session

class ProgressResponse(BaseModel):
    session_id: str
    progress: float  # 0-100
    status: str  # idle, running, stopped, completed, error
    logs: list
    result: Optional[Dict[str, Any]] = None

class StopResponse(BaseModel):
    session_id: str
    message: str
    status: str
    result: Optional[Dict[str, Any]] = None

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

def update_progress(session_id: str, progress: float, log_msg: str = "", status: str = "running"):
    """Met à jour la progression et les logs"""
    session = get_or_create_session(session_id)
    with session.lock:
        session.progress = min(progress, 100.0)
        session.status = status
        if log_msg:
            session.logs.append(log_msg)

def run_osint_background(session_id: str, data: OSINTRequest):
    """Exécute OSINT en arrière-plan avec suivi de progression"""
    session = get_or_create_session(session_id)
    
    try:
        with session.lock:
            session.status = "running"
            session.progress = 0
            session.logs = []
        
        update_progress(session_id, 10, "🔍 Initialisation de la recherche...")
        
        # Vérifier le flag d'arrêt avant chaque étape importante
        if session.stop_flag:
            raise InterruptedError("Recherche arrêtée par l'utilisateur")
        
        update_progress(session_id, 25, "📱 Recherche des réseaux sociaux...")
        
        if session.stop_flag:
            raise InterruptedError("Recherche arrêtée par l'utilisateur")
        
        update_progress(session_id, 50, "👥 Recherche des employés LinkedIn...")
        
        if session.stop_flag:
            raise InterruptedError("Recherche arrêtée par l'utilisateur")
        
        update_progress(session_id, 75, "📧 Recherche des emails...")
        
        if session.stop_flag:
            raise InterruptedError("Recherche arrêtée par l'utilisateur")
        
        # Appel au service Gradio
        result = client.predict(
            company_name=data.company_name,
            company_handle=data.company_handle,
            country_name=data.country_name,
            country_iso=data.country_iso,
            api_name="/run_osint"
        )
        
        logs, markdown, json_str = result
        
        with session.lock:
            session.result = {
                "success": True,
                "input": data.dict(),
                "logs": logs,
                "results_markdown": markdown,
                "results_json": json_str
            }
            session.progress = 100
            session.status = "completed"
            session.logs.append("✅ OSINT terminé avec succès !")
    
    except InterruptedError as e:
        with session.lock:
            session.status = "stopped"
            session.logs.append(f"🛑 {str(e)}")
            if session.result:
                session.result["success"] = False
                session.result["stopped"] = True
    
    except Exception as e:
        with session.lock:
            session.status = "error"
            session.logs.append(f"❌ Erreur : {str(e)}")
            session.result = {
                "success": False,
                "error": str(e)
            }

# =========================
# API 1: TEST SANS JWT
# =========================

@app.post("/predict-osint-test")
def predict_osint_test(data: OSINTRequest):
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
# API 2: AVEC JWT
# =========================

@app.post("/predict-osint")
def predict_osint(
    data: OSINTRequest,
    token_data: dict = Depends(verify_token),
    background_tasks: BackgroundTasks = None
):
    """Lance une recherche OSINT de manière asynchrone"""
    import uuid
    
    session_id = data.session_id or str(uuid.uuid4())
    session = get_or_create_session(session_id)
    
    # Lancer la recherche en arrière-plan
    background_tasks.add_task(run_osint_background, session_id, data)
    
    return {
        "session_id": session_id,
        "message": "Recherche lancée",
        "status": "running",
        "progress_url": f"/progress/{session_id}"
    }

# =========================
# API 3: OBTENIR LA PROGRESSION EN TEMPS RÉEL
# =========================

@app.get("/progress/{session_id}", response_model=ProgressResponse)
def get_progress(session_id: str, token_data: dict = Depends(verify_token)):
    """Récupère la progression en temps réel d'une recherche OSINT"""
    session = get_or_create_session(session_id)
    
    with session.lock:
        return ProgressResponse(
            session_id=session_id,
            progress=session.progress,
            status=session.status,
            logs=session.logs,
            result=session.result
        )

# =========================
# API 4: ARRÊTER UNE RECHERCHE EN COURS
# =========================

@app.post("/stop/{session_id}", response_model=StopResponse)
def stop_osint_search(
    session_id: str,
    token_data: dict = Depends(verify_token)
):
    """Arrête une recherche OSINT en cours et retourne les résultats partiels"""
    session = get_or_create_session(session_id)
    
    with session.lock:
        if session.status not in ["running", "idle"]:
            return StopResponse(
                session_id=session_id,
                message=f"Impossible d'arrêter - Statut actuel: {session.status}",
                status=session.status,
                result=session.result
            )
        
        session.stop_flag = True
        session.status = "stopped"
        session.logs.append("🛑 Arrêt demandé — retour des résultats partiels.")
        
        return StopResponse(
            session_id=session_id,
            message="Recherche arrêtée avec succès",
            status="stopped",
            result=session.result
        )

# =========================
# API 5: NETTOYER LES RÉSULTATS
# =========================

@app.delete("/session/{session_id}")
def clear_session(
    session_id: str,
    token_data: dict = Depends(verify_token)
):
    """Nettoie une session terminée"""
    if session_id in sessions:
        session = sessions[session_id]
        with session.lock:
            if session.status in ["completed", "stopped", "error"]:
                del sessions[session_id]
                return {"message": "Session supprimée"}
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de supprimer - Statut: {session.status}"
                )
    raise HTTPException(status_code=404, detail="Session non trouvée")

# =========================
# API 6: GÉNÉRER TOKEN
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
# API 7: HEALTH
# =========================

@app.get("/health")
def health():
    return {"status": "ok
