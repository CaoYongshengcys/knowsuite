# -*- coding: utf-8 -*-
"""Seed KnowSuite demo data for marketing screenshots (mock mode)."""
import io
import time

import httpx

B = "http://127.0.0.1:8100"
ADMIN = {"X-Admin-Token": "demo-admin"}
c = httpx.Client(timeout=60)

# wait for server
for i in range(40):
    try:
        if c.get(B + "/api/health").status_code == 200:
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise SystemExit("server not up")
print("server up")

# ---- 评测：测试集 + 用例 + 跑批 ----
s = c.post(B + "/api/eval/sets", json={"name": "储能论文知识库 QA 集", "kb_id": "mock-kb-1",
                                       "note": "混合储能/宽频振荡领域 40 问"}).json()
sid = s["id"]
cases = [
    ("混合储能系统中超级电容的作用是什么？", "平抑功率高频波动，延长电池寿命"),
    ("论文提出的改进粒子群算法收敛性如何？", "在标准测试函数上收敛速度提升约30%"),
    ("宽频振荡的模态参数辨识方法有哪些？", "基于量测的在线辨识与基于模型的离线辨识两大类"),
    ("实验部分的基线对比是否公平充分？", "对比了PSO、GA与 Proposed 方法，同一参数预算"),
    ("数据集规模与来源是什么？", "IEEE 33节点系统仿真 + 现场实测录波数据"),
    ("创新点与现有文献的区别？", "将物理约束嵌入推断网络，区别于纯数据驱动方法"),
]
for q, gt in cases:
    c.post(B + f"/api/eval/sets/{sid}/cases", json={"question": q, "ground_truth": gt})
r = c.post(B + f"/api/eval/sets/{sid}/runs").json()
run_id = r["run_id"]
for _ in range(120):
    time.sleep(0.5)
    st = c.get(B + f"/api/eval/runs/{run_id}").json()
    if st["status"] in ("done", "failed"):
        break
print("eval run:", st["status"], st.get("scores"))
# 再来一批历史批次让趋势图有数据
for extra in range(2):
    rr = c.post(B + f"/api/eval/sets/{sid}/runs").json()
    for _ in range(120):
        time.sleep(0.3)
        st2 = c.get(B + f"/api/eval/runs/{rr['run_id']}").json()
        if st2["status"] in ("done", "failed"):
            break
print("history runs done")

# ---- 版本治理：一条 3 版本链 ----
base = "本文提出一种物理引导的混合推断框架用于重叠宽频振荡模态辨识。" * 8
v1 = c.post(B + "/api/versions/register", json={"kb_id": "mock-kb-1", "title": "宽频振荡辨识论文 v1.0",
                                                "text": base, "ragflow_doc_id": "doc-a1b2", "created_by": "李同学"}).json()
v2 = c.post(B + "/api/versions/register", json={"kb_id": "mock-kb-1", "title": "宽频振荡辨识论文 v1.1（补实验）",
                                                "text": base + "新增第三章对比实验与消融分析。" * 3,
                                                "parent_id": v1["id"], "ragflow_doc_id": "doc-c3d4", "created_by": "李同学"}).json()
v3 = c.post(B + "/api/versions/register", json={"kb_id": "mock-kb-1", "title": "宽频振荡辨识论文 v2.0（大修稿）",
                                                "text": base + "重写引言，新增第五章工程验证。" * 4,
                                                "parent_id": v2["id"], "ragflow_doc_id": "doc-e5f6", "created_by": "李同学"}).json()
c.post(B + "/api/versions/register", json={"kb_id": "mock-kb-1", "title": "混合储能协调控制综述（初稿）",
                                           "text": "综述了混合储能系统协调控制的主要方法与挑战。" * 6,
                                           "ragflow_doc_id": "doc-g7h8", "created_by": "王同学"})
print("versions:", v1["id"], v2["id"], v3["id"])

# ---- 订阅支付：套餐订单与订阅 ----
o = c.post(B + "/api/billing/orders", json={"plan_code": "pro", "user_ref": "lab-tenant-01", "gateway": "qrcode"}).json()
c.post(B + f"/api/billing/orders/{o['order_no']}/confirm", headers=ADMIN)
o2 = c.post(B + "/api/billing/orders", json={"plan_code": "basic", "user_ref": "lab-tenant-02", "gateway": "mock"}).json()
c.post(B + f"/api/billing/orders/{o2['order_no']}/confirm", headers=ADMIN)
c.post(B + "/api/billing/usage", headers=ADMIN, json={"user_ref": "lab-tenant-01", "metric": "video_min", "amount": 42})
c.post(B + "/api/billing/usage", headers=ADMIN, json={"user_ref": "lab-tenant-01", "metric": "upload_mb", "amount": 860})
print("orders:", o["order_no"], o2["order_no"])

# ---- OEM：两个品牌 ----
c.post(B + "/api/oem/brands", headers=ADMIN, json={"key": "dianke", "app_name": "电科智库", "primary_color": "#0ea5e9",
                                                   "footer_text": "电科研究院 · 内部知识平台", "login_notice": "内部系统，请勿外传账号"})
c.post(B + "/api/oem/brands", headers=ADMIN, json={"key": "greentech", "app_name": "绿能知识云", "primary_color": "#16a34a",
                                                   "footer_text": "绿能科技 Group"})
print("brands created")

# ---- 视频：mock 流水线任务 ----
fake = io.BytesIO(b"\x00\x01\x02\x03fake-video" * 500)
j = c.post(B + "/api/video/jobs", files={"file": ("组会报告_储能控制策略.mp4", fake, "video/mp4")},
           data={"kb_id": "mock-kb-1", "user_ref": "lab-tenant-01"}).json()
for _ in range(60):
    time.sleep(0.5)
    js = c.get(B + f"/api/video/jobs/{j['id']}").json()
    if js["status"] in ("done", "failed"):
        break
print("video job:", js["status"], js.get("error", ""))
print("SEED DONE")
