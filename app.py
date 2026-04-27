import os
import asyncio
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from gradio_client import Client
from dotenv import load_dotenv
import uuid
import time

# =========================
# LOAD ENV
# =========================

load_dotenv()

HF_SPACE_URL = os.getenv(
    "HF_SPACE_URL",
    "https://themedworld-searchcompay.hf.space"
)

FRONTEND_URL = os.getenv("FRONTEND_URL", "http://localhost:3000")

# =========================
# APP
# =========================

app = FastAPI(title="OSINT API Gateway")

# =========================
# CORS MIDDLEWARE
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "http://localhost:3001",
        "https://localhost:3000",
        FRONTEND_URL,
        "https://search-company-xc9u.onrender.com",
        "*",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# =========================
# CLIENT
# =========================

client = Client(HF_SPACE_URL)

# =========================
# GLOBAL STATE MANAGEMENT
# =========================

class OSINTSession:
    def __init__(self):
        self.progress = 0.0
        self.status = "idle"
        self.result = None
        self.logs = []
        self.stop_flag = False
        self.lock = threading.Lock()

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
    session_id: Optional[str] = None

class ProgressResponse(BaseModel):
    session_id: str
    progress: float
    status: str
    logs: list
    result: Optional[Dict[str, Any]] = None

class StopResponse(BaseModel):
    session_id: str
    message: str
    status: str
    result: Optional[Dict[str, Any]] = None

# =========================
# COMMON FUNCTIONS
# =========================

def update_progress(session_id: str, progress: float, log_msg: str = "", status: str = "running"):
    """Met à jour la progression et les logs"""
    session = get_or_create_session(session_id)
    with session.lock:
        session.progress = min(progress, 100.0)
        session.status = status
        if log_msg:
            session.logs.append(log_msg)

def save_partial_result(session_id: str, data: OSINTRequest, logs: list):
    """Sauvegarde les résultats partiels lors d'un arrêt"""
    session = get_or_create_session(session_id)
    with session.lock:
        session.result = {
            "success": False,
            "partial": True,
            "input": data.dict(),
            "logs": logs,
            "progress": session.progress,
            "results_markdown": "Recherche arrêtée par l'utilisateur",
            "results_json": "{}",
            "message": "Recherche arrêtée - résultats partiels disponibles"
        }
        session.status = "stopped"

def run_osint_background(session_id: str, data: OSINTRequest):
    """Exécute OSINT en arrière-plan avec suivi de progression"""
    session = get_or_create_session(session_id)
    
    try:
        with session.lock:
            session.status = "running"
            session.progress = 0
            session.logs = []
            session.stop_flag = False
        
        print(f"🚀 Session {session_id} lancée: {data.company_name}")
        
        # ÉTAPE 1
        update_progress(session_id, 10, "🔍 Initialisation de la recherche...")
        time.sleep(0.5)
        
        # ✅ VÉRIFICATION ARRÊT APRÈS CHAQUE ÉTAPE
        with session.lock:
            if session.stop_flag:
                save_partial_result(session_id, data, session.logs)
                session.logs.append("🛑 Recherche arrêtée par l'utilisateur (étape 1)")
                print(f"⏸️ Session {session_id} arrêtée à l'étape 1")
                return
        
        # ÉTAPE 2
        update_progress(session_id, 25, "📱 Recherche des réseaux sociaux...")
        time.sleep(0.5)
        
        # ✅ VÉRIFICATION ARRÊT
        with session.lock:
            if session.stop_flag:
                save_partial_result(session_id, data, session.logs)
                session.logs.append("🛑 Recherche arrêtée par l'utilisateur (étape 2)")
                print(f"⏸️ Session {session_id} arrêtée à l'étape 2")
                return
        
        # ÉTAPE 3
        update_progress(session_id, 50, "👥 Recherche des employés LinkedIn...")
        time.sleep(0.5)
        
        # ✅ VÉRIFICATION ARRÊT
        with session.lock:
            if session.stop_flag:
                save_partial_result(session_id, data, session.logs)
                session.logs.append("🛑 Recherche arrêtée par l'utilisateur (étape 3)")
                print(f"⏸️ Session {session_id} arrêtée à l'étape 3")
                return
        
        # ÉTAPE 4
        update_progress(session_id, 75, "📧 Recherche des emails...")
        time.sleep(0.5)
        
        # ✅ VÉRIFICATION ARRÊT
        with session.lock:
            if session.stop_flag:
                save_partial_result(session_id, data, session.logs)
                session.logs.append("🛑 Recherche arrêtée par l'utilisateur (étape 4)")
                print(f"⏸️ Session {session_id} arrêtée à l'étape 4")
                return
        
        # ÉTAPE 5 - APPEL API
        print(f"📡 Appel Gradio pour session {session_id}...")
        update_progress(session_id, 90, "🔄 Traitement des résultats...")
        
        try:
            result = client.predict(
                company_name=data.company_name,
                company_handle=data.company_handle,
                country_name=data.country_name,
                country_iso=data.country_iso,
                api_name="/run_osint"
            )
            
            logs, markdown, json_str = result
            
            # ✅ VÉRIFICATION ARRÊT AVANT COMPLÉTION
            with session.lock:
                if session.stop_flag:
                    save_partial_result(session_id, data, session.logs)
                    session.logs.append("🛑 Recherche arrêtée par l'utilisateur (étape 5)")
                    print(f"⏸️ Session {session_id} arrêtée à l'étape 5")
                    return
            
            # SUCCÈS
            with session.lock:
                session.result = {
                    "success": True,
                    "partial": False,
                    "input": data.dict(),
                    "logs": logs,
                    "results_markdown": markdown,
                    "results_json": json_str,
                    "message": "Recherche complétée avec succès"
                }
                session.progress = 100
                session.status = "completed"
                session.logs.append("✅ OSINT terminé avec succès !")
            
            print(f"✅ Session {session_id} complétée avec succès")
        
        except Exception as gradio_error:
            print(f"❌ Erreur Gradio pour session {session_id}: {str(gradio_error)}")
            
            # Vérifier si c'est un arrêt pendant l'appel Gradio
            with session.lock:
                if session.stop_flag:
                    save_partial_result(session_id, data, session.logs)
                    session.logs.append("🛑 Recherche arrêtée pendant l'appel API")
                    return
            
            # Sinon, erreur réelle
            with session.lock:
                session.status = "error"
                session.logs.append(f"❌ Erreur Gradio : {str(gradio_error)}")
                session.result = {
                    "success": False,
                    "partial": False,
                    "input": data.dict(),
                    "logs": session.logs,
                    "error": str(gradio_error),
                    "message": "Erreur lors de l'appel API"
                }
            raise

    except Exception as e:
        print(f"❌ Session {session_id} erreur: {str(e)}")
        
        # Vérifier si c'est un arrêt volontaire
        with session.lock:
            if not session.stop_flag and session.status != "stopped":
                session.status = "error"
                session.logs.append(f"❌ Erreur : {str(e)}")
                session.result = {
                    "success": False,
                    "partial": False,
                    "input": data.dict(),
                    "logs": session.logs,
                    "error": str(e),
                    "message": "Une erreur s'est produite"
                }

# =========================
# API 1: TEST SANS JWT
# =========================

@app.post("/predict-osint-test")
def predict_osint_test(data: OSINTRequest):
    """Test endpoint sans authentification"""
    print(f"🧪 TEST: {data.company_name}")
    try:
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
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# API 2: PREDICT OSINT
# =========================

@app.post("/predict-osint")
def predict_osint(
    data: OSINTRequest,
    background_tasks: BackgroundTasks
):
    """Lance une recherche OSINT de manière asynchrone"""
    
    print(f"🚀 Recherche lancée: {data.company_name}")
    
    session_id = data.session_id or str(uuid.uuid4())
    session = get_or_create_session(session_id)
    
    # Ajouter la tâche de fond
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
def get_progress(session_id: str):
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
def stop_osint_search(session_id: str):
    """Arrête une recherche OSINT en cours"""
    session = get_or_create_session(session_id)
    
    with session.lock:
        if session.status not in ["running", "idle"]:
            return StopResponse(
                session_id=session_id,
                message=f"Impossible d'arrêter - Statut actuel: {session.status}",
                status=session.status,
                result=session.result
            )
        
        # ✅ DÉFINIR LE FLAG D'ARRÊT
        session.stop_flag = True
        session.logs.append("🛑 Arrêt demandé...")
        
        print(f"⏹️ Arrêt demandé pour session {session_id}")
        
        # Retourner immédiatement
        return StopResponse(
            session_id=session_id,
            message="Arrêt en cours - résultats partiels seront sauvegardés",
            status="stopped",
            result=session.result
        )

# =========================
# API 5: NETTOYER LES RÉSULTATS
# =========================

@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    """Nettoie une session terminée"""
    if session_id in sessions:
        session = sessions[session_id]
        with session.lock:
            if session.status in ["completed", "stopped", "error"]:
                del sessions[session_id]
                print(f"🗑️ Session {session_id} supprimée")
                return {"message": "Session supprimée"}
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de supprimer - Statut: {session.status}"
                )
    raise HTTPException(status_code=404, detail="Session non trouvée")

# =========================
# API 6: HEALTH CHECK
# =========================

@app.get("/health")
def health():
    """Health check endpoint"""
    return {
        "status": "ok",
        "message": "OSINT API Gateway is running",
        "active_sessions": len(sessions),
        "timestamp": datetime.now().isoformat()
    }

# =========================
# API 7: GET ALL SESSIONS (DEBUG)
# =========================

@app.get("/sessions")
def get_all_sessions():
    """DEBUG: Voir toutes les sessions actives"""
    return {
        "total_sessions": len(sessions),
        "sessions": {
            sid: {
                "status": s.status,
                "progress": s.progress,
                "logs_count": len(s.logs),
                "has_result": s.result is not None,
                "stop_flag": s.stop_flag
            }
            for sid, s in sessions.items()
        }
    }

# =========================
# API 8: GET SESSION DETAILS (DEBUG)
# =========================

@app.get("/session/{session_id}")
def get_session_details(session_id: str):
    """DEBUG: Voir les détails d'une session"""
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session non trouvée")
    
    session = sessions[session_id]
    with session.lock:
        return {
            "session_id": session_id,
            "status": session.status,
            "progress": session.progress,
            "logs": session.logs,
            "result": session.result,
            "stop_flag": session.stop_flag
        }

# =========================
# OPTIONS (pour les preflight requests)
# =========================

@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    """Gère les requêtes OPTIONS (preflight CORS)"""
    return {}

# =========================
# ROOT ENDPOINT
# =========================

@app.get("/")
def root():
    """Root endpoint"""
    return {
        "app": "OSINT API Gateway",
        "version": "1.0.2",
        "status": "running",
        "features": [
            "Async OSINT search",
            "Real-time progress tracking",
            "Partial results on stop",
            "Session management",
            "Proper stop handling"
        ],
        "endpoints": {
            "health": "GET /health",
            "sessions_debug": "GET /sessions",
            "session_details": "GET /session/{session_id}",
            "predict": "POST /predict-osint",
            "predict_test": "POST /predict-osint-test",
            "progress": "GET /progress/{session_id}",
            "stop": "POST /stop/{session_id}",
            "clear": "DELETE /session/{session_id}",
        }
    }

# =========================
# ERROR HANDLERS
# =========================

@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )

# =========================
# STARTUP/SHUTDOWN
# =========================

@app.on_event("startup")
async def startup_event():
    print("🚀 OSINT API Gateway démarrée")
    print(f"📡 Connected to HF Space: {HF_SPACE_URL}")

@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 OSINT API Gateway arrêtée")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)