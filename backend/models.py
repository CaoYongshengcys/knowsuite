"""ORM models for all five KnowSuite modules."""
from datetime import datetime

from sqlalchemy import String, Text, Integer, Float, Boolean, DateTime, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base


def _now():
    return datetime.utcnow()


# ============ 1. 评测（RAGAS 风格） ============
class EvalSet(Base):
    __tablename__ = "eval_sets"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    kb_id: Mapped[str] = mapped_column(String(64), default="")     # RAGFlow dataset id
    chat_id: Mapped[str] = mapped_column(String(64), default="")   # RAGFlow chat assistant id（可空=用检索+本地LLM拼答）
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    cases: Mapped[list["EvalCase"]] = relationship(back_populates="set_", cascade="all, delete-orphan")


class EvalCase(Base):
    __tablename__ = "eval_cases"
    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("eval_sets.id"), index=True)
    question: Mapped[str] = mapped_column(Text)
    ground_truth: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(200), default="")
    set_: Mapped[EvalSet] = relationship(back_populates="cases")


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    set_id: Mapped[int] = mapped_column(ForeignKey("eval_sets.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running")   # running|done|failed
    config_json: Mapped[dict] = mapped_column(JSON, default=dict)
    scores_json: Mapped[dict] = mapped_column(JSON, default=dict)        # 汇总均值
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    results: Mapped[list["EvalResult"]] = relationship(back_populates="run", cascade="all, delete-orphan")


class EvalResult(Base):
    __tablename__ = "eval_results"
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("eval_runs.id"), index=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("eval_cases.id"))
    answer: Mapped[str] = mapped_column(Text, default="")
    contexts_json: Mapped[list] = mapped_column(JSON, default=list)
    faithfulness: Mapped[float | None] = mapped_column(Float, nullable=True)
    answer_relevancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_precision: Mapped[float | None] = mapped_column(Float, nullable=True)
    context_recall: Mapped[float | None] = mapped_column(Float, nullable=True)
    error: Mapped[str] = mapped_column(Text, default="")
    run: Mapped[EvalRun] = relationship(back_populates="results")


# ============ 2. 旧稿识别归并 / 版本治理 ============
class DocVersion(Base):
    __tablename__ = "doc_versions"
    id: Mapped[int] = mapped_column(primary_key=True)
    kb_id: Mapped[str] = mapped_column(String(64), index=True)
    ragflow_doc_id: Mapped[str] = mapped_column(String(64), default="")
    title: Mapped[str] = mapped_column(String(400))
    chain_id: Mapped[str] = mapped_column(String(40), index=True, default="")   # 同链共享
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("doc_versions.id"), nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, default=True)             # 现行稿
    text_excerpt: Mapped[str] = mapped_column(Text, default="")                 # 供对照 diff
    embedding_json: Mapped[list] = mapped_column(JSON, default=list)
    fingerprint: Mapped[str] = mapped_column(String(64), default="", index=True)  # sha256(全文) 完全重复秒判
    note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


class MergeLog(Base):
    __tablename__ = "merge_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    chain_id: Mapped[str] = mapped_column(String(40), index=True)
    action: Mapped[str] = mapped_column(String(20))     # merge|split|set_current
    from_doc: Mapped[int] = mapped_column(Integer, default=0)
    to_doc: Mapped[int] = mapped_column(Integer, default=0)
    operator: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============ 3. 订阅支付 ============
class Plan(Base):
    __tablename__ = "plans"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    price_cny: Mapped[float] = mapped_column(Float, default=0)
    period_days: Mapped[int] = mapped_column(Integer, default=30)
    quotas_json: Mapped[dict] = mapped_column(JSON, default=dict)   # {"upload_mb":2048,"video_min":60,"eval_runs":50}
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Order(Base):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_no: Mapped[str] = mapped_column(String(40), unique=True, index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    user_ref: Mapped[str] = mapped_column(String(120), index=True)   # 租户/用户标识（对接方自定）
    amount: Mapped[float] = mapped_column(Float, default=0)
    gateway: Mapped[str] = mapped_column(String(20), default="mock")  # mock|qrcode|alipay
    status: Mapped[str] = mapped_column(String(20), default="created")  # created|paid|cancelled|refunded
    pay_info: Mapped[str] = mapped_column(Text, default="")            # 支付链接/二维码内容/收款说明
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_ref: Mapped[str] = mapped_column(String(120), index=True)
    plan_id: Mapped[int] = mapped_column(ForeignKey("plans.id"))
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    end_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active|expired|cancelled


class UsageLog(Base):
    __tablename__ = "usage_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_ref: Mapped[str] = mapped_column(String(120), index=True)
    metric: Mapped[str] = mapped_column(String(40), index=True)   # upload_mb|video_min|eval_runs|api_calls
    amount: Mapped[float] = mapped_column(Float, default=0)
    day: Mapped[str] = mapped_column(String(10), index=True)      # YYYY-MM (按月配额)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============ 4. OEM 贴牌 ============
class Brand(Base):
    __tablename__ = "brands"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True, index=True)  # 门户路径 /portal/{key}/
    app_name: Mapped[str] = mapped_column(String(120), default="AI 知识库")
    logo_url: Mapped[str] = mapped_column(String(500), default="")
    primary_color: Mapped[str] = mapped_column(String(20), default="#2563eb")
    footer_text: Mapped[str] = mapped_column(String(300), default="")
    login_notice: Mapped[str] = mapped_column(Text, default="")
    custom_css: Mapped[str] = mapped_column(Text, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)


# ============ 5. 视频理解 ============
class VideoJob(Base):
    __tablename__ = "video_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    filename: Mapped[str] = mapped_column(String(400))
    stored_path: Mapped[str] = mapped_column(String(600), default="")
    size_mb: Mapped[float] = mapped_column(Float, default=0)
    kb_id: Mapped[str] = mapped_column(String(64), default="")
    status: Mapped[str] = mapped_column(String(20), default="uploaded")
    # uploaded|extracting|asr|captioning|composing|uploading|done|failed
    stage_info: Mapped[str] = mapped_column(Text, default="")
    duration_sec: Mapped[float] = mapped_column(Float, default=0)
    transcript_len: Mapped[int] = mapped_column(Integer, default=0)
    frames_count: Mapped[int] = mapped_column(Integer, default=0)
    md_path: Mapped[str] = mapped_column(String(600), default="")
    ragflow_doc_id: Mapped[str] = mapped_column(String(64), default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
