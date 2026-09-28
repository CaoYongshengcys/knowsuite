"""模块 2：旧稿识别归并 / 版本治理.

上传时相似度比对（强提示≈九成相似 / 弱提示较相似，最多列 3 篇旧稿），
归并只写版本关系不删文件；现行稿/历史稿分链管理；检索侧提供"仅现行稿"清单；支持拆回独立与对照 diff。
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import DocVersion, MergeLog
from modules import sha256_text, cosine, excerpt
import llm

router = APIRouter(prefix="/api/versions", tags=["versioning"])

STRONG_THRESHOLD = 0.90   # 强提示：疑似同一文档新版本
WEAK_THRESHOLD = 0.75    # 弱提示：较相似


class CheckReq(BaseModel):
    kb_id: str
    title: str
    text: str


class RegisterReq(BaseModel):
    kb_id: str
    title: str
    text: str = ""
    ragflow_doc_id: str = ""
    parent_id: int | None = None
    note: str = ""
    created_by: str = ""


class MergeReq(BaseModel):
    chain_id: str
    keep_id: int
    operator: str = ""


class SplitReq(BaseModel):
    doc_id: int
    operator: str = ""


def _doc_brief(d: DocVersion, sim: float | None = None):
    out = {"id": d.id, "title": d.title, "kb_id": d.kb_id, "chain_id": d.chain_id,
           "is_current": d.is_current, "ragflow_doc_id": d.ragflow_doc_id,
           "created_at": d.created_at.isoformat() + "Z", "created_by": d.created_by,
           "note": d.note}
    if sim is not None:
        out["similarity"] = round(sim, 4)
    return out


@router.post("/check")
def check_old_version(req: CheckReq, db: Session = Depends(get_db)):
    """上传前/入库时调用：返回完全重复 + 强/弱相似旧稿（各最多3篇）。"""
    fp = sha256_text(req.text)
    exact = db.query(DocVersion).filter(DocVersion.kb_id == req.kb_id,
                                        DocVersion.fingerprint == fp).first()
    emb = llm.embed([excerpt(req.text, 2000)])[0]
    cands = db.query(DocVersion).filter(DocVersion.kb_id == req.kb_id,
                                        DocVersion.is_current.is_(True)).all()
    scored = []
    for d in cands:
        try:
            sim = cosine(emb, d.embedding_json or [])
        except Exception:  # noqa
            sim = 0.0
        if sim >= WEAK_THRESHOLD:
            scored.append((sim, d))
    scored.sort(key=lambda x: -x[0])
    strong = [_doc_brief(d, s) for s, d in scored[:3] if s >= STRONG_THRESHOLD]
    weak = [_doc_brief(d, s) for s, d in scored[:3] if WEAK_THRESHOLD <= s < STRONG_THRESHOLD]
    level = "duplicate" if exact else ("strong" if strong else ("weak" if weak else "none"))
    hint = {
        "duplicate": "检测到内容完全相同的文档（秒级去重）：%s" % (exact.title if exact else ""),
        "strong": "检测到高度相似旧稿（疑似同一文档的新版本），建议归并为版本链。",
        "weak": "检测到较相似文档，请确认是否相关。",
        "none": "未发现相似旧稿，可直接入库。",
    }[level]
    return {"level": level, "hint": hint,
            "exact": _doc_brief(exact) if exact else None,
            "strong": strong, "weak": weak,
            "embedding_ready": True}


@router.post("/register")
def register(req: RegisterReq, db: Session = Depends(get_db)):
    """登记一个文档版本（通常在 RAGFlow 上传成功后调用）。parent_id 为空则开新链。"""
    fp = sha256_text(req.text)
    emb = llm.embed([excerpt(req.text, 2000)])[0] if req.text else []
    parent = None
    if req.parent_id:
        parent = db.get(DocVersion, req.parent_id)
        if not parent:
            raise HTTPException(404, "parent_id 不存在")
    d = DocVersion(kb_id=req.kb_id, ragflow_doc_id=req.ragflow_doc_id, title=req.title,
                   parent_id=parent.id if parent else None,
                   chain_id=parent.chain_id if parent else "",
                   is_current=True, text_excerpt=excerpt(req.text), embedding_json=emb,
                   fingerprint=fp, note=req.note, created_by=req.created_by)
    if parent:
        # 新版本入链：旧现行稿转历史（归并只改关系，不动 RAGFlow 文件）
        for old in db.query(DocVersion).filter(DocVersion.chain_id == parent.chain_id,
                                               DocVersion.is_current.is_(True)).all():
            old.is_current = False
        db.add(MergeLog(chain_id=parent.chain_id, action="set_current",
                                from_doc=parent.id, to_doc=0, operator=req.created_by))
    db.add(d)
    db.flush()
    if not d.chain_id:
        d.chain_id = "ch-%d-%s" % (d.id, uuid.uuid4().hex[:6])
    db.commit()
    db.refresh(d)
    return _doc_brief(d)


@router.get("/chains")
def chains(kb_id: str = "", db: Session = Depends(get_db)):
    q = db.query(DocVersion)
    if kb_id:
        q = q.filter(DocVersion.kb_id == kb_id)
    docs = q.order_by(DocVersion.created_at.desc()).all()
    grouped = {}
    for d in docs:
        grouped.setdefault(d.chain_id or ("single-%d" % d.id), []).append(d)
    out = []
    for cid, items in grouped.items():
        cur = next((x for x in items if x.is_current), items[0])
        out.append({"chain_id": cid, "kb_id": cur.kb_id, "versions": len(items),
                    "current": _doc_brief(cur),
                    "latest_at": max(x.created_at for x in items).isoformat() + "Z"})
    out.sort(key=lambda x: x["latest_at"], reverse=True)
    return out


@router.get("/chains/{chain_id}")
def chain_detail(chain_id: str, db: Session = Depends(get_db)):
    items = db.query(DocVersion).filter(DocVersion.chain_id == chain_id)\
        .order_by(DocVersion.created_at.asc()).all()
    if not items:
        raise HTTPException(404, "版本链不存在")
    logs = db.query(MergeLog).filter(MergeLog.chain_id == chain_id)\
        .order_by(MergeLog.created_at.asc()).all()
    return {"chain_id": chain_id,
            "versions": [_doc_brief(d) for d in items],
            "logs": [{"action": l.action, "from_doc": l.from_doc, "to_doc": l.to_doc,
                      "operator": l.operator, "at": l.created_at.isoformat() + "Z"} for l in logs]}


@router.post("/merge")
def merge(req: MergeReq, db: Session = Depends(get_db)):
    """归并：keep_id 设为现行稿，同链其余转历史稿（不删除任何文件）。"""
    items = db.query(DocVersion).filter(DocVersion.chain_id == req.chain_id).all()
    keep = next((d for d in items if d.id == req.keep_id), None)
    if not keep:
        raise HTTPException(400, "keep_id 不在该版本链中")
    for d in items:
        d.is_current = (d.id == req.keep_id)
    db.add(MergeLog(chain_id=req.chain_id, action="merge",
                            from_doc=0, to_doc=req.keep_id, operator=req.operator))
    db.commit()
    return {"ok": True, "current": _doc_brief(keep)}


@router.post("/split")
def split(req: SplitReq, db: Session = Depends(get_db)):
    """单份拆回独立：仅该文档出链，不影响链上其他版本。"""
    d = db.get(DocVersion, req.doc_id)
    if not d:
        raise HTTPException(404, "文档不存在")
    old_chain = d.chain_id
    d.chain_id = "ch-%d-%s" % (d.id, uuid.uuid4().hex[:6])
    d.parent_id = None
    d.is_current = True
    db.add(MergeLog(chain_id=old_chain, action="split",
                            from_doc=d.id, to_doc=0, operator=req.operator))
    db.commit()
    return {"ok": True, "doc": _doc_brief(d)}


@router.get("/current")
def current_docs(kb_id: str, db: Session = Depends(get_db)):
    """检索侧助手接口：某知识库的全部现行稿（历史稿默认不参与问答）。"""
    items = db.query(DocVersion).filter(DocVersion.kb_id == kb_id,
                                        DocVersion.is_current.is_(True)).all()
    return [_doc_brief(d) for d in items]


@router.get("/compare")
def compare(a: int, b: int, db: Session = Depends(get_db)):
    """两版本按段落粗分对照（unified diff）。"""
    import difflib
    da, dbb = db.get(DocVersion, a), db.get(DocVersion, b)
    if not da or not dbb:
        raise HTTPException(404, "文档不存在")
    pa = [p for p in (da.text_excerpt or "").split("\n") if p.strip()]
    pb = [p for p in (dbb.text_excerpt or "").split("\n") if p.strip()]
    diff = list(difflib.unified_diff(pa, pb, fromfile=da.title, tofile=dbb.title, lineterm=""))
    return {"a": _doc_brief(da), "b": _doc_brief(dbb),
            "unified_diff": diff[:400],
            "para_count": [len(pa), len(pb)]}
