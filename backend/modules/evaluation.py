"""模块 1：RAGAS 风格评测看板.

测试集管理 → 跑批（检索→回答→judge 打分）→ 结果与看板。
指标（0-1）：faithfulness 忠实度 / answer_relevancy 答案相关性 /
context_precision 上下文精确率 / context_recall 上下文召回率。
judge 采用单次 LLM 调用输出四维分数（成本低于 ragas 四次调用，可在 README 切换真 ragas）。
"""
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db, SessionLocal
from models import EvalSet, EvalCase, EvalRun, EvalResult
import llm
import ragflow_client as rf

router = APIRouter(prefix="/api/eval", tags=["evaluation"])

JUDGE_PROMPT = """你是 RAG 系统质量评审员。请对下面的一问一答与检索上下文打分（0~1 小数，两位精度）。

指标定义：
- faithfulness 忠实度：回答是否只基于给定上下文，无编造。
- answer_relevancy 答案相关性：回答是否切题、完整回应问题。
- context_precision 上下文精确率：上下文中与问题相关的片段占比（越靠前越准越高）。
- context_recall 上下文召回率：上下文是否覆盖了回答问题（或参考答案）所需的关键信息。

【问题】
{question}

【参考答案（可为空）】
{ground_truth}

【检索上下文】
{contexts}

【系统回答】
{answer}

只输出 JSON：{{"faithfulness":0.0,"answer_relevancy":0.0,"context_precision":0.0,"context_recall":0.0,"reason":"一句话理由"}}"""

RAG_PROMPT = """请仅根据以下知识库片段回答问题，信息不足时明确说明。用简体中文回答。

【知识库片段】
{contexts}

【问题】
{question}"""


# ---------- schemas ----------
class SetReq(BaseModel):
    name: str
    kb_id: str = ""
    chat_id: str = ""
    note: str = ""


class CaseReq(BaseModel):
    question: str
    ground_truth: str = ""
    tags: str = ""


class ImportReq(BaseModel):
    lines: str  # 每行: 问题||参考答案（参考可省略）


# ---------- sets & cases ----------
@router.post("/sets")
def create_set(req: SetReq, db: Session = Depends(get_db)):
    s = EvalSet(name=req.name, kb_id=req.kb_id, chat_id=req.chat_id, note=req.note)
    db.add(s)
    db.commit()
    db.refresh(s)
    return {"id": s.id, "name": s.name, "kb_id": s.kb_id, "chat_id": s.chat_id}


@router.get("/sets")
def list_sets(db: Session = Depends(get_db)):
    out = []
    for s in db.query(EvalSet).order_by(EvalSet.created_at.desc()).all():
        last = db.query(EvalRun).filter(EvalRun.set_id == s.id)\
            .order_by(EvalRun.started_at.desc()).first()
        out.append({"id": s.id, "name": s.name, "kb_id": s.kb_id, "chat_id": s.chat_id,
                    "note": s.note, "cases": len(s.cases),
                    "created_at": s.created_at.isoformat() + "Z",
                    "last_run": {"id": last.id, "status": last.status,
                                 "scores": last.scores_json,
                                 "at": last.started_at.isoformat() + "Z"} if last else None})
    return out


@router.get("/sets/{sid}")
def get_set(sid: int, db: Session = Depends(get_db)):
    s = db.get(EvalSet, sid)
    if not s:
        raise HTTPException(404, "测试集不存在")
    return {"id": s.id, "name": s.name, "kb_id": s.kb_id, "chat_id": s.chat_id, "note": s.note,
            "cases": [{"id": c.id, "question": c.question, "ground_truth": c.ground_truth,
                       "tags": c.tags} for c in s.cases]}


@router.delete("/sets/{sid}")
def delete_set(sid: int, db: Session = Depends(get_db)):
    s = db.get(EvalSet, sid)
    if not s:
        raise HTTPException(404, "测试集不存在")
    db.query(EvalResult).filter(EvalResult.run_id.in_(
        db.query(EvalRun.id).filter(EvalRun.set_id == sid))).delete(synchronize_session=False)
    db.query(EvalRun).filter(EvalRun.set_id == sid).delete()
    db.delete(s)
    db.commit()
    return {"ok": True}


@router.post("/sets/{sid}/cases")
def add_case(sid: int, req: CaseReq, db: Session = Depends(get_db)):
    s = db.get(EvalSet, sid)
    if not s:
        raise HTTPException(404, "测试集不存在")
    c = EvalCase(set_id=sid, question=req.question, ground_truth=req.ground_truth, tags=req.tags)
    db.add(c)
    db.commit()
    db.refresh(c)
    return {"id": c.id}


@router.post("/sets/{sid}/cases/import")
def import_cases(sid: int, req: ImportReq, db: Session = Depends(get_db)):
    n = 0
    for line in req.lines.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split("||", 1)
        q = parts[0].strip()
        gt = parts[1].strip() if len(parts) > 1 else ""
        if q:
            db.add(EvalCase(set_id=sid, question=q, ground_truth=gt))
            n += 1
    db.commit()
    return {"imported": n}


@router.delete("/cases/{cid}")
def delete_case(cid: int, db: Session = Depends(get_db)):
    c = db.get(EvalCase, cid)
    if c:
        db.delete(c)
        db.commit()
    return {"ok": True}


# ---------- runs ----------
def _run_eval_async(run_id: int):
    db = SessionLocal()
    try:
        run = db.get(EvalRun, run_id)
        eset = db.get(EvalSet, run.set_id)
        cases = list(eset.cases)
        kb_ids = [eset.kb_id] if eset.kb_id else []
        agg = {"faithfulness": [], "answer_relevancy": [], "context_precision": [], "context_recall": []}
        for i, case in enumerate(cases):
            try:
                # 1) 检索
                contexts = []
                if eset.chat_id:
                    answer, contexts = rf.chat_completion(eset.chat_id, case.question)
                else:
                    chunks = rf.retrieval(case.question, kb_ids) if kb_ids else []
                    contexts = [c.get("content", "") for c in chunks][:6]
                    ctx_txt = "\n---\n".join(contexts) or "（无检索结果）"
                    answer = llm.chat([{"role": "user", "content":
                                        RAG_PROMPT.format(contexts=ctx_txt, question=case.question)}])
                # 2) judge
                judge_txt = JUDGE_PROMPT.format(question=case.question,
                                                ground_truth=case.ground_truth or "（未提供）",
                                                contexts="\n---\n".join(contexts)[:6000] or "（无）",
                                                answer=answer[:3000])
                scores, raw = llm.chat_json([{"role": "user", "content": judge_txt}])
                vals = {}
                for k in agg:
                    v = scores.get(k)
                    try:
                        v = max(0.0, min(1.0, float(v)))
                    except (TypeError, ValueError):
                        v = None
                    vals[k] = v
                    if v is not None:
                        agg[k].append(v)
                res = EvalResult(run_id=run_id, case_id=case.id, answer=answer,
                                 contexts_json=contexts[:6], error="" if scores else ("judge解析失败: " + raw[:200]),
                                 **vals)
                db.add(res)
            except Exception as e:  # noqa
                db.add(EvalResult(run_id=run_id, case_id=case.id, error=str(e)[:500]))
            db.commit()
            run.config_json = dict(run.config_json or {}, progress="%d/%d" % (i + 1, len(cases)))
            db.commit()
        run.scores_json = {k: round(sum(v) / len(v), 4) for k, v in agg.items() if v}
        run.scores_json = dict(run.scores_json, cases=len(cases),
                               errors=db.query(EvalResult).filter(EvalResult.run_id == run_id,
                                                                  EvalResult.error != "").count())
        run.status = "done"
        run.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:  # noqa
        try:
            run = db.get(EvalRun, run_id)
            run.status = "failed"
            run.scores_json = {"error": str(e)[:500]}
            db.commit()
        except Exception:  # noqa
            db.rollback()
    finally:
        db.close()


@router.post("/sets/{sid}/runs")
def start_run(sid: int, db: Session = Depends(get_db)):
    s = db.get(EvalSet, sid)
    if not s:
        raise HTTPException(404, "测试集不存在")
    if not s.cases:
        raise HTTPException(400, "测试集为空，请先添加评测用例")
    # 配额闸门（软集成：billing 模块存在即生效）
    try:
        from modules import billing as billing_mod
        ok, reason = billing_mod.check_and_consume(db, s.note and "" or "", "eval_runs", 1, soft=True)
        if not ok:
            raise HTTPException(402, reason)
    except HTTPException:
        raise
    except Exception:  # noqa  billing 异常不阻塞评测
        pass
    run = EvalRun(set_id=sid, config_json={"model": llm.config.AI_MODEL,
                                           "mock_llm": llm.config.MOCK_LLM,
                                           "mock_ragflow": rf.mocked()})
    db.add(run)
    db.commit()
    db.refresh(run)
    threading.Thread(target=_run_eval_async, args=(run.id,), daemon=True).start()
    return {"run_id": run.id, "status": "running"}


@router.get("/runs")
def list_runs(set_id: int = 0, db: Session = Depends(get_db)):
    q = db.query(EvalRun)
    if set_id:
        q = q.filter(EvalRun.set_id == set_id)
    runs = q.order_by(EvalRun.started_at.desc()).limit(50).all()
    return [{"id": r.id, "set_id": r.set_id, "status": r.status, "scores": r.scores_json,
             "config": r.config_json, "started_at": r.started_at.isoformat() + "Z",
             "finished_at": (r.finished_at.isoformat() + "Z") if r.finished_at else None} for r in runs]


@router.get("/runs/{rid}")
def run_detail(rid: int, db: Session = Depends(get_db)):
    r = db.get(EvalRun, rid)
    if not r:
        raise HTTPException(404, "评测批次不存在")
    results = []
    for res in r.results:
        case = db.get(EvalCase, res.case_id)
        results.append({"id": res.id, "case_id": res.case_id,
                        "question": case.question if case else "",
                        "ground_truth": case.ground_truth if case else "",
                        "answer": res.answer, "contexts": res.contexts_json,
                        "faithfulness": res.faithfulness, "answer_relevancy": res.answer_relevancy,
                        "context_precision": res.context_precision, "context_recall": res.context_recall,
                        "error": res.error})
    return {"id": r.id, "set_id": r.set_id, "status": r.status, "scores": r.scores_json,
            "config": r.config_json, "results": results}


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db)):
    """看板聚合：每个测试集最近 N 次批次得分趋势。"""
    out = []
    for s in db.query(EvalSet).all():
        runs = db.query(EvalRun).filter(EvalRun.set_id == s.id, EvalRun.status == "done")\
            .order_by(EvalRun.started_at.asc()).limit(20).all()
        out.append({"set_id": s.id, "name": s.name,
                    "trend": [{"run_id": r.id, "at": r.started_at.isoformat() + "Z",
                               "scores": r.scores_json} for r in runs]})
    return out
