"""模块 3：订阅支付.

套餐(Plan) → 订单(Order) → 支付网关抽象(mock/qrcode/alipay占位) → 订阅(Subscription) → 配额闸门(UsageLog)。
- mock: 下单即返回"待确认"，管理员调 confirm 完成支付（联调用）
- qrcode: 返回收款码图片 URL + 订单号，用户扫码转账后管理员人工 confirm（小微团队现实方案）
- alipay: 预留网关接口（需商户资质后实现当面付/电脑网站支付）
配额按自然月计量（UsageLog.day=YYYY-MM），未订阅用户享受 free 套餐额度。
"""
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Plan, Order, Subscription, UsageLog
from modules import require_admin, month_key
import config

router = APIRouter(prefix="/api/billing", tags=["billing"])

DEFAULT_PLANS = [
    {"code": "free", "name": "免费版", "price_cny": 0, "period_days": 36500,
     "quotas_json": {"upload_mb": 200, "video_min": 10, "eval_runs": 5, "api_calls": 500}},
    {"code": "basic", "name": "基础版", "price_cny": 99, "period_days": 30,
     "quotas_json": {"upload_mb": 5120, "video_min": 120, "eval_runs": 100, "api_calls": 20000}},
    {"code": "pro", "name": "专业版", "price_cny": 399, "period_days": 30,
     "quotas_json": {"upload_mb": 51200, "video_min": 1200, "eval_runs": 1000, "api_calls": 200000}},
    {"code": "enterprise", "name": "企业版（含OEM贴牌）", "price_cny": 1999, "period_days": 30,
     "quotas_json": {"upload_mb": 512000, "video_min": 6000, "eval_runs": -1, "api_calls": -1, "oem": 1}},
]


def seed_plans(db: Session):
    if db.query(Plan).count() == 0:
        for p in DEFAULT_PLANS:
            db.add(Plan(**p))
        db.commit()


# ---------- schemas ----------
class OrderReq(BaseModel):
    plan_code: str
    user_ref: str
    gateway: str = ""   # 空=用全局 PAYMENT_GATEWAY


class UsageReq(BaseModel):
    user_ref: str
    metric: str
    amount: float = 1


# ---------- helpers (供其他模块调用) ----------
def get_active_sub(db: Session, user_ref: str):
    now = datetime.utcnow()
    sub = db.query(Subscription).filter(Subscription.user_ref == user_ref,
                                        Subscription.status == "active",
                                        Subscription.end_at > now)\
        .order_by(Subscription.end_at.desc()).first()
    return sub


def get_effective_plan(db: Session, user_ref: str):
    sub = get_active_sub(db, user_ref)
    if sub:
        return db.get(Plan, sub.plan_id), sub
    return db.query(Plan).filter_by(code="free").first(), None


def usage_of(db: Session, user_ref: str, metric: str):
    mk = month_key()
    rows = db.query(UsageLog).filter(UsageLog.user_ref == user_ref,
                                     UsageLog.metric == metric,
                                     UsageLog.day == mk).all()
    return sum(r.amount for r in rows)


def check_and_consume(db: Session, user_ref: str, metric: str, amount: float = 1, soft: bool = False):
    """配额闸门：返回 (ok, reason)。soft=True 时 user_ref 为空/无免费套餐则放行。"""
    if not user_ref:
        return (True, "") if soft else (False, "缺少 user_ref")
    plan, sub = get_effective_plan(db, user_ref)
    if not plan:
        return True, ""   # 未初始化套餐体系时不拦
    quota = (plan.quotas_json or {}).get(metric)
    if quota is None or quota == -1:
        return True, ""   # 不限量
    used = usage_of(db, user_ref, metric)
    if used + amount > quota:
        return False, "本月 %s 配额已用尽（%s/%s），请升级套餐或下月再试" % (metric, used, quota)
    db.add(UsageLog(user_ref=user_ref, metric=metric, amount=amount, day=month_key()))
    db.commit()
    return True, ""


# ---------- routes ----------
@router.get("/plans")
def plans(db: Session = Depends(get_db)):
    seed_plans(db)
    return [{"code": p.code, "name": p.name, "price_cny": p.price_cny,
             "period_days": p.period_days, "quotas": p.quotas_json,
             "is_active": p.is_active}
            for p in db.query(Plan).filter(Plan.is_active.is_(True)).all()]


@router.post("/orders")
def create_order(req: OrderReq, db: Session = Depends(get_db)):
    seed_plans(db)
    plan = db.query(Plan).filter_by(code=req.plan_code).first()
    if not plan:
        raise HTTPException(404, "套餐不存在")
    gw = (req.gateway or config.PAYMENT_GATEWAY or "mock").lower()
    order_no = "KS%s%s" % (datetime.utcnow().strftime("%Y%m%d%H%M%S"), secrets.token_hex(3).upper())
    if gw == "mock":
        pay_info = "MOCK 网关：调用 POST /api/billing/orders/%s/confirm（携带 X-Admin-Token）完成支付" % order_no
    elif gw == "qrcode":
        pay_info = ("扫码收款：请向财务二维码转账 ¥%.2f，备注订单号 %s；"
                    "到账后管理员在控制台点击「确认到账」。") % (plan.price_cny, order_no)
    elif gw == "alipay":
        pay_info = "支付宝网关为占位实现：需商户资质后接入当面付/电脑网站支付（见 README）。"
    else:
        raise HTTPException(400, "不支持的支付网关: %s" % gw)
    o = Order(order_no=order_no, plan_id=plan.id, user_ref=req.user_ref,
              amount=plan.price_cny, gateway=gw, status="created", pay_info=pay_info)
    db.add(o)
    db.commit()
    return {"order_no": o.order_no, "amount": o.amount, "gateway": gw,
            "status": o.status, "pay_info": pay_info}


def _activate_subscription(db: Session, order: Order):
    plan = db.get(Plan, order.plan_id)
    now = datetime.utcnow()
    existing = get_active_sub(db, order.user_ref)
    if existing and existing.plan_id == order.plan_id:
        existing.end_at = existing.end_at + timedelta(days=plan.period_days)   # 续费顺延
        sub = existing
    else:
        base = existing.end_at if (existing and existing.end_at > now) else now
        sub = Subscription(user_ref=order.user_ref, plan_id=plan.id, order_id=order.id,
                           start_at=now, end_at=base + timedelta(days=plan.period_days))
        db.add(sub)
    order.status = "paid"
    order.paid_at = now
    db.commit()
    return sub


@router.post("/orders/{order_no}/confirm")
def confirm_order(order_no: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    """管理员确认到账（mock/qrcode 网关）；真实网关应替换为异步回调+验签。"""
    o = db.query(Order).filter_by(order_no=order_no).first()
    if not o:
        raise HTTPException(404, "订单不存在")
    if o.status == "paid":
        return {"ok": True, "msg": "订单已是支付状态", "order_no": order_no}
    sub = _activate_subscription(db, o)
    return {"ok": True, "order_no": order_no,
            "subscription": {"plan_id": sub.plan_id, "end_at": sub.end_at.isoformat() + "Z"}}


@router.post("/orders/{order_no}/cancel")
def cancel_order(order_no: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    o = db.query(Order).filter_by(order_no=order_no).first()
    if not o:
        raise HTTPException(404, "订单不存在")
    if o.status == "paid":
        raise HTTPException(400, "已支付订单请走退款流程（当前版本仅标记 refunded，需人工处理）")
    o.status = "cancelled"
    db.commit()
    return {"ok": True}


@router.get("/orders")
def list_orders(user_ref: str = "", _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    q = db.query(Order)
    if user_ref:
        q = q.filter(Order.user_ref == user_ref)
    orders = q.order_by(Order.created_at.desc()).limit(100).all()
    return [{"order_no": o.order_no, "user_ref": o.user_ref, "amount": o.amount,
             "gateway": o.gateway, "status": o.status, "pay_info": o.pay_info,
             "plan": (db.get(Plan, o.plan_id).name if db.get(Plan, o.plan_id) else ""),
             "created_at": o.created_at.isoformat() + "Z",
             "paid_at": (o.paid_at.isoformat() + "Z") if o.paid_at else None} for o in orders]


@router.get("/subscriptions/{user_ref}")
def my_subscription(user_ref: str, db: Session = Depends(get_db)):
    seed_plans(db)
    plan, sub = get_effective_plan(db, user_ref)
    quotas = dict(plan.quotas_json or {}) if plan else {}
    used = {m: usage_of(db, user_ref, m) for m in quotas if quotas[m] != 1 or True}
    remaining = {}
    for m, q in quotas.items():
        remaining[m] = -1 if q == -1 else max(0, q - used.get(m, 0))
    return {"user_ref": user_ref,
            "plan": {"code": plan.code, "name": plan.name} if plan else None,
            "subscription": {"start_at": sub.start_at.isoformat() + "Z",
                             "end_at": sub.end_at.isoformat() + "Z",
                             "status": sub.status} if sub else None,
            "quotas": quotas, "used": used, "remaining": remaining}


@router.post("/usage")
def report_usage(req: UsageReq, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    db.add(UsageLog(user_ref=req.user_ref, metric=req.metric,
                    amount=req.amount, day=month_key()))
    db.commit()
    return {"ok": True}


@router.get("/quota")
def quota_gate(user_ref: str, metric: str, amount: float = 1, db: Session = Depends(get_db)):
    """其他系统前置校验用：GET /api/billing/quota?user_ref=x&metric=video_min&amount=30"""
    ok, reason = check_and_consume(db, user_ref, metric, amount, soft=True)
    return {"allowed": ok, "reason": reason}
