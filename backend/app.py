"""KnowSuite — RAGFlow 企业增强套件 入口.

五大模块：评测看板 / 版本治理 / 订阅支付 / OEM 贴牌 / 视频理解
启动：uvicorn app:app --host 0.0.0.0 --port 8100  （或 python app.py）
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fastapi import FastAPI, Depends          # noqa: E402
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles   # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from sqlalchemy.orm import Session            # noqa: E402

import config                                # noqa: E402
from db import init_db, get_db               # noqa: E402
from modules import evaluation, versioning, billing, oem, video  # noqa: E402
import ragflow_client as rf                  # noqa: E402

app = FastAPI(title="KnowSuite", version="0.1.0",
              description="RAGFlow 企业增强套件：RAGAS 评测 / 版本治理 / 订阅支付 / OEM 贴牌 / 视频理解")

app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=False,
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(evaluation.router)
app.include_router(versioning.router)
app.include_router(billing.router)
app.include_router(oem.router)
app.include_router(video.router)


def _bootstrap():
    """建表 + 播种套餐（幂等）。模块加载即执行，兼容 TestClient 不触发 startup 的场景。"""
    init_db()
    from db import SessionLocal
    db = SessionLocal()
    try:
        billing.seed_plans(db)
    finally:
        db.close()


_bootstrap()


@app.on_event("startup")
def startup():
    _bootstrap()


@app.get("/api/health")
def health(db: Session = Depends(get_db)):
    return {"ok": True, "service": "knowsuite", "version": "0.1.0",
            "ragflow": {"mocked": rf.mocked(), "api_base": config.RAGFLOW_API_BASE,
                        "datasets_reachable": _ragflow_ping()},
            "llm": {"mock": config.MOCK_LLM, "model": config.AI_MODEL,
                    "embed": config.AI_EMBED_MODEL},
            "ffmpeg": video.ffmpeg_available(),
            "payment_gateway": config.PAYMENT_GATEWAY}


def _ragflow_ping():
    try:
        rf.list_datasets(page=1, size=1)
        return True
    except Exception:  # noqa
        return False


@app.get("/api/datasets")
def datasets_proxy():
    """给前端下拉框用的 RAGFlow 知识库列表。"""
    try:
        return rf.list_datasets()
    except Exception as e:  # noqa
        return JSONResponse({"error": str(e)}, status_code=502)


# ---- 前端控制台（零构建静态页） ----
FRONTEND = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.isdir(FRONTEND):
    app.mount("/static", StaticFiles(directory=FRONTEND), name="static")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(os.path.join(FRONTEND, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=config.KNOWSUITE_PORT, reload=False)
