"""KnowSuite configuration (env-driven, no external deps)."""
import os


def _b(name, default="0"):
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


def _load_dotenv():
    """Minimal .env loader (avoid pydantic-settings dependency)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            k, v = k.strip(), v.strip().strip('"').strip("'")
            os.environ.setdefault(k, v)


_load_dotenv()

RAGFLOW_API_BASE = os.environ.get("RAGFLOW_API_BASE", "http://127.0.0.1:80").rstrip("/")
RAGFLOW_API_KEY = os.environ.get("RAGFLOW_API_KEY", "").strip()
RAGFLOW_WEB = os.environ.get("RAGFLOW_WEB", RAGFLOW_API_BASE).rstrip("/")
MOCK_RAGFLOW = _b("MOCK_RAGFLOW") or not RAGFLOW_API_KEY

AI_API_BASE = os.environ.get("AI_API_BASE", "https://dashscope.aliyuncs.com/compatible-mode/v1").rstrip("/")
AI_API_KEY = os.environ.get("AI_API_KEY", "").strip()
AI_MODEL = os.environ.get("AI_MODEL", "qwen-plus")
AI_EMBED_MODEL = os.environ.get("AI_EMBED_MODEL", "text-embedding-v4")
MOCK_LLM = _b("MOCK_LLM") or not AI_API_KEY
AI_TIMEOUT = int(os.environ.get("AI_TIMEOUT", "180"))

ASR_API_BASE = os.environ.get("ASR_API_BASE", "").rstrip("/")
ASR_API_KEY = os.environ.get("ASR_API_KEY", "").strip()
ASR_MODEL = os.environ.get("ASR_MODEL", "whisper-large-v3-turbo")
ASR_OMNI_MODEL = os.environ.get("ASR_OMNI_MODEL", "").strip()
VL_MODEL = os.environ.get("VL_MODEL", "qwen-vl-plus")
VIDEO_MAX_FRAMES = int(os.environ.get("VIDEO_MAX_FRAMES", "12"))
VIDEO_FRAME_INTERVAL = int(os.environ.get("VIDEO_FRAME_INTERVAL", "30"))  # seconds

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data"))
KNOWSUITE_PORT = int(os.environ.get("KNOWSUITE_PORT", "8100"))
PAYMENT_GATEWAY = os.environ.get("PAYMENT_GATEWAY", "mock")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "change-me-admin-token")

os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "videos"), exist_ok=True)
os.makedirs(os.path.join(DATA_DIR, "video_md"), exist_ok=True)

DB_PATH = os.path.join(DATA_DIR, "knowsuite.db")
SQLALCHEMY_URL = "sqlite:///" + DB_PATH
