# -*- coding: utf-8 -*-
"""KnowSuite 冒烟测试：MOCK_RAGFLOW=1 MOCK_LLM=1 下走通五大模块全流程。

运行：python tests/smoke_test.py
"""
import io
import os
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="ks_test_")
os.environ["DATA_DIR"] = TMP
os.environ["MOCK_RAGFLOW"] = "1"
os.environ["MOCK_LLM"] = "1"
os.environ["RAGFLOW_API_KEY"] = ""
os.environ["AI_API_KEY"] = ""
os.environ["ADMIN_TOKEN"] = "test-admin"
os.environ["PAYMENT_GATEWAY"] = "mock"

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
os.chdir(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))

from fastapi.testclient import TestClient  # noqa: E402
import app as app_module  # noqa: E402

client = TestClient(app_module.app)
ADMIN = {"X-Admin-Token": "test-admin"}
RESULTS = []


def check(name, cond, extra=""):
    RESULTS.append((name, bool(cond), extra))
    print(("PASS " if cond else "FAIL ") + name + ((" | " + str(extra)[:200]) if (extra and not cond) else ""))


# ---------- 0. health ----------
r = client.get("/api/health")
check("A1 health", r.status_code == 200 and r.json()["ok"] and r.json()["ragflow"]["mocked"], r.text[:150])
r = client.get("/api/datasets")
check("A2 datasets mock", r.status_code == 200 and isinstance(r.json(), list))
r = client.get("/")
check("A3 console page", r.status_code == 200 and "KnowSuite" in r.text)

# ---------- 1. 评测看板 ----------
r = client.post("/api/eval/sets", json={"name": "冒烟测试集", "kb_id": "mock-kb-1"})
sid = r.json().get("id")
check("B1 create eval set", r.status_code == 200 and sid, r.text[:150])
r = client.post(f"/api/eval/sets/{sid}/cases", json={"question": "混合储能的作用是什么？", "ground_truth": "平抑波动、提供惯量支撑"})
check("B2 add case", r.status_code == 200)
r = client.post(f"/api/eval/sets/{sid}/cases/import", json={"lines": "问题一||答案一\n问题二\n\n问题三||答案三"})
check("B3 import cases", r.status_code == 200 and r.json()["imported"] == 3, r.text[:150])
r = client.post(f"/api/eval/sets/{sid}/runs")
run_id = r.json().get("run_id")
check("B4 start run", r.status_code == 200 and run_id, r.text[:150])
import time
for _ in range(60):
    time.sleep(0.5)
    r = client.get(f"/api/eval/runs/{run_id}")
    if r.json()["status"] in ("done", "failed"):
        break
d = r.json()
check("B5 run done", d["status"] == "done", d.get("scores"))
sc = d.get("scores") or {}
check("B6 scores present", sc.get("faithfulness") is not None and sc.get("cases") == 4, sc)
check("B7 results rows", len(d.get("results", [])) == 4)
r = client.get("/api/eval/dashboard")
check("B8 dashboard", r.status_code == 200 and isinstance(r.json(), list))

# ---------- 2. 版本治理 ----------
text_v1 = "本文提出一种混合储能协调控制方法。" * 20
r = client.post("/api/versions/check", json={"kb_id": "mock-kb-1", "title": "储能论文v1", "text": text_v1})
check("C1 check empty kb -> none", r.status_code == 200 and r.json()["level"] == "none", r.text[:150])
r = client.post("/api/versions/register", json={"kb_id": "mock-kb-1", "title": "储能论文v1", "text": text_v1,
                                                "ragflow_doc_id": "doc-1", "created_by": "stu"})
d1 = r.json().get("id")
check("C2 register v1", r.status_code == 200 and d1, r.text[:150])
r = client.post("/api/versions/check", json={"kb_id": "mock-kb-1", "title": "储能论文v1", "text": text_v1})
check("C3 exact duplicate detected", r.json()["level"] == "duplicate", r.json().get("level"))
text_v2 = text_v1 + "新增第三章实验对比。" * 5
r = client.post("/api/versions/check", json={"kb_id": "mock-kb-1", "title": "储能论文v2", "text": text_v2})
check("C4 similar detected strong/weak", r.json()["level"] in ("strong", "weak"), r.json().get("level"))
r = client.post("/api/versions/register", json={"kb_id": "mock-kb-1", "title": "储能论文v2", "text": text_v2,
                                                "parent_id": d1, "created_by": "stu"})
d2 = r.json().get("id")
chain = r.json().get("chain_id")
check("C5 register v2 into chain", r.status_code == 200 and d2 and chain, r.text[:150])
r = client.get(f"/api/versions/chains/{chain}")
vers = r.json().get("versions", [])
cur = [v for v in vers if v["is_current"]]
check("C6 old version auto-historized", len(vers) == 2 and len(cur) == 1 and cur[0]["id"] == d2, vers)
r = client.get("/api/versions/current?kb_id=mock-kb-1")
check("C7 current list", any(v["id"] == d2 for v in r.json()) and not any(v["id"] == d1 for v in r.json()))
r = client.get(f"/api/versions/compare?a={d1}&b={d2}")
check("C8 compare diff", r.status_code == 200 and isinstance(r.json().get("unified_diff"), list))
r = client.post("/api/versions/merge", json={"chain_id": chain, "keep_id": d1, "operator": "teacher"})
check("C9 merge keep v1", r.status_code == 200 and r.json()["current"]["id"] == d1, r.text[:150])
r = client.post("/api/versions/split", json={"doc_id": d2, "operator": "teacher"})
check("C10 split", r.status_code == 200 and r.json()["doc"]["chain_id"] != chain, r.text[:150])

# ---------- 3. 订阅支付 ----------
r = client.get("/api/billing/plans")
plans = r.json()
check("D1 plans seeded", r.status_code == 200 and len(plans) >= 4 and any(p["code"] == "pro" for p in plans))
r = client.post("/api/billing/orders", json={"plan_code": "pro", "user_ref": "tenant-a"})
od = r.json()
check("D2 create order", r.status_code == 200 and od.get("order_no", "").startswith("KS"), r.text[:150])
no = od["order_no"]
r = client.post(f"/api/billing/orders/{no}/confirm")
check("D3 confirm without admin -> 403", r.status_code == 403)
r = client.post(f"/api/billing/orders/{no}/confirm", headers=ADMIN)
check("D4 confirm order", r.status_code == 200 and r.json()["ok"], r.text[:150])
r = client.get("/api/billing/subscriptions/tenant-a")
sub = r.json()
check("D5 subscription active", sub["plan"]["code"] == "pro" and sub["subscription"]["status"] == "active", sub)
r = client.get("/api/billing/quota?user_ref=tenant-a&metric=video_min&amount=100")
check("D6 quota allowed", r.json()["allowed"] is True, r.text[:150])
r = client.get("/api/billing/quota?user_ref=free-user&metric=video_min&amount=99999")
check("D7 free quota blocked", r.json()["allowed"] is False, r.text[:150])
r = client.post("/api/billing/usage", json={"user_ref": "tenant-a", "metric": "upload_mb", "amount": 50}, headers=ADMIN)
check("D8 usage report", r.status_code == 200)
r = client.get("/api/billing/orders", headers=ADMIN)
check("D9 order list admin", r.status_code == 200 and len(r.json()) >= 1)

# ---------- 4. OEM ----------
r = client.post("/api/oem/brands", json={"key": "acme", "app_name": "Acme 知识库",
                                         "primary_color": "#0ea5e9", "footer_text": "Acme Inc."})
check("E1 create brand without admin -> 403", r.status_code == 403)
r = client.post("/api/oem/brands", headers=ADMIN, json={"key": "acme", "app_name": "Acme 知识库",
                                                        "primary_color": "#0ea5e9", "footer_text": "Acme Inc.",
                                                        "login_notice": "内部系统，请勿外传"})
check("E2 create brand", r.status_code == 200 and r.json()["key"] == "acme", r.text[:150])
r = client.get("/api/oem/brands/acme/public")
check("E3 public brand", r.status_code == 200 and r.json()["app_name"] == "Acme 知识库")
r = client.get("/portal/acme")
check("E4 portal html", r.status_code == 200 and "Acme 知识库" in r.text and "#0ea5e9" in r.text and "iframe" in r.text)
r = client.put("/api/oem/brands/acme", headers=ADMIN, json={"key": "acme", "app_name": "Acme 知识平台",
                                                            "primary_color": "#16a34a", "is_active": True})
check("E5 update brand", r.status_code == 200 and r.json()["app_name"] == "Acme 知识平台", r.text[:150])
r = client.get("/portal/acme")
check("E6 portal reflects update", "Acme 知识平台" in r.text)
r = client.get("/api/oem/brands", headers=ADMIN)
check("E7 list brands", r.status_code == 200 and len(r.json()) == 1)

# ---------- 5. 视频理解（mock 流水线，无需 ffmpeg） ----------
fake = io.BytesIO(b"\x00\x01fake-video-bytes" * 100)
r = client.post("/api/video/jobs", files={"file": ("demo.mp4", fake, "video/mp4")},
                data={"kb_id": "mock-kb-1", "user_ref": ""})
jid = r.json().get("id")
check("F1 create video job", r.status_code == 200 and jid, r.text[:150])
for _ in range(60):
    time.sleep(0.5)
    r = client.get(f"/api/video/jobs/{jid}")
    if r.json()["status"] in ("done", "failed"):
        break
d = r.json()
check("F2 job done", d["status"] == "done", d.get("error") or d.get("status"))
check("F3 ragflow doc linked", d["ragflow_doc_id"] != "", d)
r = client.get(f"/api/video/jobs/{jid}/markdown")
md = r.json().get("markdown", "")
check("F4 markdown composed", "语音转写" in md and "关键帧" in md and "demo.mp4" in md, md[:150])
r = client.post("/api/video/jobs", files={"file": ("note.txt", io.BytesIO(b"hi"), "text/plain")}, data={})
check("F5 non-video rejected", r.status_code == 400, r.status_code)

# ---------- summary ----------
fails = [x for x in RESULTS if not x[1]]
print("\n==== KNOWSUITE SMOKE: %d/%d passed ====" % (len(RESULTS) - len(fails), len(RESULTS)))
if fails:
    for name, _, extra in fails:
        print("FAILED:", name, extra)
    sys.exit(1)
print("ALL GREEN")
