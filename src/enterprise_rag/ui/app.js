(() => {
  "use strict";

  const byId = (id) => document.getElementById(id);
  const views = {
    assistant: { kicker: "对话与决策", title: "智能问答" },
    knowledge: { kicker: "内容与索引", title: "知识管理" },
    operations: { kicker: "健康与质量", title: "运行观测" },
  };
  const state = {
    apiKey: sessionStorage.getItem("enterprise-rag-api-key") || "",
    conversationId: newConversationId(),
    history: [],
    currentView: "assistant",
    pendingDelete: null,
  };

  function newConversationId() {
    if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
    return `ui-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  }

  class ApiError extends Error {
    constructor(message, status, requestId) {
      super(message);
      this.name = "ApiError";
      this.status = status;
      this.requestId = requestId;
    }
  }

  async function apiFetch(path, options = {}) {
    const headers = new Headers(options.headers || {});
    if (state.apiKey) headers.set("X-API-Key", state.apiKey);
    if (!(options.body instanceof FormData) && options.body !== undefined) {
      headers.set("Content-Type", "application/json");
    }
    const response = await fetch(path, { ...options, headers });
    const requestId = response.headers.get("X-Request-ID") || "";
    const text = await response.text();
    let payload = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        payload = text;
      }
    }
    if (!response.ok) {
      const message = extractError(payload) || `请求失败（HTTP ${response.status}）`;
      throw new ApiError(message, response.status, requestId);
    }
    return { data: payload, response, requestId };
  }

  function extractError(payload) {
    if (!payload) return "";
    if (typeof payload === "string") return payload;
    if (payload.error?.message) return payload.error.message;
    if (typeof payload.detail === "string") return payload.detail;
    if (Array.isArray(payload.detail)) {
      return payload.detail.map((item) => item.msg || "参数无效").join("；");
    }
    return "";
  }

  function announce(message) {
    const node = byId("status-announcer");
    node.textContent = "";
    window.setTimeout(() => {
      node.textContent = message;
    }, 20);
  }

  function toast(message, kind = "info") {
    const node = document.createElement("div");
    node.className = `toast${kind === "error" ? " is-error" : ""}`;
    node.textContent = message;
    byId("toast-region").append(node);
    announce(message);
    window.setTimeout(() => node.remove(), 4400);
  }

  async function busy(button, task) {
    const originalDisabled = button.disabled;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try {
      return await task();
    } finally {
      button.disabled = originalDisabled;
      button.removeAttribute("aria-busy");
    }
  }

  function setServiceState(kind, label) {
    const node = byId("sidebar-service-status");
    node.classList.remove("is-ok", "is-error");
    if (kind) node.classList.add(kind === "ok" ? "is-ok" : "is-error");
    node.querySelector("span:last-child").textContent = label;
  }

  function setView(name, updateHash = false) {
    const next = views[name] ? name : "assistant";
    state.currentView = next;
    document.querySelectorAll("[data-view]").forEach((view) => {
      const selected = view.dataset.view === next;
      view.hidden = !selected;
      view.classList.toggle("is-visible", selected);
    });
    document.querySelectorAll("[data-view-link]").forEach((link) => {
      const selected = link.dataset.viewLink === next;
      link.classList.toggle("is-active", selected);
      if (selected) link.setAttribute("aria-current", "page");
      else link.removeAttribute("aria-current");
    });
    byId("view-kicker").textContent = views[next].kicker;
    byId("view-title").textContent = views[next].title;
    document.title = `${views[next].title} · 企业 RAG 工作台`;
    if (updateHash && location.hash !== `#${next}`) history.pushState(null, "", `#${next}`);
    if (next === "knowledge") void refreshDocuments({ quiet: true });
    if (next === "operations") void refreshOperations({ quiet: true });
  }

  function currentHashView() {
    return location.hash.replace(/^#/, "") || "assistant";
  }

  async function refreshHealth({ quiet = false } = {}) {
    try {
      const { data } = await apiFetch("/health/ready");
      const healthy = data.status === "ready";
      setServiceState(healthy ? "ok" : "error", healthy ? "服务正常" : "服务未就绪");
      byId("environment-badge").textContent = `${data.environment} · ${data.model_provider || "模型未知"}`;
      renderHealth(data);
      return data;
    } catch (error) {
      setServiceState("error", "连接失败");
      if (!quiet) toast(describeError(error), "error");
      throw error;
    }
  }

  function renderHealth(data) {
    byId("health-ready").textContent = data.status === "ready" ? "就绪" : "未就绪";
    byId("health-model").textContent = data.model_provider || "未知";
    byId("health-database").textContent = data.components?.database || "未知";
    byId("health-version").textContent = data.version || "未知";
  }

  function describeError(error) {
    if (error instanceof ApiError) {
      const suffix = error.requestId ? ` · 请求 ${error.requestId.slice(0, 8)}` : "";
      if (error.status === 401) return `认证失败，请检查 API Key${suffix}`;
      if (error.status === 429) return `请求过于频繁，请稍后重试${suffix}`;
      return `${error.message}${suffix}`;
    }
    if (error instanceof TypeError) return "无法连接服务，请确认应用正在运行";
    return error instanceof Error ? error.message : "发生未知错误";
  }

  function appendMessage(role, text, options = {}) {
    const item = document.createElement("li");
    item.className = `message message-${role}${options.error ? " is-error" : ""}`;
    if (options.id) item.id = options.id;

    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = options.meta || (role === "user" ? "你" : "RAG 助手");
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.textContent = text;
    item.append(meta, bubble);
    byId("message-list").append(item);
    byId("conversation-empty").hidden = true;
    scrollConversation();
    return item;
  }

  function appendThinking() {
    const item = document.createElement("li");
    item.className = "message message-assistant message-thinking";
    item.id = "assistant-thinking";
    const meta = document.createElement("div");
    meta.className = "message-meta";
    meta.textContent = "正在路由与检索";
    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.setAttribute("aria-label", "正在生成回答");
    for (let index = 0; index < 3; index += 1) {
      const dot = document.createElement("span");
      dot.className = "thinking-dot";
      dot.setAttribute("aria-hidden", "true");
      bubble.append(dot);
    }
    item.append(meta, bubble);
    byId("message-list").append(item);
    byId("conversation-empty").hidden = true;
    scrollConversation();
  }

  function scrollConversation() {
    const scroll = byId("conversation-scroll");
    window.requestAnimationFrame(() => {
      scroll.scrollTop = scroll.scrollHeight;
    });
  }

  async function submitAssistant(event) {
    event.preventDefault();
    const queryInput = byId("assistant-query");
    const errorNode = byId("composer-error");
    const query = queryInput.value.trim();
    if (!query) {
      queryInput.setAttribute("aria-invalid", "true");
      errorNode.textContent = "请输入问题后再发送。";
      queryInput.focus();
      return;
    }
    queryInput.removeAttribute("aria-invalid");
    errorNode.textContent = "";
    const previousHistory = state.history.slice(-20);
    appendMessage("user", query);
    appendThinking();
    const button = byId("send-query");
    const submittedText = queryInput.value;
    queryInput.value = "";
    updateCharacterCount();

    try {
      await busy(button, async () => {
        const { data, requestId } = await apiFetch("/api/v1/assistant/respond", {
          method: "POST",
          body: JSON.stringify({
            query,
            conversation_id: state.conversationId,
            actor_type: byId("actor-type").value,
            history: previousHistory,
            provided_slots: {},
          }),
        });
        byId("assistant-thinking")?.remove();
        state.conversationId = data.conversation_id || state.conversationId;
        state.history.push({ role: "user", content: query });
        if (data.answer) state.history.push({ role: "assistant", content: data.answer });
        const meta = `${statusLabel(data.status)} · ${routeLabel(data.route?.target)}${
          requestId ? ` · ${requestId.slice(0, 8)}` : ""
        }`;
        appendMessage("assistant", data.answer || "请求已完成。", { meta });
        renderInspector(data);
        announce(`回答完成，状态：${statusLabel(data.status)}`);
      });
    } catch (error) {
      byId("assistant-thinking")?.remove();
      queryInput.value = submittedText;
      updateCharacterCount();
      const message = describeError(error);
      appendMessage("assistant", message, { error: true, meta: "请求未完成" });
      errorNode.textContent = message;
      if (error instanceof ApiError && error.status === 401) openConnectionDialog();
    }
  }

  function statusLabel(status) {
    const labels = {
      answered: "已回答",
      needs_input: "需要补充",
      action_completed: "任务完成",
      cancelled: "已取消",
      handoff: "已转人工",
      insufficient_evidence: "证据不足",
      needs_human: "需要人工",
      rejected: "安全拦截",
    };
    return labels[status] || status || "已处理";
  }

  function routeLabel(route) {
    const labels = {
      reject: "安全拒绝",
      chitchat: "闲聊",
      task_flow: "任务流",
      kbqa: "结构化问答",
      rag: "RAG 检索",
    };
    return labels[route] || route || "待判断";
  }

  function renderInspector(result) {
    const route = result.route || {};
    const retrieval = result.retrieval || result.generation?.retrieval || null;
    const citations = result.generation?.citations || retrieval?.citations || [];
    byId("inspector-empty").hidden = true;
    byId("inspector-content").hidden = false;
    const badge = byId("route-badge");
    badge.textContent = routeLabel(route.target);

    const decisions = [
      ["处理状态", statusLabel(result.status)],
      ["安全判断", route.safety?.decision || "未知"],
      ["业务领域", route.domain?.display_name || route.domain?.name || "未知"],
      ["识别意图", route.intent?.display_name || route.intent?.name || "未知"],
      ["目标受众", route.audience || "未知"],
      ["耗时", retrieval ? `${formatNumber(retrieval.duration_ms, 1)} ms` : "不适用"],
    ];
    const decisionList = byId("decision-list");
    decisionList.replaceChildren();
    decisions.forEach(([term, value]) => {
      const wrapper = document.createElement("div");
      const dt = document.createElement("dt");
      const dd = document.createElement("dd");
      dt.textContent = term;
      dd.textContent = value;
      wrapper.append(dt, dd);
      decisionList.append(wrapper);
    });

    const routeList = byId("retrieval-routes");
    routeList.replaceChildren();
    const executions = retrieval?.routes || [];
    if (!executions.length) {
      routeList.append(emptyListItem("当前路径未调用检索通道"));
    } else {
      executions.forEach((execution) => {
        const item = document.createElement("li");
        const name = document.createElement("strong");
        const status = document.createElement("span");
        const timing = document.createElement("span");
        name.textContent = routeName(execution.route);
        status.textContent = `${execution.status} · ${execution.hit_count} 条`;
        status.className = `route-status ${
          execution.status === "ok" ? "is-ok" : execution.status === "error" ? "is-error" : "is-muted"
        }`;
        timing.textContent = `${formatNumber(execution.duration_ms, 1)} ms`;
        item.append(name, status, timing);
        routeList.append(item);
      });
    }

    const citationList = byId("citation-list");
    citationList.replaceChildren();
    if (!citations.length) {
      citationList.append(emptyListItem("当前回答没有引用证据"));
    } else {
      citations.forEach((citation) => {
        const item = document.createElement("li");
        const header = document.createElement("div");
        header.className = "citation-title";
        const title = document.createElement("span");
        const score = document.createElement("span");
        title.textContent = `[${citation.index}] ${citation.title || citation.source_type}`;
        score.textContent = formatScore(citation.score);
        header.append(title, score);
        const snippet = document.createElement("p");
        snippet.textContent = citation.snippet || "无摘要";
        item.append(header, snippet);
        citationList.append(item);
      });
    }

    const traceList = byId("trace-list");
    traceList.replaceChildren();
    (route.trace || []).forEach((step) => {
      const item = document.createElement("li");
      item.textContent = `${step.stage}：${step.decision}${
        step.confidence == null ? "" : `（${formatScore(step.confidence)}）`
      }`;
      traceList.append(item);
    });
    if (!traceList.children.length) traceList.append(emptyListItem("没有可用的路由轨迹"));
  }

  function emptyListItem(text) {
    const item = document.createElement("li");
    item.className = "empty-copy";
    item.textContent = text;
    return item;
  }

  function routeName(route) {
    const labels = {
      semantic: "语义检索",
      lexical: "关键词检索",
      web: "受控互联网",
      kg: "知识图谱",
      faq: "FAQ",
    };
    return labels[route] || route;
  }

  function resetConversation() {
    state.conversationId = newConversationId();
    state.history = [];
    byId("message-list").replaceChildren();
    byId("conversation-empty").hidden = false;
    byId("inspector-empty").hidden = false;
    byId("inspector-content").hidden = true;
    byId("route-badge").textContent = "等待提问";
    byId("assistant-query").value = "";
    byId("composer-error").textContent = "";
    updateCharacterCount();
    byId("assistant-query").focus();
    announce("已开始新对话");
  }

  function updateCharacterCount() {
    const input = byId("assistant-query");
    byId("character-count").textContent = `${input.value.length} / 4000`;
  }

  async function refreshDocuments({ quiet = false } = {}) {
    const body = byId("document-table-body");
    const empty = byId("document-empty");
    try {
      const { data } = await apiFetch("/api/v1/knowledge/documents");
      body.replaceChildren();
      byId("document-count").textContent = String(data.length);
      empty.hidden = data.length > 0;
      data.forEach((documentRecord) => body.append(documentRow(documentRecord)));
    } catch (error) {
      body.replaceChildren();
      empty.hidden = false;
      empty.textContent = describeError(error);
      if (!quiet) toast(describeError(error), "error");
    }
  }

  function documentRow(record) {
    const row = document.createElement("tr");
    const identity = document.createElement("td");
    const name = document.createElement("span");
    const source = document.createElement("span");
    name.className = "document-name";
    source.className = "document-source";
    name.textContent = record.title;
    source.textContent = record.source_uri;
    source.title = record.source_uri;
    identity.append(name, source);

    const version = document.createElement("td");
    const chunks = document.createElement("td");
    const updated = document.createElement("td");
    version.textContent = `v${record.current_version}`;
    chunks.textContent = String(record.chunk_count);
    updated.textContent = formatDate(record.updated_at);

    const action = document.createElement("td");
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "row-action";
    remove.dataset.deleteDocument = record.id;
    remove.dataset.documentTitle = record.title;
    remove.textContent = "停用";
    remove.setAttribute("aria-label", `停用文档：${record.title}`);
    action.append(remove);
    row.append(identity, version, chunks, updated, action);
    return row;
  }

  async function uploadDocument(event) {
    event.preventDefault();
    const fileInput = byId("document-file");
    const status = byId("upload-status");
    if (!fileInput.files?.length) {
      status.className = "form-status is-error";
      status.textContent = "请选择文档。";
      fileInput.focus();
      return;
    }
    const metadataText = byId("metadata-json").value.trim() || "{}";
    try {
      const parsed = JSON.parse(metadataText);
      if (!parsed || Array.isArray(parsed) || typeof parsed !== "object") throw new Error();
    } catch {
      status.className = "form-status is-error";
      status.textContent = "元数据必须是 JSON 对象。";
      byId("metadata-json").focus();
      return;
    }
    const formData = new FormData();
    formData.set("file", fileInput.files[0]);
    const sourceUri = byId("source-uri").value.trim();
    if (sourceUri) formData.set("source_uri", sourceUri);
    formData.set("metadata_json", metadataText);
    const button = byId("upload-document");
    status.className = "form-status";
    status.textContent = "正在解析和索引…";
    try {
      await busy(button, async () => {
        const { data } = await apiFetch("/api/v1/knowledge/documents/ingest", {
          method: "POST",
          body: formData,
        });
        status.className = "form-status is-success";
        status.textContent = `已${ingestionLabel(data.action)}：${data.document.title}`;
        fileInput.value = "";
        byId("file-label").textContent = "选择或拖入文档";
        await refreshDocuments({ quiet: true });
        toast(`文档${ingestionLabel(data.action)}成功`);
      });
    } catch (error) {
      status.className = "form-status is-error";
      status.textContent = describeError(error);
    }
  }

  function ingestionLabel(action) {
    return { created: "创建", updated: "更新", unchanged: "确认无变化", duplicate: "识别为重复" }[action] || action;
  }

  async function submitFaq(event) {
    event.preventDefault();
    const button = event.submitter;
    const status = byId("faq-status");
    status.className = "form-status";
    status.textContent = "正在保存…";
    try {
      await busy(button, async () => {
        const { data } = await apiFetch("/api/v1/knowledge/faqs/import", {
          method: "POST",
          body: JSON.stringify({
            items: [
              {
                question: byId("faq-question").value.trim(),
                answer: byId("faq-answer").value.trim(),
                approved: byId("faq-approved").checked,
                metadata: { source: "ui" },
              },
            ],
          }),
        });
        status.className = "form-status is-success";
        status.textContent = `已保存（新建 ${data.created}，更新 ${data.updated}）`;
        byId("faq-form").reset();
        byId("faq-approved").checked = true;
        toast("FAQ 已写入知识库");
      });
    } catch (error) {
      status.className = "form-status is-error";
      status.textContent = describeError(error);
    }
  }

  async function submitKg(event) {
    event.preventDefault();
    const button = event.submitter;
    const status = byId("kg-status");
    status.className = "form-status";
    status.textContent = "正在保存…";
    try {
      await busy(button, async () => {
        const { data } = await apiFetch("/api/v1/kbqa/kg/triples/import", {
          method: "POST",
          body: JSON.stringify({
            triples: [
              {
                subject: byId("kg-subject").value.trim(),
                predicate: byId("kg-predicate").value.trim(),
                object: byId("kg-object").value.trim(),
                metadata: { source: "ui" },
              },
            ],
          }),
        });
        status.className = "form-status is-success";
        status.textContent = `已保存（新建 ${data.created}，更新 ${data.updated}）`;
        byId("kg-form").reset();
        toast("知识图谱三元组已保存");
      });
    } catch (error) {
      status.className = "form-status is-error";
      status.textContent = describeError(error);
    }
  }

  async function rebuildIndexes() {
    const button = byId("rebuild-index");
    try {
      await busy(button, async () => {
        const { data } = await apiFetch("/api/v1/knowledge/indexes/rebuild", { method: "POST" });
        toast(`索引已重建：${data.documents} 篇文档，${data.chunks} 个分块`);
        await refreshDocuments({ quiet: true });
      });
    } catch (error) {
      toast(describeError(error), "error");
    }
  }

  function askToDelete(documentId, title, trigger) {
    state.pendingDelete = { documentId, title, trigger };
    byId("delete-description").textContent = `“${title}”将不再参与检索。历史版本仍保留，可通过重新上传相同来源恢复。`;
    byId("delete-dialog").showModal();
  }

  async function deletePendingDocument() {
    const pending = state.pendingDelete;
    state.pendingDelete = null;
    if (!pending) return;
    try {
      await apiFetch(`/api/v1/knowledge/documents/${encodeURIComponent(pending.documentId)}`, {
        method: "DELETE",
      });
      toast(`已停用文档：${pending.title}`);
      await refreshDocuments({ quiet: true });
      byId("refresh-documents").focus();
    } catch (error) {
      toast(describeError(error), "error");
      pending.trigger?.focus();
    }
  }

  async function searchKnowledge(event) {
    event.preventDefault();
    const query = byId("search-query").value.trim();
    const button = event.submitter;
    const target = byId("search-results");
    target.innerHTML = '<p class="empty-copy">正在执行关键词与向量检索…</p>';
    try {
      await busy(button, async () => {
        const { data } = await apiFetch("/api/v1/knowledge/search", {
          method: "POST",
          body: JSON.stringify({ query, limit: 5 }),
        });
        renderSearchResults(data);
      });
    } catch (error) {
      target.replaceChildren();
      const message = document.createElement("p");
      message.className = "empty-copy";
      message.textContent = describeError(error);
      target.append(message);
    }
  }

  function renderSearchResults(data) {
    const target = byId("search-results");
    target.replaceChildren();
    const columns = document.createElement("div");
    columns.className = "search-columns";
    columns.append(searchColumn("关键词召回", data.lexical), searchColumn("向量召回", data.vector));
    target.append(columns);
    announce(`检索完成，共返回 ${data.lexical.length + data.vector.length} 条结果`);
  }

  function searchColumn(title, hits) {
    const column = document.createElement("section");
    column.className = "result-column";
    const heading = document.createElement("h4");
    heading.textContent = `${title} · ${hits.length}`;
    const list = document.createElement("ol");
    if (!hits.length) list.append(emptyListItem("没有匹配结果"));
    hits.forEach((hit) => {
      const item = document.createElement("li");
      item.className = "search-hit";
      const header = document.createElement("header");
      const source = document.createElement("span");
      const score = document.createElement("span");
      source.textContent = hit.source_type === "faq" ? "FAQ" : "文档";
      score.textContent = formatScore(hit.score);
      header.append(source, score);
      const content = document.createElement("p");
      content.textContent = hit.content;
      item.append(header, content);
      list.append(item);
    });
    column.append(heading, list);
    return column;
  }

  async function refreshOperations({ quiet = false } = {}) {
    const settled = await Promise.allSettled([
      refreshHealth({ quiet: true }),
      apiFetch("/api/v1/observability/slo"),
      apiFetch("/api/v1/rag/quality/summary"),
    ]);
    if (settled[1].status === "fulfilled") renderSlo(settled[1].value.data);
    else renderSloError(describeError(settled[1].reason));
    if (settled[2].status === "fulfilled") renderQuality(settled[2].value.data);
    else renderQualityError();
    byId("operations-freshness").textContent = `更新于 ${new Intl.DateTimeFormat("zh-CN", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    }).format(new Date())}`;
    const failed = settled.filter((result) => result.status === "rejected");
    if (failed.length && !quiet) toast(describeError(failed[0].reason), "error");
  }

  function renderSlo(data) {
    const badge = byId("slo-status");
    badge.classList.remove("is-ok", "is-error");
    badge.textContent = { healthy: "目标内", violated: "已违反", no_data: "暂无样本" }[data.status] || data.status;
    if (data.status === "healthy") badge.classList.add("is-ok");
    if (data.status === "violated") badge.classList.add("is-error");
    const list = byId("slo-metrics");
    list.replaceChildren();
    data.checks.forEach((check) => {
      const row = document.createElement("div");
      row.className = "metric-row";
      const name = document.createElement("span");
      const meter = document.createElement("meter");
      const value = document.createElement("span");
      name.textContent = sloName(check.name);
      value.className = "metric-value";
      const actual = check.actual;
      if (check.unit === "ratio") {
        meter.min = 0;
        meter.max = 1;
        meter.value = actual ?? 0;
        meter.low = check.target;
        value.textContent = actual == null ? "无样本" : `${formatNumber(actual * 100, 1)}% / ${formatNumber(check.target * 100, 0)}%`;
      } else {
        meter.min = 0;
        meter.max = Math.max(check.target * 2, actual || 0, 1);
        meter.value = actual ?? 0;
        meter.high = check.target;
        value.textContent = actual == null ? "无样本" : `${formatNumber(actual, 0)} / ${formatNumber(check.target, 0)} ms`;
      }
      row.append(name, meter, value);
      list.append(row);
    });
  }

  function sloName(name) {
    return {
      availability: "可用率",
      http_p95_latency: "P95 延迟",
      p95_latency_ms: "P95 延迟",
      answer_success: "回答成功率",
      answer_success_rate: "回答成功率",
    }[name] || name;
  }

  function renderSloError(message) {
    const badge = byId("slo-status");
    badge.textContent = "不可用";
    badge.className = "status-label is-error";
    const list = byId("slo-metrics");
    list.replaceChildren();
    const paragraph = document.createElement("p");
    paragraph.className = "empty-copy";
    paragraph.textContent = message;
    list.append(paragraph);
  }

  function renderQuality(data) {
    byId("quality-total").textContent = String(data.total);
    byId("quality-answered").textContent = String(data.answered);
    byId("quality-insufficient").textContent = String(data.insufficient_evidence);
    byId("quality-human").textContent = String(data.needs_human);
    byId("quality-repaired").textContent = String(data.repaired);
  }

  function renderQualityError() {
    ["quality-total", "quality-answered", "quality-insufficient", "quality-human", "quality-repaired"].forEach(
      (id) => {
        byId(id).textContent = "不可用";
      },
    );
  }

  function openConnectionDialog() {
    const dialog = byId("connection-dialog");
    byId("api-key").value = state.apiKey;
    byId("connection-status").textContent = state.apiKey ? "已加载本会话中的密钥。" : "本地无鉴权时可留空。";
    byId("connection-status").className = "modal-status";
    dialog.showModal();
    window.setTimeout(() => byId("api-key").focus(), 30);
  }

  async function saveApiKey() {
    const input = byId("api-key");
    const status = byId("connection-status");
    const button = byId("save-api-key");
    const candidate = input.value.trim();
    status.className = "modal-status";
    status.textContent = "正在验证连接…";
    const previous = state.apiKey;
    state.apiKey = candidate;
    try {
      await busy(button, async () => {
        await apiFetch("/api/v1/routing/catalog");
      });
      if (candidate) sessionStorage.setItem("enterprise-rag-api-key", candidate);
      else sessionStorage.removeItem("enterprise-rag-api-key");
      status.className = "modal-status is-success";
      status.textContent = "验证成功，连接配置已保存。";
      setServiceState("ok", "服务正常");
      toast("API 连接验证成功");
      window.setTimeout(() => byId("connection-dialog").close("saved"), 450);
    } catch (error) {
      state.apiKey = previous;
      status.className = "modal-status is-error";
      status.textContent = describeError(error);
      input.focus();
    }
  }

  function clearApiKey() {
    state.apiKey = "";
    sessionStorage.removeItem("enterprise-rag-api-key");
    byId("api-key").value = "";
    byId("connection-status").className = "modal-status";
    byId("connection-status").textContent = "密钥已从当前会话清除。";
    toast("已清除会话 API Key");
  }

  function formatScore(value) {
    const number = Number(value);
    return Number.isFinite(number) ? `${formatNumber(number * 100, 1)}%` : "—";
  }

  function formatNumber(value, digits = 0) {
    const number = Number(value);
    return Number.isFinite(number)
      ? new Intl.NumberFormat("zh-CN", { maximumFractionDigits: digits }).format(number)
      : "—";
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "—";
    return new Intl.DateTimeFormat("zh-CN", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
    }).format(date);
  }

  function configureDragAndDrop() {
    const zone = byId("drop-zone");
    const input = byId("document-file");
    ["dragenter", "dragover"].forEach((eventName) => {
      zone.addEventListener(eventName, (event) => {
        event.preventDefault();
        zone.classList.add("is-dragging");
      });
    });
    ["dragleave", "drop"].forEach((eventName) => {
      zone.addEventListener(eventName, () => zone.classList.remove("is-dragging"));
    });
    zone.addEventListener("drop", (event) => {
      event.preventDefault();
      const files = event.dataTransfer?.files;
      if (!files?.length) return;
      const transfer = new DataTransfer();
      transfer.items.add(files[0]);
      input.files = transfer.files;
      updateFileLabel();
    });
    input.addEventListener("change", updateFileLabel);
  }

  function updateFileLabel() {
    const file = byId("document-file").files?.[0];
    byId("file-label").textContent = file ? file.name : "选择或拖入文档";
  }

  function bindEvents() {
    document.querySelectorAll("[data-view-link]").forEach((link) => {
      link.addEventListener("click", (event) => {
        event.preventDefault();
        setView(link.dataset.viewLink, true);
        byId("main-content").focus({ preventScroll: true });
      });
    });
    window.addEventListener("hashchange", () => setView(currentHashView()));
    byId("assistant-form").addEventListener("submit", submitAssistant);
    byId("assistant-query").addEventListener("input", updateCharacterCount);
    byId("assistant-query").addEventListener("keydown", (event) => {
      if (event.ctrlKey && event.key === "Enter") {
        event.preventDefault();
        byId("assistant-form").requestSubmit();
      }
    });
    document.querySelectorAll("[data-suggestion]").forEach((button) => {
      button.addEventListener("click", () => {
        byId("assistant-query").value = button.dataset.suggestion;
        updateCharacterCount();
        byId("assistant-query").focus();
      });
    });
    byId("new-conversation").addEventListener("click", resetConversation);
    byId("document-form").addEventListener("submit", uploadDocument);
    byId("faq-form").addEventListener("submit", submitFaq);
    byId("kg-form").addEventListener("submit", submitKg);
    byId("search-form").addEventListener("submit", searchKnowledge);
    byId("refresh-documents").addEventListener("click", () => refreshDocuments());
    byId("rebuild-index").addEventListener("click", rebuildIndexes);
    byId("document-table-body").addEventListener("click", (event) => {
      const button = event.target.closest("[data-delete-document]");
      if (button) askToDelete(button.dataset.deleteDocument, button.dataset.documentTitle, button);
    });
    byId("delete-dialog").addEventListener("close", () => {
      if (byId("delete-dialog").returnValue === "confirm") void deletePendingDocument();
      else {
        state.pendingDelete?.trigger?.focus();
        state.pendingDelete = null;
      }
    });
    ["open-connection", "operations-connection"].forEach((id) => byId(id).addEventListener("click", openConnectionDialog));
    byId("save-api-key").addEventListener("click", saveApiKey);
    byId("clear-api-key").addEventListener("click", clearApiKey);
    byId("toggle-api-key").addEventListener("click", () => {
      const input = byId("api-key");
      const visible = input.type === "text";
      input.type = visible ? "password" : "text";
      byId("toggle-api-key").textContent = visible ? "显示" : "隐藏";
      byId("toggle-api-key").setAttribute("aria-label", visible ? "显示 API Key" : "隐藏 API Key");
    });
    byId("refresh-view").addEventListener("click", async () => {
      const button = byId("refresh-view");
      await busy(button, async () => {
        if (state.currentView === "knowledge") await refreshDocuments();
        else if (state.currentView === "operations") await refreshOperations();
        else await refreshHealth();
      });
    });
    configureDragAndDrop();
  }

  function init() {
    bindEvents();
    setView(currentHashView());
    updateCharacterCount();
    void refreshHealth({ quiet: true });
  }

  init();
})();
