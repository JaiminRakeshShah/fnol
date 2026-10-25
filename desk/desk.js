(() => {
  "use strict";

  const state = {
    user: null,
    nav: "queue",
    caseId: null,
    caseView: null,
  };

  const el = {
    loginView: document.getElementById("login-view"),
    deskView: document.getElementById("desk-view"),
    loginForm: document.getElementById("login-form"),
    loginError: document.getElementById("login-error"),
    userName: document.getElementById("user-name"),
    userTeam: document.getElementById("user-team"),
    logoutBtn: document.getElementById("logout-btn"),
    refreshBtn: document.getElementById("refresh-btn"),
    viewTitle: document.getElementById("view-title"),
    viewSubtitle: document.getElementById("view-subtitle"),
    queuePanel: document.getElementById("queue-panel"),
    casePanel: document.getElementById("case-panel"),
    auditPanel: document.getElementById("audit-panel"),
    queueBody: document.getElementById("queue-body"),
    queueEmpty: document.getElementById("queue-empty"),
    auditBody: document.getElementById("audit-body"),
    auditEmpty: document.getElementById("audit-empty"),
    backBtn: document.getElementById("back-btn"),
    identityRow: document.getElementById("identity-row"),
    flagRow: document.getElementById("flag-row"),
    decisionEyebrow: document.getElementById("decision-eyebrow"),
    decisionBody: document.getElementById("decision-body"),
    summaryEyebrow: document.getElementById("summary-eyebrow"),
    summaryBody: document.getElementById("summary-body"),
    paneActions: document.getElementById("pane-actions"),
    toast: document.getElementById("toast"),
    rejectDialog: document.getElementById("reject-dialog"),
    rejectForm: document.getElementById("reject-form"),
    rejectReason: document.getElementById("reject-reason"),
    rejectCancel: document.getElementById("reject-cancel"),
    navAudit: document.getElementById("nav-audit"),
  };

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function api(path, options = {}) {
    const opts = {
      credentials: "same-origin",
      headers: { Accept: "application/json", ...(options.headers || {}) },
      ...options,
    };
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json; charset=utf-8";
      opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(path, opts);
    let data = null;
    const text = await resp.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch {
        data = { message: text };
      }
    }
    if (!resp.ok) {
      const err = new Error((data && (data.message || data.error)) || `HTTP ${resp.status}`);
      err.status = resp.status;
      err.data = data;
      throw err;
    }
    return data;
  }

  function showToast(message) {
    el.toast.textContent = message;
    el.toast.hidden = false;
    clearTimeout(showToast._t);
    showToast._t = setTimeout(() => {
      el.toast.hidden = true;
    }, 3200);
  }

  function setNavActive(name) {
    document.querySelectorAll(".rail-link").forEach((btn) => {
      btn.classList.toggle("is-active", btn.dataset.nav === name);
    });
  }

  function showLogin() {
    el.loginView.hidden = false;
    el.deskView.hidden = true;
  }

  function showDesk() {
    el.loginView.hidden = true;
    el.deskView.hidden = false;
    el.userName.textContent = state.user.display_name;
    el.userTeam.textContent = `${state.user.team} team`;
  }

  function formatWhen(iso) {
    if (!iso) return "—";
    try {
      const d = new Date(iso);
      if (Number.isNaN(d.getTime())) return iso;
      return d.toISOString().replace("T", " ").replace(/\.\d+Z$/, "Z");
    } catch {
      return iso;
    }
  }

  function statusClass(status) {
    const s = String(status || "none").toLowerCase();
    if (s === "pending" || s === "in_review") return "status-pending";
    if (s === "approved") return "status-approved";
    if (s === "rejected") return "status-rejected";
    return "status-none";
  }

  function renderFlags(flags) {
    if (!flags || !flags.length) return "";
    return `<div class="flag-list">${flags
      .map(
        (f) =>
          `<span class="flag-chip tone-${esc(f.tone || "watch")}">${esc(f.label)}</span>`
      )
      .join("")}</div>`;
  }

  async function loadQueue() {
    const data = await api("/api/queue");
    const rows = data.cases || [];
    el.queueBody.innerHTML = "";
    el.queueEmpty.hidden = rows.length > 0;
    for (const row of rows) {
      const tr = document.createElement("tr");
      tr.tabIndex = 0;
      tr.innerHTML = `
        <td class="mono">${esc(row.case_id)}</td>
        <td class="mono">${esc(row.policy_number || "—")}</td>
        <td>${esc(row.classification || "—")}</td>
        <td>${esc(row.routing || "—")}</td>
        <td>${renderFlags(row.flags)}</td>
        <td><span class="status-pill ${statusClass(row.review_status)}">${esc(row.review_status)}</span></td>
        <td class="mono">${esc(formatWhen(row.waiting_since))}</td>
      `;
      tr.addEventListener("click", () => openCase(row.case_id));
      tr.addEventListener("keydown", (ev) => {
        if (ev.key === "Enter" || ev.key === " ") {
          ev.preventDefault();
          openCase(row.case_id);
        }
      });
      el.queueBody.appendChild(tr);
    }
  }

  async function loadAudit() {
    const data = await api("/api/audit");
    const events = data.events || [];
    el.auditBody.innerHTML = "";
    el.auditEmpty.hidden = events.length > 0;
    for (const event of events) {
      const tr = document.createElement("tr");
      const detail = esc(JSON.stringify(event.detail || {}));
      tr.innerHTML = `
        <td class="mono">${esc(event.seq)}</td>
        <td class="mono">${esc(formatWhen(event.at))}</td>
        <td>${esc(event.event)}</td>
        <td class="mono">${esc(event.case_id || "—")}</td>
        <td class="mono">${detail}</td>
      `;
      el.auditBody.appendChild(tr);
    }
  }

  function identityItem(label, value, mono) {
    return `<div class="identity-item">
      <span class="label">${esc(label)}</span>
      <span class="value${mono ? " mono" : ""}">${esc(value ?? "—")}</span>
    </div>`;
  }

  function renderDecision(decision) {
    const facts = decision.facts || {};
    const factOrder = [
      ["policy_number", "Policy"],
      ["vehicle_id", "Vehicle"],
      ["incident_timestamp", "Incident"],
      ["injury_reported", "Injury"],
      ["vehicle_drivable", "Drivable"],
      ["referral_indicator", "Referral"],
      ["selected_policy_version", "Policy version"],
      ["duplicate_delivery", "Duplicate delivery"],
    ];
    const factHtml = factOrder
      .map(
        ([key, label]) => `<div class="fact-cell">
        <span class="label">${esc(label)}</span>
        <span class="value">${esc(facts[key] ?? "Unknown")}</span>
      </div>`
      )
      .join("");

    const reasons =
      decision.route_reasons && decision.route_reasons.length
        ? `<ul>${decision.route_reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul>`
        : `<p>No manual-review, urgency, or specialist trigger applies.</p>`;

    let contentCheck = "";
    if (decision.content_check_notes && decision.content_check_notes.length) {
      contentCheck = `<div class="section-block content-check">
        <h3>Content check</h3>
        <ul>${decision.content_check_notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul>
      </div>`;
    }

    let conflicts = "";
    if (decision.conflicts && decision.conflicts.length) {
      conflicts = `<div class="section-block">
        <h3>Conflicts</h3>
        <ul>${decision.conflicts.map((c) => `<li>${esc(c)}</li>`).join("")}</ul>
      </div>`;
    }

    let missing = "";
    if (decision.missing_information && decision.missing_information.length) {
      const questions = decision.follow_up_questions || [];
      const qByField = Object.fromEntries(
        questions.filter((q) => q && q.field).map((q) => [q.field, q.question])
      );
      missing = `<div class="section-block">
        <h3>Missing information</h3>
        <ul>${decision.missing_information
          .map((field) => {
            const q = qByField[field];
            return `<li><code>${esc(field)}</code>${
              q
                ? `<div class="draft-question"><span class="tag">Draft customer communication</span>${esc(q)}</div>`
                : ""
            }</li>`;
          })
          .join("")}</ul>
      </div>`;
    }

    const policyNote = decision.policy_note
      ? `<p>${esc(decision.policy_note)}</p>`
      : `<p>Selected version: <strong>${esc(
          decision.policy_version == null ? "null — person must review" : decision.policy_version
        )}</strong></p>`;

    const citations = (decision.citations || [])
      .map(
        (c) => `<article class="citation">
        <div class="citation-meta">
          <span class="mono">${esc(c.source_id || "—")}</span>
          <span>${esc(c.claim || "")}</span>
        </div>
        <blockquote>${esc(c.quote || "")}</blockquote>
      </article>`
      )
      .join("");

    return `
      <div class="section-block">
        <h3>Recommendation</h3>
        <p><strong>${esc(decision.classification || "—")}</strong> · route
          <strong>${esc(decision.routing || "—")}</strong>
          under <code>${esc(decision.route_rule || "AUTO-TRIAGE-01")}</code></p>
        ${reasons}
      </div>
      <div class="section-block">
        <h3>Facts</h3>
        <div class="fact-grid">${factHtml}</div>
      </div>
      ${contentCheck}
      ${conflicts}
      ${missing}
      <div class="section-block">
        <h3>Policy</h3>
        ${policyNote}
        <p class="mono" style="margin-top:0.4rem;color:var(--ink-muted)">${esc(
          (decision.policy_ids || []).join(", ") || "—"
        )}</p>
      </div>
      <div class="section-block">
        <h3>Citations</h3>
        ${citations || "<p>No citations attached.</p>"}
      </div>
    `;
  }

  function renderSummary(summary) {
    if (!summary.available) {
      return `<p class="summary-empty">${esc(summary.empty_reason || "No handler summary.")}</p>
        <p class="boundary">${esc(summary.boundary || "")}</p>`;
    }
    const paragraphs = String(summary.text)
      .split(/\n+/)
      .filter(Boolean)
      .map((p) => `<p>${esc(p)}</p>`)
      .join("");
    return `${paragraphs}<p class="boundary">${esc(summary.boundary || "")}</p>`;
  }

  function renderActions(view) {
    const actions = view.actions || {};
    const team = view.team;
    const parts = [];

    if (actions.can_send) {
      parts.push(`<div class="action-row">
        <button type="button" class="btn btn-harbor" id="send-btn">Send to handlers</button>
      </div>
      <p class="action-note">Submits this exact draft into pending review. Sending does not approve.</p>`);
    }

    if (team === "handlers") {
      parts.push(`<div class="action-row">
        <button type="button" class="btn btn-harbor" id="accept-btn" ${
          actions.can_accept ? "" : "disabled"
        }>${esc(actions.accept_label || "Accept")}</button>
        <button type="button" class="btn btn-rust" id="reject-btn" ${
          actions.can_reject ? "" : "disabled"
        }>Reject</button>
      </div>
      <p class="action-note">Accepting records this exact draft so the intake record may be created. It is not a coverage decision.</p>`);
      if (!actions.can_accept) {
        parts.push(
          `<p class="action-note">Accept and reject require a pending review whose hash matches this draft.</p>`
        );
      }
    } else if (team === "analysts") {
      parts.push(`<p class="action-note">${esc(actions.handler_only_note)}</p>`);
    } else if (team === "security") {
      parts.push(`<p class="action-note">Security has read-only access. No accept, reject, or file actions.</p>`);
    }

    el.paneActions.innerHTML = parts.join("");

    const sendBtn = document.getElementById("send-btn");
    if (sendBtn) sendBtn.addEventListener("click", onSend);
    const acceptBtn = document.getElementById("accept-btn");
    if (acceptBtn) acceptBtn.addEventListener("click", onAccept);
    const rejectBtn = document.getElementById("reject-btn");
    if (rejectBtn) {
      rejectBtn.addEventListener("click", () => {
        el.rejectReason.value = "";
        el.rejectDialog.showModal();
      });
    }
  }

  async function openCase(caseId) {
    state.caseId = caseId;
    state.nav = "case";
    const view = await api(`/api/cases/${encodeURIComponent(caseId)}`);
    state.caseView = view;
    el.queuePanel.hidden = true;
    el.auditPanel.hidden = true;
    el.casePanel.hidden = false;
    el.viewTitle.textContent = caseId;
    el.viewSubtitle.textContent = `Draft ${view.short_hash || ""} · revision ${
      view.input_revision ?? "—"
    }`;
    setNavActive("queue");

    const id = view.identity || {};
    el.identityRow.innerHTML = [
      identityItem("Case", id.case_id, true),
      identityItem("Policy", id.policy_number, true),
      identityItem("Vehicle", id.vehicle_id, true),
      identityItem("Incident", id.incident_timestamp, true),
      identityItem("Loss", id.classification),
      identityItem("Route", id.routing),
      identityItem("Review", id.review_status),
    ].join("");

    el.flagRow.innerHTML = (view.flags || [])
      .map(
        (f) =>
          `<span class="flag-chip tone-${esc(f.tone || "watch")}">${esc(f.label)}</span>`
      )
      .join("");

    el.decisionEyebrow.textContent = view.decision.eyebrow || "Deterministic · AUTO-TRIAGE-01";
    el.decisionBody.innerHTML = renderDecision(view.decision);
    el.summaryEyebrow.textContent = view.summary.eyebrow || "Draft for the handler";
    el.summaryBody.innerHTML = renderSummary(view.summary);
    renderActions(view);
  }

  async function showQueue() {
    state.nav = "queue";
    state.caseId = null;
    el.casePanel.hidden = true;
    el.auditPanel.hidden = true;
    el.queuePanel.hidden = false;
    el.viewTitle.textContent = "Queue";
    const team = state.user?.team || "";
    const sub =
      team === "handlers"
        ? "Drafts awaiting handler review"
        : team === "security"
          ? "Cases with watch conditions"
          : "Prepared drafts for your team";
    el.viewSubtitle.textContent = sub;
    setNavActive("queue");
    await loadQueue();
  }

  async function showAudit() {
    state.nav = "audit";
    state.caseId = null;
    el.casePanel.hidden = true;
    el.queuePanel.hidden = true;
    el.auditPanel.hidden = false;
    el.viewTitle.textContent = "Audit";
    el.viewSubtitle.textContent = "Mock enterprise audit log";
    setNavActive("audit");
    await loadAudit();
  }

  async function onSend() {
    if (!state.caseId) return;
    try {
      const result = await api(`/api/cases/${encodeURIComponent(state.caseId)}/send`, {
        method: "POST",
        body: {},
      });
      showToast(
        result.already_pending
          ? `Already pending as ${result.review_id}`
          : `Sent to handlers · ${result.review_id}`
      );
      await openCase(state.caseId);
    } catch (err) {
      showToast(err.message || "Send failed");
    }
  }

  async function onAccept() {
    if (!state.caseId) return;
    try {
      const result = await api(`/api/cases/${encodeURIComponent(state.caseId)}/accept`, {
        method: "POST",
        body: {},
      });
      showToast(`Accepted by ${result.reviewer}`);
      await openCase(state.caseId);
    } catch (err) {
      showToast(err.message || "Accept failed");
    }
  }

  async function onRejectSubmit(ev) {
    ev.preventDefault();
    if (!state.caseId) return;
    const reason = el.rejectReason.value.trim();
    if (!reason) return;
    try {
      const result = await api(`/api/cases/${encodeURIComponent(state.caseId)}/reject`, {
        method: "POST",
        body: { reason },
      });
      el.rejectDialog.close();
      showToast(`Rejected by ${result.reviewer}`);
      await openCase(state.caseId);
    } catch (err) {
      showToast(err.message || "Reject failed");
    }
  }

  async function boot() {
    el.loginForm.addEventListener("submit", async (ev) => {
      ev.preventDefault();
      el.loginError.hidden = true;
      const fd = new FormData(el.loginForm);
      try {
        const data = await api("/api/login", {
          method: "POST",
          body: {
            username: fd.get("username"),
            password: fd.get("password"),
          },
        });
        state.user = data.user;
        showDesk();
        await showQueue();
      } catch (err) {
        el.loginError.textContent = err.message || "Sign-in failed";
        el.loginError.hidden = false;
      }
    });

    el.logoutBtn.addEventListener("click", async () => {
      try {
        await api("/api/logout", { method: "POST", body: {} });
      } catch {
        /* ignore */
      }
      state.user = null;
      showLogin();
    });

    el.refreshBtn.addEventListener("click", async () => {
      try {
        if (state.nav === "case" && state.caseId) await openCase(state.caseId);
        else if (state.nav === "audit") await showAudit();
        else await showQueue();
      } catch (err) {
        showToast(err.message || "Refresh failed");
      }
    });

    el.backBtn.addEventListener("click", () => {
      showQueue().catch((err) => showToast(err.message));
    });

    document.querySelectorAll(".rail-link").forEach((btn) => {
      btn.addEventListener("click", () => {
        const nav = btn.dataset.nav;
        if (nav === "audit") showAudit().catch((err) => showToast(err.message));
        else showQueue().catch((err) => showToast(err.message));
      });
    });

    el.rejectCancel.addEventListener("click", () => el.rejectDialog.close());
    el.rejectForm.addEventListener("submit", onRejectSubmit);

    try {
      const data = await api("/api/me");
      state.user = data.user;
      showDesk();
      await showQueue();
    } catch {
      showLogin();
    }
  }

  boot();
})();
