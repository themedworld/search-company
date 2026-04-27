import os
import threading
from datetime import datetime
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import uuid
import sys

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
# IMPORT OSINT ENGINE
# =========================
# On importe directement les fonctions de app.py (même conteneur HF Space)
# Si app.py est dans le même répertoire :
sys.path.insert(0, os.path.dirname(__file__))

try:
    from app import run_osint_with_session, set_stop_event
    OSINT_MODE = "local"
    print("✅ OSINT engine importé localement depuis app.py")
except ImportError:
    # Fallback : utiliser le client Gradio si app.py n'est pas disponible localement
    from gradio_client import Client
    _gradio_client = Client(HF_SPACE_URL)
    OSINT_MODE = "gradio"
    print(f"⚠️  OSINT engine via Gradio client : {HF_SPACE_URL}")

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
# SESSION MANAGEMENT
# =========================

class OSINTSession:
    def __init__(self):
        self.progress = 0.0
        self.status   = "idle"
        self.result   = None
        self.logs     = []
        self.stop_flag = False
        self.lock      = threading.Lock()

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
    country_iso: str  = "TN"
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
# HELPERS
# =========================

def update_progress(session_id: str, progress: float,
                    log_msg: str = "", status: str = "running"):
    session = get_or_create_session(session_id)
    with session.lock:
        session.progress = min(progress, 100.0)
        session.status   = status
        if log_msg:
            session.logs.append(log_msg)


def run_osint_background(session_id: str, data: OSINTRequest):
    """
    Exécute OSINT en arrière-plan.

    Flux corrigé :
    1. On lance run_osint_with_session() qui fait le vrai travail.
    2. Quand la fonction retourne (normalement OU après InterruptedError),
       on récupère markdown + json et on les stocke dans la session.
    3. Si stop_flag était levé, on marque partial=True.
    """
    session = get_or_create_session(session_id)

    with session.lock:
        session.status    = "running"
        session.progress  = 0
        session.logs      = []
        session.stop_flag = False

    print(f"🚀 Session {session_id} lancée : {data.company_name}")

    try:
        update_progress(session_id, 5, "🔍 Initialisation de la recherche...")

        # ── Appel principal ──────────────────────────────────
        if OSINT_MODE == "local":
            # Appel direct — run_osint_with_session gère le stop via set_stop_event()
            logs_str, markdown, json_str = run_osint_with_session(
                company_name   = data.company_name,
                company_handle = data.company_handle,
                country_name   = data.country_name,
                country_iso    = data.country_iso,
                session_id     = session_id,
            )
        else:
            # Fallback Gradio client (bloquant — le stop ne peut qu'arriver après)
            update_progress(session_id, 10, "📡 Connexion au service OSINT...")
            result_tuple = _gradio_client.predict(
                company_name   = data.company_name,
                company_handle = data.company_handle,
                country_name   = data.country_name,
                country_iso    = data.country_iso,
                api_name       = "/run_osint",
            )
            logs_str, markdown, json_str = result_tuple

        # ── Vérifier si un arrêt a été demandé pendant l'exécution ──
        with session.lock:
            was_stopped = session.stop_flag

        # ── Stocker le résultat (partiel ou complet) ──────────
        logs_list = logs_str.split("\n") if isinstance(logs_str, str) else logs_str

        with session.lock:
            session.result = {
                "success"         : not was_stopped,
                "partial"         : was_stopped,          # ← clé du fix
                "input"           : data.dict(),
                "logs"            : logs_list,
                "results_markdown": markdown,              # ← toujours les vraies données
                "results_json"    : json_str,              # ← toujours les vraies données
                "message"         : (
                    "Recherche arrêtée — résultats partiels disponibles"
                    if was_stopped else
                    "Recherche complétée avec succès"
                ),
            }
            session.progress = session.progress if was_stopped else 100.0
            session.status   = "stopped" if was_stopped else "completed"
            session.logs     = logs_list
            session.logs.append(
                "🛑 Arrêté — résultats partiels sauvegardés"
                if was_stopped else
                "✅ OSINT terminé avec succès !"
            )

        print(f"{'⏸️ Arrêté' if was_stopped else '✅ Complété'} — session {session_id}")

    except Exception as e:
        print(f"❌ Session {session_id} erreur : {e}")
        with session.lock:
            # Ne pas écraser un statut "stopped" déjà positionné
            if session.status != "stopped":
                session.status = "error"
                session.logs.append(f"❌ Erreur : {str(e)}")
                session.result = {
                    "success"         : False,
                    "partial"         : False,
                    "input"           : data.dict(),
                    "logs"            : session.logs,
                    "error"           : str(e),
                    "results_markdown": "",
                    "results_json"    : "{}",
                    "message"         : "Une erreur s'est produite",
                }

# =========================
# API 1 : TEST SANS JWT
# =========================

@app.post("/predict-osint-test")
def predict_osint_test(data: OSINTRequest):
    """Test endpoint sans authentification — appel synchrone."""
    print(f"🧪 TEST : {data.company_name}")
    try:
        if OSINT_MODE == "local":
            logs_str, markdown, json_str = run_osint_with_session(
                data.company_name, data.company_handle,
                data.country_name, data.country_iso,
                session_id=str(uuid.uuid4()),
            )
        else:
            result = _gradio_client.predict(
                company_name   = data.company_name,
                company_handle = data.company_handle,
                country_name   = data.country_name,
                country_iso    = data.country_iso,
                api_name       = "/run_osint",
            )
            logs_str, markdown, json_str = result

        return {
            "success"         : True,
            "input"           : data.dict(),
            "logs"            : logs_str,
            "results_markdown": markdown,
            "results_json"    : json_str,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# =========================
# API 2 : LANCER OSINT ASYNC
# =========================

@app.post("/predict-osint")
def predict_osint(data: OSINTRequest, background_tasks: BackgroundTasks):
    """Lance une recherche OSINT de manière asynchrone."""
    print(f"🚀 Recherche lancée : {data.company_name}")

    session_id = data.session_id or str(uuid.uuid4())
    get_or_create_session(session_id)

    background_tasks.add_task(run_osint_background, session_id, data)

    return {
        "session_id"  : session_id,
        "message"     : "Recherche lancée",
        "status"      : "running",
        "progress_url": f"/progress/{session_id}",
    }

# =========================
# API 3 : PROGRESSION
# =========================

@app.get("/progress/{session_id}", response_model=ProgressResponse)
def get_progress(session_id: str):
    """Récupère la progression en temps réel."""
    session = get_or_create_session(session_id)
    with session.lock:
        return ProgressResponse(
            session_id = session_id,
            progress   = session.progress,
            status     = session.status,
            logs       = session.logs,
            result     = session.result,
        )

# =========================
# API 4 : ARRÊTER
# =========================

@app.post("/stop/{session_id}", response_model=StopResponse)
def stop_osint_search(session_id: str):
    """
    Arrête une recherche OSINT en cours.

    Mécanisme :
    - On lève session.stop_flag (lu par run_osint_background)
    - On lève set_stop_event(session_id) (lu par les fonctions internes de app.py)
    - On retourne immédiatement — le background thread finit proprement
      et sauvegarde les résultats partiels réels.
    """
    session = get_or_create_session(session_id)

    with session.lock:
        if session.status not in ["running", "idle"]:
            return StopResponse(
                session_id = session_id,
                message    = f"Impossible d'arrêter - Statut actuel : {session.status}",
                status     = session.status,
                result     = session.result,
            )

        # Lever les deux flags
        session.stop_flag = True
        session.logs.append("🛑 Arrêt demandé...")

    # Lever le flag interne de app.py (propagé à toutes les sous-fonctions)
    if OSINT_MODE == "local":
        set_stop_event(session_id)

    print(f"⏹️  Arrêt demandé pour session {session_id}")

    # On retourne "stopping" — le statut final sera mis à jour
    # par run_osint_background quand il aura fini de collecter les partiels
    return StopResponse(
        session_id = session_id,
        message    = "Arrêt en cours — résultats partiels seront sauvegardés dès la fin de l'étape courante",
        status     = "stopping",
        result     = None,
    )

# =========================
# API 5 : NETTOYER SESSION
# =========================

@app.delete("/session/{session_id}")
def clear_session(session_id: str):
    if session_id in sessions:
        session = sessions[session_id]
        with session.lock:
            if session.status in ["completed", "stopped", "error"]:
                del sessions[session_id]
                print(f"🗑️  Session {session_id} supprimée")
                return {"message": "Session supprimée"}
            else:
                raise HTTPException(
                    status_code=400,
                    detail=f"Impossible de supprimer - Statut : {session.status}",
                )
    raise HTTPException(status_code=404, detail="Session non trouvée")

# =========================
# API 6 : HEALTH CHECK
# =========================

@app.get("/health")
def health():
    return {
        "status"         : "ok",
        "message"        : "OSINT API Gateway is running",
        "osint_mode"     : OSINT_MODE,
        "active_sessions": len(sessions),
        "timestamp"      : datetime.now().isoformat(),
    }

# =========================
# API 7 : DEBUG — TOUTES SESSIONS
# =========================

@app.get("/sessions")
def get_all_sessions():
    return {
        "total_sessions": len(sessions),
        "sessions": {
            sid: {
                "status"     : s.status,
                "progress"   : s.progress,
                "logs_count" : len(s.logs),
                "has_result" : s.result is not None,
                "stop_flag"  : s.stop_flag,
            }
            for sid, s in sessions.items()
        },
    }

# =========================
# API 8 : DEBUG — DÉTAILS SESSION
# =========================

@app.get("/session/{session_id}")
def get_session_details(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session non trouvée")
    session = sessions[session_id]
    with session.lock:
        return {
            "session_id": session_id,
            "status"    : session.status,
            "progress"  : session.progress,
            "logs"      : session.logs,
            "result"    : session.result,
            "stop_flag" : session.stop_flag,
        }

# =========================
# OPTIONS (preflight CORS)
# =========================

@app.options("/{full_path:path}")
async def options_handler(full_path: str):
    return {}

# =========================
# ROOT
# =========================

@app.get("/")
def root():
    return {
        "app"      : "OSINT API Gateway",
        "version"  : "2.0.0",
        "status"   : "running",
        "osint_mode": OSINT_MODE,
        "features" : [
            "Async OSINT search",
            "Real-time progress tracking",
            "Partial results on stop (real data)",
            "Per-session stop flag",
            "Session management",
        ],
        "endpoints": {
            "health"        : "GET  /health",
            "sessions_debug": "GET  /sessions",
            "session_details": "GET  /session/{session_id}",
            "predict"       : "POST /predict-osint",
            "predict_test"  : "POST /predict-osint-test",
            "progress"      : "GET  /progress/{session_id}",
            "stop"          : "POST /stop/{session_id}",
            "clear"         : "DELETE /session/{session_id}",
        },
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
# STARTUP / SHUTDOWN
# =========================

@app.on_event("startup")
async def startup_event():
    print("🚀 OSINT API Gateway démarrée")
    print(f"📡 Mode : {OSINT_MODE}")
    if OSINT_MODE == "gradio":
        print(f"   HF Space : {HF_SPACE_URL}")

@app.on_event("shutdown")
async def shutdown_event():
    print("🛑 OSINT API Gateway arrêtée")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)