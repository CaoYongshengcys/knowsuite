"""模块 5：视频理解.

流水线：上传视频 → ffmpeg 抽音频(16k mono wav)+关键帧(定时采样) → ASR 转写
（适配器：OpenAI 兼容 /audio/transcriptions → 百炼 qwen-omni → mock 降级）
→ qwen-vl 逐帧描述 → 合成带时间戳的 Markdown 文档 → 上传 RAGFlow 知识库并解析。
产物 Markdown 结构：元信息 / 转写全文（分段） / 关键帧描述表，RAGFlow 按 naive/paper 模板均可分块。
"""
import base64
import os
import shutil
import subprocess
import threading
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from sqlalchemy.orm import Session

from db import get_db, SessionLocal
from models import VideoJob
import config
import llm
import ragflow_client as rf

router = APIRouter(prefix="/api/video", tags=["video"])

VIDEO_EXT = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v", ".flv", ".wmv", ".ts"}


def ffmpeg_available():
    return shutil.which("ffmpeg") is not None


def _run(cmd, timeout=1800):
    return subprocess.run(cmd, capture_output=True, timeout=timeout)


def _probe_duration(path):
    try:
        p = _run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
                  "-of", "default=noprint_wrappers=1:nokey=1", path], timeout=60)
        return float(p.stdout.decode().strip() or 0)
    except Exception:  # noqa
        return 0.0


def _extract_audio(video_path, wav_path):
    p = _run(["ffmpeg", "-y", "-i", video_path, "-vn", "-ac", "1", "-ar", "16000",
              "-c:a", "pcm_s16le", wav_path], timeout=3600)
    return p.returncode == 0 and os.path.exists(wav_path)


def _extract_frames(video_path, out_dir, duration):
    os.makedirs(out_dir, exist_ok=True)
    interval = max(5, config.VIDEO_FRAME_INTERVAL)
    p = _run(["ffmpeg", "-y", "-i", video_path,
              "-vf", "fps=1/%d,scale=640:-2" % interval,
              "-frames:v", str(config.VIDEO_MAX_FRAMES),
              os.path.join(out_dir, "frame_%03d.jpg")], timeout=1800)
    frames = sorted(f for f in os.listdir(out_dir) if f.endswith(".jpg")) if p.returncode == 0 else []
    return frames, interval


def _asr(wav_path):
    """ASR 适配器链：A) OpenAI兼容 transcriptions B) 百炼 qwen-omni C) mock。"""
    with open(wav_path, "rb") as f:
        wav = f.read()
    txt = llm.transcribe_audio_wav(wav)
    if txt:
        return txt, "openai_compatible:%s" % config.ASR_MODEL
    if config.ASR_OMNI_MODEL and not config.MOCK_LLM:
        txt = llm.transcribe_audio_omni(llm.b64e(wav[:20 * 1024 * 1024]))
        if txt:
            return txt, "omni:%s" % config.ASR_OMNI_MODEL
    return ("【MOCK 转写】未配置 ASR 后端。此处为演示文本：本次视频介绍了系统的整体架构、"
            "核心功能与使用方法。（配置 ASR_API_BASE/ASR_API_KEY 或 ASR_OMNI_MODEL 后为真实转写）"), "mock"


def _caption_frames(frame_dir, frames):
    out = []
    for i, fn in enumerate(frames):
        path = os.path.join(frame_dir, fn)
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode()
            cap = llm.vision_caption(b64, "用一句中文客观描述画面主要内容（若是PPT/图表请概括要点）。")
        except Exception as e:  # noqa
            cap = "[帧读取失败 %s]" % e
        out.append({"frame": fn, "caption": cap})
    return out


def _compose_markdown(job: VideoJob, transcript, asr_src, frame_caps, interval, duration):
    lines = ["# 视频转写与关键帧：%s" % job.filename, ""]
    lines += ["> 时长：约 %.0f 秒 ｜ ASR：%s ｜ 关键帧：%d 张（每 %d 秒）｜ 由 KnowSuite 视频理解模块生成"
              % (duration, asr_src, len(frame_caps), interval), ""]
    lines += ["## 一、语音转写全文", "", transcript or "（无语音内容）", ""]
    if frame_caps:
        lines += ["## 二、关键帧画面描述", "", "| 时间点(约) | 画面描述 |", "|---|---|"]
        for i, fc in enumerate(frame_caps):
            ts = i * interval
            lines.append("| %02d:%02d | %s |" % (ts // 60, ts % 60, fc["caption"].replace("|", "／").replace("\n", " ")))
        lines.append("")
    return "\n".join(lines)


def _process_job(job_id: int):
    db = SessionLocal()
    try:
        job = db.get(VideoJob, job_id)
        work_dir = os.path.join(config.DATA_DIR, "videos", "job_%d" % job_id)
        os.makedirs(work_dir, exist_ok=True)
        job.status, job.stage_info = "extracting", "ffmpeg 抽取音频与关键帧"
        db.commit()

        duration = 0.0
        frames, interval, transcript, asr_src, caps = [], config.VIDEO_FRAME_INTERVAL, "", "mock", []
        if ffmpeg_available() and os.path.exists(job.stored_path):
            duration = _probe_duration(job.stored_path)
            job.duration_sec = duration
            wav = os.path.join(work_dir, "audio.wav")
            if _extract_audio(job.stored_path, wav):
                job.status, job.stage_info = "asr", "语音转写中"
                db.commit()
                transcript, asr_src = _asr(wav)
            fdir = os.path.join(work_dir, "frames")
            frames, interval = _extract_frames(job.stored_path, fdir, duration)
            if frames:
                job.status, job.stage_info = "captioning", "视觉模型描述 %d 张关键帧" % len(frames)
                db.commit()
                caps = _caption_frames(fdir, frames)
        else:
            # 无 ffmpeg 或 mock：给出演示产物，保证流程可跑通
            duration = job.duration_sec or 120
            transcript, asr_src = ("【MOCK 转写】ffmpeg 不可用或未配置 ASR。演示文本："
                                   "本视频讲解了平台的核心功能与操作流程。"), "mock(ffmpeg不可用)"
            caps = [{"frame": "mock_frame_%02d" % i, "caption": llm.vision_caption("", "描述画面")}
                    for i in range(3)]

        job.status, job.stage_info = "composing", "合成 Markdown 文档"
        db.commit()
        md = _compose_markdown(job, transcript, asr_src, caps, interval, duration)
        md_path = os.path.join(config.DATA_DIR, "video_md", "video_%d.md" % job_id)
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md)
        job.md_path, job.transcript_len, job.frames_count = md_path, len(transcript), len(caps)

        if job.kb_id:
            job.status, job.stage_info = "uploading", "上传 RAGFlow 知识库并解析"
            db.commit()
            docs = rf.upload_documents(job.kb_id, [(os.path.basename(md_path), md.encode("utf-8"))])
            if docs:
                doc_id = docs[0].get("id", "")
                job.ragflow_doc_id = doc_id
                try:
                    rf.parse_documents(job.kb_id, [doc_id])
                except Exception:  # noqa
                    pass
        job.status, job.stage_info = "done", "完成"
        job.finished_at = datetime.utcnow()
        db.commit()
    except Exception as e:  # noqa
        try:
            job = db.get(VideoJob, job_id)
            job.status, job.error = "failed", str(e)[:800]
            db.commit()
        except Exception:  # noqa
            db.rollback()
    finally:
        db.close()


def _brief(j: VideoJob):
    return {"id": j.id, "filename": j.filename, "size_mb": round(j.size_mb, 2),
            "kb_id": j.kb_id, "status": j.status, "stage_info": j.stage_info,
            "duration_sec": j.duration_sec, "transcript_len": j.transcript_len,
            "frames_count": j.frames_count, "ragflow_doc_id": j.ragflow_doc_id,
            "error": j.error, "created_at": j.created_at.isoformat() + "Z",
            "finished_at": (j.finished_at.isoformat() + "Z") if j.finished_at else None}


@router.post("/jobs")
async def create_job(file: UploadFile = File(...), kb_id: str = Form(default=""),
                     user_ref: str = Form(default=""), db: Session = Depends(get_db)):
    name = file.filename or "video"
    ext = os.path.splitext(name)[1].lower()
    if ext not in VIDEO_EXT:
        raise HTTPException(400, "仅支持视频文件：%s" % " ".join(sorted(VIDEO_EXT)))
    data = await file.read()
    size_mb = len(data) / 1048576
    # 配额闸门（视频分钟数按文件大小粗略折算：100MB≈1分钟，可在部署时调整）
    if user_ref:
        try:
            from modules import billing
            ok, reason = billing.check_and_consume(db, user_ref, "video_min", max(1, size_mb // 100))
            if not ok:
                raise HTTPException(402, reason)
        except HTTPException:
            raise
        except Exception:  # noqa
            pass
    job = VideoJob(filename=name, size_mb=size_mb, kb_id=kb_id)
    db.add(job)
    db.commit()
    db.refresh(job)
    stored = os.path.join(config.DATA_DIR, "videos", "job_%d_%s" % (job.id, name.replace("/", "_")))
    os.makedirs(os.path.dirname(stored), exist_ok=True)
    with open(stored, "wb") as f:
        f.write(data)
    job.stored_path = stored
    db.commit()
    threading.Thread(target=_process_job, args=(job.id,), daemon=True).start()
    return _brief(job)


@router.get("/jobs")
def list_jobs(db: Session = Depends(get_db)):
    return [_brief(j) for j in db.query(VideoJob).order_by(VideoJob.created_at.desc()).limit(50).all()]


@router.get("/jobs/{jid}")
def job_detail(jid: int, db: Session = Depends(get_db)):
    j = db.get(VideoJob, jid)
    if not j:
        raise HTTPException(404, "任务不存在")
    return _brief(j)


@router.get("/jobs/{jid}/markdown")
def job_markdown(jid: int, db: Session = Depends(get_db)):
    j = db.get(VideoJob, jid)
    if not j or not j.md_path or not os.path.exists(j.md_path):
        raise HTTPException(404, "Markdown 尚未生成")
    with open(j.md_path, "r", encoding="utf-8") as f:
        return {"filename": os.path.basename(j.md_path), "markdown": f.read()}
