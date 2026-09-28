/* KnowSuite 控制台（零构建 vanilla JS） */
(function () {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const H = () => ({ "X-Admin-Token": $("#adminToken").value || "", "Content-Type": "application/json" });

  function toast(msg, err) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = err ? "show err" : "show";
    setTimeout(() => (t.className = ""), 3200);
  }
  async function api(path, opts = {}) {
    opts.headers = Object.assign({}, H(), opts.headers || {});
    if (opts.body && typeof opts.body !== "string" && !(opts.body instanceof FormData)) {
      opts.body = JSON.stringify(opts.body);
    }
    if (opts.body instanceof FormData) delete opts.headers["Content-Type"];
    const r = await fetch(path, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = { detail: await r.text() }; }
    if (!r.ok) { toast((data && (data.detail || data.error)) || ("HTTP " + r.status), true); throw new Error(r.status); }
    return data;
  }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const badge = (txt, cls) => `<span class="badge ${cls || ""}">${esc(txt)}</span>`;

  const KS = {
    state: { datasets: [], curSet: null, curRun: null, curChain: null },

    go(tab) { $$(".tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
      $$(".tabpane").forEach(p => p.classList.toggle("active", p.id === "tab-" + tab));
      ({ eval: KS.evalSets, version: KS.verChains, billing: KS.billInit, oem: KS.oemList, video: KS.videoJobs }[tab] || (() => {}))(); },

    // ---------- 概览 ----------
    async health() {
      try { const h = await api("/api/health"); $("#healthOut").textContent = JSON.stringify(h, null, 2); }
      catch (e) { $("#healthOut").textContent = "健康检查失败"; }
    },
    async loadDatasets() {
      let ds = [];
      try { ds = await api("/api/datasets"); } catch (e) { ds = []; }
      if (!Array.isArray(ds)) ds = [];
      KS.state.datasets = ds;
      $("#dsList").innerHTML = ds.length
        ? ds.map(d => `<div class="item"><b>${esc(d.name)}</b> <span class="muted small">${esc(d.id)}</span> ${badge((d.document_count || 0) + " 文档", "gray")}</div>`).join("")
        : '<p class="muted small">无知识库（RAGFlow 未连接时为 mock 数据）</p>';
      const opts = ds.map(d => `<option value="${esc(d.id)}">${esc(d.name)}</option>`).join("");
      ["#esKb", "#vcKb", "#vrKb", "#vdKb"].forEach(sel => { if ($(sel)) $(sel).innerHTML = opts; });
    },

    // ---------- 评测 ----------
    async evalSets() {
      const sets = await api("/api/eval/sets");
      $("#esList").innerHTML = sets.length ? sets.map(s => `
        <div class="item ${KS.state.curSet === s.id ? "sel" : ""}" onclick="KS.evalSelect(${s.id})">
          <b>${esc(s.name)}</b> ${badge(s.cases + " 用例", "gray")}
          ${s.last_run ? badge("最近:" + s.last_run.status, s.last_run.status === "done" ? "ok" : "warn") : ""}
          ${s.last_run && s.last_run.scores && s.last_run.scores.faithfulness != null
            ? `<span class="scores">忠${s.last_run.scores.faithfulness} 相关${s.last_run.scores.answer_relevancy} 精${s.last_run.scores.context_precision} 召${s.last_run.scores.context_recall}</span>` : ""}
          <a class="del" href="javascript:KS.evalDelSet(${s.id})">删除</a>
        </div>`).join("") : '<p class="muted small">暂无测试集</p>';
      KS.evalRuns();
    },
    async evalCreateSet() {
      const name = $("#esName").value.trim(); if (!name) return toast("请填写名称", true);
      await api("/api/eval/sets", { method: "POST", body: { name, kb_id: $("#esKb").value, chat_id: $("#esChat").value.trim() } });
      $("#esName").value = ""; toast("测试集已创建"); KS.evalSets();
    },
    async evalDelSet(id) { if (!confirm("删除测试集及其全部批次？")) return; await api("/api/eval/sets/" + id, { method: "DELETE" }); KS.evalSets(); },
    async evalSelect(id) {
      KS.state.curSet = id;
      const s = await api("/api/eval/sets/" + id);
      $("#esCurName").textContent = "· " + s.name;
      $("#ecList").innerHTML = s.cases.length ? s.cases.map(c =>
        `<div class="item"><b>Q:</b> ${esc(c.question).slice(0, 80)} ${c.ground_truth ? badge("有参考答案", "info") : ""}
         <a class="del" href="javascript:KS.evalDelCase(${c.id})">删</a></div>`).join("") : '<p class="muted small">暂无用例</p>';
      KS.evalSets();
    },
    async evalAddCase() {
      if (!KS.state.curSet) return toast("先选择测试集", true);
      const q = $("#ecQ").value.trim(); if (!q) return toast("请填写问题", true);
      await api(`/api/eval/sets/${KS.state.curSet}/cases`, { method: "POST", body: { question: q, ground_truth: $("#ecGt").value.trim() } });
      $("#ecQ").value = ""; $("#ecGt").value = ""; KS.evalSelect(KS.state.curSet);
    },
    async evalImportCases() {
      if (!KS.state.curSet) return toast("先选择测试集", true);
      const lines = $("#ecImport").value.trim(); if (!lines) return toast("请粘贴用例", true);
      const r = await api(`/api/eval/sets/${KS.state.curSet}/cases/import`, { method: "POST", body: { lines } });
      toast("已导入 " + r.imported + " 条"); $("#ecImport").value = ""; KS.evalSelect(KS.state.curSet);
    },
    async evalRun() {
      if (!KS.state.curSet) return toast("先选择测试集", true);
      const r = await api(`/api/eval/sets/${KS.state.curSet}/runs`, { method: "POST" });
      toast("跑批已开始 run_id=" + r.run_id); KS.state.curRun = r.run_id; KS.evalRuns();
      KS._pollRun = setInterval(KS.evalRuns, 4000);
    },
    async evalRuns() {
      const runs = await api("/api/eval/runs" + (KS.state.curSet ? "?set_id=" + KS.state.curSet : ""));
      $("#runList").innerHTML = runs.length ? runs.map(r => {
        const s = r.scores || {};
        return `<div class="item ${KS.state.curRun === r.id ? "sel" : ""}" onclick="KS.evalRunDetail(${r.id})">
          <b>#${r.id}</b> ${badge(r.status, r.status === "done" ? "ok" : (r.status === "failed" ? "err" : "warn"))}
          ${s.faithfulness != null ? `<span class="scores">忠实度 ${s.faithfulness} ｜ 相关性 ${s.answer_relevancy} ｜ 精确率 ${s.context_precision} ｜ 召回率 ${s.context_recall} ｜ 用例 ${s.cases}</span>` : (r.config && r.config.progress ? "进度 " + r.config.progress : "")}
          <span class="muted small">${(r.started_at || "").slice(0, 16).replace("T", " ")}</span></div>`;
      }).join("") : '<p class="muted small">暂无批次</p>';
      const running = runs.some(r => r.status === "running");
      if (!running && KS._pollRun) { clearInterval(KS._pollRun); KS._pollRun = null; }
      if (KS.state.curRun) KS.evalRunDetail(KS.state.curRun, true);
    },
    async evalRunDetail(id, silent) {
      KS.state.curRun = id;
      const r = await api("/api/eval/runs/" + id);
      $("#runCur").textContent = "# " + id + " · " + r.status;
      const head = r.scores && r.scores.faithfulness != null ? `<div class="scorebar">
        ${["faithfulness", "answer_relevancy", "context_precision", "context_recall"].map(k =>
          `<div class="sc"><b>${(r.scores[k] * 100 || 0).toFixed(0)}</b><span>${{ faithfulness: "忠实度", answer_relevancy: "相关性", context_precision: "精确率", context_recall: "召回率" }[k]}</span>
           <div class="bar"><i style="width:${(r.scores[k] || 0) * 100}%"></i></div></div>`).join("")}</div>` : "";
      $("#runDetail").innerHTML = head + (r.results || []).map(x => `
        <details class="case"><summary>${x.error ? "⚠ " : ""}${esc(x.question).slice(0, 70)}
          ${x.faithfulness != null ? badge("忠" + x.faithfulness + " 相" + x.answer_relevancy + " 精" + x.context_precision + " 召" + x.context_recall, "info") : ""}</summary>
          <p><b>回答：</b>${esc(x.answer).slice(0, 600)}</p>
          ${x.error ? `<p class="err">错误：${esc(x.error)}</p>` : ""}
          <p class="muted small">上下文片段数：${(x.contexts || []).length}</p>
        </details>`).join("");
      if (!silent) KS.evalRuns();
    },
    evalDelCase(id) { api("/api/eval/cases/" + id, { method: "DELETE" }).then(() => KS.evalSelect(KS.state.curSet)); },

    // ---------- 版本治理 ----------
    async verCheck() {
      const body = { kb_id: $("#vcKb").value, title: $("#vcTitle").value.trim(), text: $("#vcText").value };
      if (!body.title) return toast("请填写标题", true);
      const r = await api("/api/versions/check", { method: "POST", body });
      const list = (arr, tag, cls) => (arr || []).map(d =>
        `<div class="item">${badge(tag, cls)} <b>${esc(d.title)}</b> 相似度 ${(d.similarity * 100).toFixed(1)}%
         <span class="muted small">id=${d.id} ${esc((d.created_at || "").slice(0, 10))}</span>
         <a href="javascript:KS.verFillParent(${d.id})">作为父版本登记</a></div>`).join("");
      $("#vcResult").innerHTML = `<p>${badge(r.level, r.level === "none" ? "ok" : (r.level === "duplicate" ? "err" : "warn"))} ${esc(r.hint)}</p>`
        + list(r.strong, "强相似", "warn") + list(r.weak, "较相似", "gray")
        + (r.exact ? list([r.exact], "完全重复", "err") : "");
    },
    verFillParent(id) { $("#vrParent").value = id; $("#vrTitle").value = $("#vcTitle").value; $("#vrText").value = $("#vcText").value; toast("已填入 parent_id=" + id); },
    async verRegister() {
      const body = { kb_id: $("#vrKb").value, title: $("#vrTitle").value.trim(), text: $("#vrText").value,
        ragflow_doc_id: $("#vrDocId").value.trim(), parent_id: parseInt($("#vrParent").value) || null, created_by: $("#vrBy").value.trim() };
      if (!body.title) return toast("请填写标题", true);
      const d = await api("/api/versions/register", { method: "POST", body });
      toast("已登记 doc id=" + d.id + "，链 " + d.chain_id); KS.verChains();
    },
    async verChains() {
      const chains = await api("/api/versions/chains");
      $("#chainList").innerHTML = chains.length ? chains.map(c => `
        <div class="item ${KS.state.curChain === c.chain_id ? "sel" : ""}" onclick="KS.verChainDetail('${c.chain_id}')">
          <b>${esc(c.current.title)}</b> ${badge(c.versions + " 个版本", "info")}
          <span class="muted small">${esc(c.chain_id)} · 最新 ${c.latest_at.slice(0, 10)}</span></div>`).join("") : '<p class="muted small">暂无版本链</p>';
    },
    async verChainDetail(cid) {
      KS.state.curChain = cid;
      const c = await api("/api/versions/chains/" + encodeURIComponent(cid));
      $("#chainDetail").innerHTML = `<h3>链 ${esc(cid)}</h3>` + c.versions.map(v => `
        <div class="item">${v.is_current ? badge("现行稿", "ok") : badge("历史稿", "gray")}
          <b>${esc(v.title)}</b> <span class="muted small">id=${v.id} ${v.created_at.slice(0, 10)} ${esc(v.created_by || "")}</span>
          ${v.is_current ? "" : `<a href="javascript:KS.verKeep('${cid}',${v.id})">设为现行</a>`}
          <a href="javascript:KS.verSplit(${v.id})">拆回独立</a></div>`).join("")
        + (c.logs.length ? "<h4>操作日志</h4>" + c.logs.map(l => `<div class="muted small">${l.at.slice(0, 16).replace("T", " ")} · ${l.action} · ${esc(l.operator || "")}</div>`).join("") : "");
    },
    async verKeep(cid, id) { await api("/api/versions/merge", { method: "POST", body: { chain_id: cid, keep_id: id } }); toast("已归并"); KS.verChainDetail(cid); },
    async verSplit(id) { if (!confirm("将该文档拆回独立链？")) return; await api("/api/versions/split", { method: "POST", body: { doc_id: id } }); KS.verChains(); },
    async verCompare() {
      const a = parseInt($("#vcmpA").value), b = parseInt($("#vcmpB").value);
      if (!a || !b) return toast("填两个 doc id", true);
      const r = await api(`/api/versions/compare?a=${a}&b=${b}`);
      $("#vcmpOut").textContent = (r.unified_diff || []).join("\n") || "（无差异或无文本）";
    },

    // ---------- 订阅支付 ----------
    async billInit() {
      const plans = await api("/api/billing/plans");
      $("#planList").innerHTML = plans.map(p => `<div class="plan">
        <b>${esc(p.name)}</b><div class="price">¥${p.price_cny}<span>/${p.period_days >= 365 ? "永久" : p.period_days + "天"}</span></div>
        <ul>${Object.entries(p.quotas || {}).map(([k, v]) => `<li>${esc(k)}：${v === -1 ? "不限量" : v}</li>`).join("")}</ul>
        <code>${esc(p.code)}</code></div>`).join("");
      $("#odPlan").innerHTML = plans.map(p => `<option value="${p.code}">${esc(p.name)} ¥${p.price_cny}</option>`).join("");
      KS.billOrders(true);
    },
    async billOrder() {
      const user_ref = $("#odUser").value.trim(); if (!user_ref) return toast("填 user_ref", true);
      const r = await api("/api/billing/orders", { method: "POST", body: { plan_code: $("#odPlan").value, user_ref, gateway: $("#odGw").value } });
      $("#odOut").textContent = JSON.stringify(r, null, 2);
      toast("订单已创建：" + r.order_no);
    },
    async billOrders(silent) {
      try {
        const orders = await api("/api/billing/orders");
        $("#orderList").innerHTML = orders.length ? orders.map(o => `<div class="item">
          <b>${esc(o.order_no)}</b> ${badge(o.status, o.status === "paid" ? "ok" : (o.status === "created" ? "warn" : "gray"))}
          ${esc(o.plan)} ¥${o.amount} <span class="muted small">${esc(o.user_ref)} · ${o.gateway} · ${o.created_at.slice(0, 16).replace("T", " ")}</span>
          ${o.status === "created" ? `<a href="javascript:KS.billConfirmNo('${o.order_no}')">确认到账</a>` : ""}</div>`).join("") : '<p class="muted small">暂无订单（需管理口令）</p>';
      } catch (e) { if (!silent) toast("需要管理口令", true); }
    },
    async billConfirm() { const no = $("#cfOrderNo").value.trim(); if (!no) return toast("填订单号", true); await KS.billConfirmNo(no); },
    async billConfirmNo(no) { const r = await api(`/api/billing/orders/${no}/confirm`, { method: "POST" }); toast("已确认到账，订阅生效"); KS.billOrders(true); },
    async billSub() {
      const u = $("#subUser").value.trim(); if (!u) return toast("填 user_ref", true);
      const r = await api("/api/billing/subscriptions/" + encodeURIComponent(u));
      $("#subOut").textContent = JSON.stringify(r, null, 2);
    },

    // ---------- OEM ----------
    async oemList() {
      try {
        const brands = await api("/api/oem/brands");
        $("#brandList").innerHTML = brands.length ? brands.map(b => `<div class="item ${b.is_active ? "" : "dim"}">
          <span class="dot" style="background:${esc(b.primary_color)}"></span><b>${esc(b.app_name)}</b>
          <code>${esc(b.key)}</code>
          <a href="javascript:KS.oemEdit('${esc(b.key)}')">编辑</a>
          <a href="/portal/${esc(b.key)}" target="_blank">门户</a>
          <a class="del" href="javascript:KS.oemDel('${esc(b.key)}')">删除</a></div>`).join("") : '<p class="muted small">暂无品牌（需管理口令）</p>';
      } catch (e) { $("#brandList").innerHTML = '<p class="muted small">读取失败：需管理口令</p>'; }
    },
    async oemEdit(key) {
      const brands = await api("/api/oem/brands");
      const b = brands.find(x => x.key === key); if (!b) return;
      $("#brKey").value = b.key; $("#brName").value = b.app_name; $("#brColor").value = b.primary_color;
      $("#brLogo").value = b.logo_url || ""; $("#brFooter").value = b.footer_text || "";
      $("#brNotice").value = b.login_notice || ""; $("#brCss").value = b.custom_css || "";
    },
    async oemSave() {
      const body = { key: $("#brKey").value.trim(), app_name: $("#brName").value.trim() || "AI 知识库",
        logo_url: $("#brLogo").value.trim(), primary_color: $("#brColor").value, footer_text: $("#brFooter").value.trim(),
        login_notice: $("#brNotice").value.trim(), custom_css: $("#brCss").value.trim(), is_active: true };
      if (!body.key) return toast("填 key", true);
      const exist = $("#brandList").innerHTML.includes(">" + body.key + "<");
      await api("/api/oem/brands" + (exist ? "/" + body.key : ""), { method: exist ? "PUT" : "POST", body });
      toast("品牌已保存"); KS.oemList();
      $("#portalLink").href = "/portal/" + body.key; $("#proxyLink").href = "/proxy/" + body.key + "/";
    },
    async oemDel(key) { if (!confirm("删除品牌 " + key + "？")) return; await api("/api/oem/brands/" + key, { method: "DELETE" }); KS.oemList(); },
    oemPreview() { const k = $("#brKey").value.trim(); if (!k) return toast("先填/选品牌 key", true); $("#oemPreview").src = "/portal/" + k; },

    // ---------- 视频 ----------
    async videoUpload() {
      const f = $("#vdFile").files[0]; if (!f) return toast("选择视频文件", true);
      const fd = new FormData(); fd.append("file", f); fd.append("kb_id", $("#vdKb").value); fd.append("user_ref", $("#vdUser").value.trim());
      const r = await api("/api/video/jobs", { method: "POST", body: fd });
      toast("任务已创建 id=" + r.id + "，后台处理中"); KS.videoJobs();
      KS._pollJob = setInterval(KS.videoJobs, 5000);
    },
    async videoJobs() {
      const jobs = await api("/api/video/jobs");
      $("#jobList").innerHTML = jobs.length ? jobs.map(j => `<div class="item">
        <b>#${j.id} ${esc(j.filename)}</b> ${badge(j.status, j.status === "done" ? "ok" : (j.status === "failed" ? "err" : "warn"))}
        <span class="muted small">${esc(j.stage_info || "")} ${j.duration_sec ? "· " + Math.round(j.duration_sec) + "s" : ""} ${j.frames_count ? "· " + j.frames_count + "帧" : ""} ${j.error ? "· " + esc(j.error).slice(0, 60) : ""}</span>
        ${j.status === "done" ? `<a href="javascript:KS.videoMd(${j.id})">查看产物</a>` : ""}</div>`).join("") : '<p class="muted small">暂无任务</p>';
      if (!jobs.some(j => !["done", "failed"].includes(j.status)) && KS._pollJob) { clearInterval(KS._pollJob); KS._pollJob = null; }
    },
    async videoMd(id) {
      const r = await api("/api/video/jobs/" + id + "/markdown");
      $("#mdCur").textContent = "· " + r.filename;
      $("#mdOut").textContent = r.markdown;
    },
  };

  window.KS = KS;
  document.addEventListener("click", (e) => {
    const t = e.target.closest(".tab");
    if (t) KS.go(t.dataset.tab);
  });
  $("#adminToken").value = localStorage.getItem("ks_admin") || "";
  $("#adminToken").addEventListener("change", (e) => localStorage.setItem("ks_admin", e.target.value));
  KS.health(); KS.loadDatasets(); KS.evalSets();
})();
