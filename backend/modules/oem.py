"""模块 4：OEM 贴牌.

品牌配置 CRUD（管理端）+ 品牌门户：
- /portal/{key}          品牌外壳页（带 logo/配色/页脚，内嵌 RAGFlow 界面 iframe）
- /api/oem/brands/{key}/public  前端可安全读取的品牌配置
- /proxy/{key}/{path}    实验性直连代理：转发 RAGFlow 页面并注入品牌 <title>/logo/CSS
Apache-2.0 允许去品牌再分发；本模块实现"运行时换肤"，无需改动 RAGFlow 代码。
"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from db import get_db
from models import Brand
from modules import require_admin
import config

router = APIRouter(tags=["oem"])

PORTAL_TMPL = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__APP_NAME__</title>
<link rel="icon" href="__LOGO__">
<style>
 :root{--brand:__PRIMARY__}
 *{box-sizing:border-box}body{margin:0;font-family:-apple-system,"PingFang SC","Microsoft YaHei",sans-serif}
 .topbar{height:52px;background:var(--brand);color:#fff;display:flex;align-items:center;gap:10px;padding:0 18px}
 .topbar img{height:30px}.topbar b{font-size:16px}
 .notice{background:#fffbe6;border-bottom:1px solid #ffe58f;padding:6px 18px;font-size:13px;color:#614700}
 iframe{width:100%;height:calc(100vh - 52px);border:0}
 .footer{position:fixed;bottom:0;right:0;background:rgba(255,255,255,.85);font-size:11px;color:#94a3b8;padding:2px 8px;border-radius:6px 0 0 0}
 __CUSTOM_CSS__
</style></head><body>
<div class="topbar">__LOGO_IMG__<b>__APP_NAME__</b></div>
__NOTICE__
<iframe src="__INNER__"></iframe>
<div class="footer">__FOOTER__</div>
</body></html>"""


class BrandReq(BaseModel):
    key: str
    app_name: str = "AI 知识库"
    logo_url: str = ""
    primary_color: str = "#2563eb"
    footer_text: str = ""
    login_notice: str = ""
    custom_css: str = ""
    is_active: bool = True


def _brief(b: Brand, public=False):
    d = {"key": b.key, "app_name": b.app_name, "logo_url": b.logo_url,
         "primary_color": b.primary_color, "is_active": b.is_active}
    if not public:
        d.update({"footer_text": b.footer_text, "login_notice": b.login_notice,
                  "custom_css": b.custom_css, "created_at": b.created_at.isoformat() + "Z"})
    return d


# ---------- admin CRUD ----------
@router.get("/api/oem/brands")
def list_brands(_: bool = Depends(require_admin), db: Session = Depends(get_db)):
    return [_brief(b) for b in db.query(Brand).order_by(Brand.created_at.desc()).all()]


@router.post("/api/oem/brands")
def create_brand(req: BrandReq, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(Brand).filter_by(key=req.key).first():
        raise HTTPException(400, "品牌 key 已存在")
    b = Brand(**req.model_dump())
    db.add(b)
    db.commit()
    db.refresh(b)
    return _brief(b)


@router.put("/api/oem/brands/{key}")
def update_brand(key: str, req: BrandReq, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.query(Brand).filter_by(key=key).first()
    if not b:
        raise HTTPException(404, "品牌不存在")
    for k, v in req.model_dump(exclude={"key"}).items():
        setattr(b, k, v)
    db.commit()
    return _brief(b)


@router.delete("/api/oem/brands/{key}")
def delete_brand(key: str, _: bool = Depends(require_admin), db: Session = Depends(get_db)):
    b = db.query(Brand).filter_by(key=key).first()
    if b:
        db.delete(b)
        db.commit()
    return {"ok": True}


@router.get("/api/oem/brands/{key}/public")
def public_brand(key: str, db: Session = Depends(get_db)):
    b = db.query(Brand).filter_by(key=key).first()
    if not b or not b.is_active:
        raise HTTPException(404, "品牌不存在或已停用")
    return _brief(b, public=True)


# ---------- 品牌门户（iframe 外壳，稳定可靠） ----------
@router.get("/portal/{key}", response_class=HTMLResponse)
def portal(key: str, db: Session = Depends(get_db)):
    b = db.query(Brand).filter_by(key=key, is_active=True).first()
    if not b:
        raise HTTPException(404, "品牌不存在或已停用")
    notice = ('<div class="notice">%s</div>' % b.login_notice) if b.login_notice else ""
    logo_img = ('<img src="%s" alt="logo">' % b.logo_url) if b.logo_url else "<span>📚</span>"
    html = (PORTAL_TMPL
            .replace("__APP_NAME__", b.app_name)
            .replace("__LOGO_IMG__", logo_img)
            .replace("__LOGO__", b.logo_url or "data:,")
            .replace("__PRIMARY__", b.primary_color)
            .replace("__NOTICE__", notice)
            .replace("__INNER__", config.RAGFLOW_WEB + "/")
            .replace("__FOOTER__", b.footer_text or b.app_name)
            .replace("__CUSTOM_CSS__", b.custom_css or ""))
    return HTMLResponse(html)


# ---------- 实验性直连代理（注入品牌到 RAGFlow 原生页面） ----------
@router.api_route("/proxy/{key}/{path:path}", methods=["GET"])
async def inject_proxy(key: str, path: str, request: Request, db: Session = Depends(get_db)):
    b = db.query(Brand).filter_by(key=key, is_active=True).first()
    if not b:
        raise HTTPException(404, "品牌不存在或已停用")
    target = "%s/%s" % (config.RAGFLOW_WEB, path)
    if request.url.query:
        target += "?" + request.url.query
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as client:
            r = await client.get(target)
    except Exception as e:  # noqa
        raise HTTPException(502, "无法连接 RAGFlow: %s" % e)
    ctype = r.headers.get("content-type", "")
    if "text/html" in ctype:
        html = r.text
        inject = (
            "<style>:root{--primary-color:%s !important;--ant-primary-color:%s !important}"
            "body{--brand:%s}</style>"
            "<script>window.__OEM__=%s;document.addEventListener('DOMContentLoaded',function(){"
            "document.title=%s;var l=document.querySelector('link[rel~=icon]');"
            "if(l&&%s)l.href=%s;});</script>"
        ) % (b.primary_color, b.primary_color, b.primary_color,
             '{"appName":"%s"}' % b.app_name.replace('"', "'"),
             '"%s"' % b.app_name.replace('"', "'"),
             "true" if b.logo_url else "false",
             '"%s"' % b.logo_url)
        if "</head>" in html:
            html = html.replace("</head>", inject + "</head>", 1)
        else:
            html = inject + html
        return HTMLResponse(html, status_code=r.status_code)
    return Response(content=r.content, status_code=r.status_code,
                    media_type=ctype or None,
                    headers={k: v for k, v in r.headers.items()
                             if k.lower() not in ("content-encoding", "content-length", "transfer-encoding")})
