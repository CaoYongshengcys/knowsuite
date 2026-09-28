# KnowSuite · RAGFlow 企业增强套件

在 [RAGFlow](https://github.com/infiniflow/ragflow)（开源 RAG 引擎）之上，通过其官方 REST API 叠加
五大企业级增强能力，**不修改 RAGFlow 一行源码**（RAGFlow 可随时独立升级）：

| 模块 | 能力定位 | 说明 |
|---|---|---|
| 📊 评测看板 | RAG 质量评测 | 测试集管理、跑批、四指标 LLM-judge 打分（忠实度/答案相关性/上下文精确率/召回率）、趋势看板 |
| 🗂 版本治理 | 文档版本管理 | 上传查重（完全重复/强相似/较相似三级提示）、版本链、现行稿/历史稿、归并/拆回独立/段落对照 diff |
| 💳 订阅支付 | 商业化订阅 | 套餐/订单/订阅/配额闸门（按月计量），网关抽象：mock、扫码+人工确认、支付宝占位 |
| 🎨 OEM 贴牌 | 品牌定制交付 | 品牌配置 CRUD、`/portal/{key}` 品牌外壳门户（iframe）、`/proxy/{key}/` 实验性页面注入代理 |
| 🎬 视频理解 | 多模态内容入库 | ffmpeg 抽音频+关键帧 → ASR 转写 → qwen-vl 逐帧描述 → 合成带时间戳 Markdown → 自动入 RAGFlow 知识库 |

技术栈：**FastAPI + SQLAlchemy/SQLite + 零构建前端（vanilla JS）**，单容器 <500MB 内存。

---

## 快速开始

### 方式一：Docker Compose（推荐）

```bash
cp .env.example .env       # 填写 RAGFLOW_API_KEY、AI_API_KEY（百炼）、ADMIN_TOKEN
docker compose up -d --build
# 控制台: http://localhost:8100
```

### 方式二：本地源码（开发）

```bash
pip install -r requirements.txt
# Windows 视频模块需安装 ffmpeg 并加入 PATH；不装则视频模块自动 mock 降级
cd backend && uvicorn app:app --host 0.0.0.0 --port 8100
```

### 无 RAGFlow 也能跑（演示/开发模式）

`.env` 中留空 `RAGFLOW_API_KEY`（或 `MOCK_RAGFLOW=1`）、留空 `AI_API_KEY`（或 `MOCK_LLM=1`），
全部模块自动降级为确定性 mock 数据，五大流程完整可演示。

---

## 配置说明（.env）

| 变量 | 说明 |
|---|---|
| `RAGFLOW_API_BASE` / `RAGFLOW_API_KEY` | RAGFlow 地址与 API Key（RAGFlow 界面右上角头像 → API 生成） |
| `RAGFLOW_WEB` | OEM 门户代理的 RAGFlow 前端地址 |
| `AI_API_BASE` / `AI_API_KEY` | OpenAI 兼容大模型端点，默认百炼 `dashscope.aliyuncs.com/compatible-mode/v1` |
| `AI_MODEL` / `AI_EMBED_MODEL` | 问答/judge 模型（qwen-plus）、向量模型（text-embedding-v4） |
| `ASR_API_BASE` / `ASR_API_KEY` / `ASR_MODEL` | ASR 适配器 A：OpenAI 兼容 `/audio/transcriptions`（Groq whisper、SiliconFlow 等） |
| `ASR_OMNI_MODEL` | ASR 适配器 B：百炼 qwen-omni 系（chat 接口传 base64 音频），A 不可用时启用 |
| `VL_MODEL` | 关键帧描述视觉模型（qwen-vl-plus） |
| `PAYMENT_GATEWAY` | mock / qrcode / alipay(占位) |
| `ADMIN_TOKEN` | 管理端接口口令（订单确认、品牌管理、用量上报），请求头 `X-Admin-Token` |

## 与 RAGFlow 的对接点

- **知识库/文档/解析**：`/api/v1/datasets...`（上传、解析、删除、列表）
- **检索**：`/api/v1/retrieval`（评测模块取上下文）
- **问答**：`/api/v1/chats_openai/{chat_id}/chat/completions`（评测可用 RAGFlow 助手作答）
- **配额联动**：视频模块上传前调 billing 配额闸门；评测跑批同理（软集成，billing 异常不阻塞）

## API 一览（全部挂在 KnowSuite 服务下）

```
GET  /api/health                     健康与依赖状态
GET  /api/datasets                   RAGFlow 知识库列表代理
--- 评测 ---
POST/GET/DELETE /api/eval/sets[...]  测试集/用例 CRUD、批量导入
POST /api/eval/sets/{id}/runs        跑批（后台线程）
GET  /api/eval/runs[/{id}]           批次列表/详情（含逐用例四维得分）
GET  /api/eval/dashboard             看板聚合（趋势）
--- 版本治理 ---
POST /api/versions/check             上传查重（duplicate/strong/weak/none）
POST /api/versions/register          登记版本（parent_id 入链，旧现行稿自动转历史）
GET  /api/versions/chains[/{id}]     版本链列表/详情（含操作日志）
POST /api/versions/merge|split       归并指定现行稿 / 单份拆回独立
GET  /api/versions/current?kb_id=    现行稿清单（检索侧"只答现行稿"过滤器）
GET  /api/versions/compare?a=&b=     段落级 unified diff 对照
--- 订阅支付 ---
GET  /api/billing/plans              套餐（首次自动播种 free/basic/pro/enterprise）
POST /api/billing/orders             下单（返回支付指引）
POST /api/billing/orders/{no}/confirm|cancel   管理员确认到账/取消
GET  /api/billing/orders             订单列表（管理）
GET  /api/billing/subscriptions/{user_ref}     订阅+配额+已用+剩余
GET  /api/billing/quota?user_ref=&metric=&amount=  前置配额校验
POST /api/billing/usage              用量上报（管理）
--- OEM ---
GET/POST/PUT/DELETE /api/oem/brands[/{key}]    品牌 CRUD（管理）
GET  /api/oem/brands/{key}/public    品牌公开配置
GET  /portal/{key}                   品牌门户（iframe 外壳）
GET  /proxy/{key}/{path}             实验性注入代理
--- 视频 ---
POST /api/video/jobs                 上传视频（multipart: file, kb_id, user_ref）
GET  /api/video/jobs[/{id}]          任务列表/状态轮询
GET  /api/video/jobs/{id}/markdown   产物 Markdown 预览
```

## 测试

```bash
python tests/smoke_test.py     # 44 项断言，mock 模式下全流程（无需 RAGFlow/LLM/ffmpeg）
```

## 已知边界（v0.1）

- judge 打分为单次 LLM 调用四维输出（成本 1/4），如需严格 RAGAS 可 `pip install ragas` 替换 `evaluation._run_eval_async` 的 judge 段
- `/proxy/{key}/` 直连代理对 SPA 深链/WebSocket 为尽力而为，生产建议用 `/portal/{key}` iframe 外壳
- 支付宝网关为占位（需商户资质）；当前推荐 qrcode+人工确认流
- 视频 ASR 依赖外部适配器（A/B 二选一），未配置时 mock 降级
- OEM 门户 iframe 方案要求 RAGFlow 允许被嵌入（同源部署或调整其响应头）

## License

本项目 Apache-2.0；RAGFlow 亦为 Apache-2.0（允许商用/修改/OEM 再分发，商标除外）。
