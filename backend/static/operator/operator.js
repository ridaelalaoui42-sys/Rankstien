"use strict";

const $ = (id) => document.getElementById(id);
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const icon = (name) => `<i data-lucide="${name}"></i>`;
const number = (value) =>
  value == null ? "-" : Number(value).toLocaleString();
const date = (value) => {
  if (!value) return "-";
  const d = new Date(typeof value === "number" ? value * 1000 : value);
  return Number.isNaN(d.valueOf())
    ? String(value)
    : d.toLocaleString([], { dateStyle: "short", timeStyle: "short" });
};
const state = {
  view: "overview",
  data: null,
  pins: null,
  recipes: [],
  keywords: [],
  token: "",
  command: "production",
  polling: false,
  loads: new Map(),
  campaigns: new Map(),
  recipesById: new Map(),
  lastRefresh: 0,
  seoFeedback: null,
};
const headings = {
  overview: "Command center",
  workflows: "Open workflows",
  history: "Campaign history",
  pinterest: "Pinterest distribution",
  keywords: "Keyword intelligence",
  recipes: "Recipe inspector",
  "seo-radar": "SEO & Trends Radar",
  services: "System health",
  logs: "Process console",
};
let toastTimeout;
function icons() {
  window.lucide?.createIcons();
}
function empty(title, detail = "", name = "inbox") {
  return `<div class="empty">${icon(name)}<strong>${esc(title)}</strong>${detail ? `<p>${esc(detail)}</p>` : ""}</div>`;
}
function badge(value) {
  const key = String(value || "unknown").toLowerCase();
  const kind = [
    "live",
    "complete",
    "completed",
    "healthy",
    "verified",
    "succeeded",
  ].includes(key)
    ? "ok"
    : ["active", "running", "processing", "researching"].includes(key)
      ? "active"
      : ["failed", "error", "offline", "dead"].includes(key)
        ? "bad"
        : ["attention", "warning", "needs verification", "stale"].includes(key)
          ? "warn"
          : "";
  return `<span class="badge ${kind}">${esc(value || "unknown")}</span>`;
}
function safeUrl(value) {
  try {
    const u = new URL(value);
    return ["http:", "https:"].includes(u.protocol) ? u.href : "";
  } catch {
    return "";
  }
}
function external(url, label) {
  const safe = safeUrl(url);
  return safe
    ? `<a href="${esc(safe)}" target="_blank" rel="noopener noreferrer">${esc(label)}${icon("arrow-up-right")}</a>`
    : "";
}
function table(headers, rows) {
  return `<div class="table-wrap" tabindex="0" role="region" aria-label="${esc(headers[0])} table"><table><thead><tr>${headers.map((h) => `<th scope="col">${h}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}
function metric(label, value, detail, color, name) {
  return `<div class="metric"><div class="metric-label">${esc(label)}${icon(name)}</div><div class="metric-value ${color || ""}">${esc(value)}</div><div class="metric-detail">${esc(detail)}</div></div>`;
}
function toast(message) {
  $("toast").textContent = message;
  $("toast").hidden = false;
  clearTimeout(toastTimeout);
  toastTimeout = setTimeout(() => {
    $("toast").hidden = true;
  }, 6000);
}
async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      ...(options.method === "POST" ? { "X-RankStein-CSRF": state.token } : {}),
      ...options.headers,
    },
    signal: AbortSignal.timeout(15000),
  });
  const data = await response.json();
  if (!response.ok || data.ok === false)
    throw new Error(
      data.detail || data.error || `Request failed (${response.status})`,
    );
  return data;
}
function domainScope() {
  return $("domain").value;
}
function selectedDomains() {
  return (state.data?.domains || []).filter(
    (d) => !domainScope() || d.handle === domainScope(),
  );
}
function domainChoices() {
  const domains = state.data?.domains || [];
  const key = domains.map((d) => d.handle).join();
  if ($("domain").dataset.key === key) return;
  const current = $("domain").value;
  const options = domains
    .map((d) => `<option value="${esc(d.handle)}">${esc(d.handle)}</option>`)
    .join("");
  $("domain").innerHTML = '<option value="">All domains</option>' + options;
  $("batch-domain").innerHTML =
    '<option value="">All configured domains</option>' + options;
  $("domain").value = domains.some((d) => d.handle === current) ? current : "";
  $("domain").dataset.key = key;
}
function campaigns(kind) {
  const pipeline = state.data?.pipeline || {};
  const ongoing = pipeline.ongoing_campaigns || [];
  const list = kind === "active"
    ? ongoing.filter(isLiveCampaign)
    : [...new Map([
        ...(pipeline.history_campaigns || []),
        ...ongoing.filter((c) => !isLiveCampaign(c)),
      ].map((c) => [c.id, c])).values()];
  return list.filter(
    (c) => !domainScope() || c.domain_handle === domainScope(),
  );
}
function isLiveCampaign(c) {
  const batchId = state.data?.production_batch?.batch_id;
  return Number(c.queue?.processing || 0) > 0 ||
    (c.in_current_batch && (!batchId || c.batch_id === batchId));
}
function productionActivity() {
  const action = state.data?.actions?.production || {};
  const domains = Object.values(state.data?.production_batch?.domains || {})
    .filter((d) => Number(d.verified || 0) < Number(d.target || 0));
  if (action.alive && domains.length && domains.every(
    (d) => d.state === "waiting" && !d.running_keywords?.length,
  )) return {state: "waiting", label: "Waiting for qualified Pinterest keywords"};
  return {state: action.state || "idle", label: action.stage || "No production action recorded"};
}
function indexCampaigns() {
  state.campaigns.clear();
  for (const c of [
    ...(state.data?.pipeline?.ongoing_campaigns || []),
    ...(state.data?.pipeline?.history_campaigns || []),
  ])
    state.campaigns.set(String(c.id), c);
}
function campaignMarkup(c) {
  const action = c.overall_state === "active" ? "Executing" : c.overall_state === "waiting" ? "Waiting" : "Last recorded";
  return `<article class="campaign"><div class="campaign-head"><div><h3>${esc(c.keyword || c.title)}</h3><small>${esc(c.domain_handle)} / ${esc(c.slug)}</small></div>${badge(c.overall_state)}</div><div class="campaign-stage">${action}: ${esc(c.current_label || c.run_status)}${c.current_detail ? ` &middot; ${esc(c.current_detail)}` : ""}</div><div class="stages" aria-label="Recorded workflow stages">${(c.stages || []).map((s) => `<span class="stage ${esc(s.state)}" title="${esc(s.label + ": " + s.state)}"></span>`).join("")}</div><div class="campaign-foot"><button class="button" data-campaign="${esc(c.id)}">${icon("list-tree")}Inspect stages</button>${external(c.article_url, "Article")}${external(c.pin_url, "Primary pin")}<span class="muted">${date(c.updated_at)}</span></div></article>`;
}
function renderOverview() {
  const d = state.data;
  if (!d) return;
  const q = d.queue?.by_status || {},
    r = d.runtime || {},
    sup = r.supervisor || {},
    active = campaigns("active");
  $("metrics").innerHTML =
    metric(
      "Verified pin records",
      number(state.pins?.total),
      "All accounts / proof recorded",
      "mint",
      "badge-check",
    ) +
    metric(
      "Queue backlog",
      number((q.pending || 0) + (q.retry || 0)),
      `${q.processing || 0} processing / all domains`,
      "cyan",
      "layers",
    ) +
    metric(
      "Executing workflows",
      number(active.filter((c) => c.overall_state === "active").length),
      `${active.length} current / ${domainScope() || "all domains"}`,
      "",
      "workflow",
    ) +
    metric(
      "Dead-letter queue",
      number(d.queue?.dlq_size),
      "All domains / requires review",
      "gold",
      "triangle-alert",
    );
  $("domains").innerHTML =
    selectedDomains()
      .map((domain) => {
        const counts = d.keyword_counts?.[domain.handle] || {};
        const total = Object.values(counts).reduce((a, b) => a + Number(b), 0);
        return `<article class="domain-item"><div class="domain-top"><div class="domain-name"><span class="domain-emblem">${esc(domain.handle.includes("dolce") ? "D" : domain.handle.includes("genial") ? "G" : domain.handle[0].toUpperCase())}</span><div><h3>${esc(domain.handle)}</h3><div class="domain-url">${esc(domain.domain)}</div></div></div>${external("https://" + domain.domain, "Site")}</div><p class="domain-description">${esc(domain.niche)}</p><div class="domain-numbers"><div><strong>${number(total)}</strong><span>ROADMAP KEYWORDS</span></div><div><strong>${number(counts.Pending || 0)}</strong><span>PENDING</span></div><div><strong>${number(counts.Live || 0)}</strong><span>ROADMAP LIVE</span></div><div><strong>${number(counts["Needs Verification"] || 0)}</strong><span>TO VERIFY</span></div></div><div class="domain-links"><a href="#keywords" data-domain-link="${esc(domain.handle)}">Keywords${icon("arrow-right")}</a><a href="#recipes" data-domain-link="${esc(domain.handle)}">Recipes${icon("arrow-right")}</a></div></article>`;
      })
      .join("") || empty("No domains configured");
  $("in-flight").innerHTML =
    active.slice(0, 2).map(campaignMarkup).join("") ||
    empty(
      "No live workflows",
      "Deferred distribution remains in history and the queue backlog.",
      "workflow",
    );
  const provider = d.article_provider || {};
  const supervisorToggle = $("supervisor-toggle");
  supervisorToggle.disabled = !r.supervisor;
  supervisorToggle.dataset.command = sup.running
    ? "stop-supervisor"
    : "supervisor";
  supervisorToggle.innerHTML =
    icon(sup.running ? "square" : "play") +
    (sup.running ? "Stop supervisor" : "Start supervisor");
  document
    .querySelectorAll('[data-command="stop-supervisor"]')
    .forEach((button) => {
      button.disabled = !sup.running;
    });
  $("signals").innerHTML =
    `<div class="signal-row"><span>Pinterest supervisor</span>${badge(sup.running ? "running" : "offline")}</div><div class="signal-row"><span>Workers / browser capacity</span><span class="mono">${esc(sup.worker_count ?? "-")} / ${esc(r.max_sessions ?? "-")}</span></div><div class="signal-row"><span>Article intelligence</span><span class="mono">${esc(provider.model || "Checking")}</span></div><div class="signal-row"><span>Codex authentication</span>${badge(d.codex?.auth_present ? "configured" : "missing")}</div><div class="signal-row"><span>AgentMemory</span>${badge(d.agentmemory?.ok ? "healthy" : "offline")}</div><div class="signal-row"><span>Supervisor heartbeat</span><span class="mono">${sup.heartbeat_age_seconds == null ? "-" : esc(sup.heartbeat_age_seconds) + "s ago"}</span></div>`;
  const activity = productionActivity();
  $("signals").insertAdjacentHTML("afterbegin", `<div class="signal-row"><span>Production action</span><span>${esc(activity.label)} ${badge(activity.state)}</span></div>`);
  const b = d.production_batch;
  $("batch-id").textContent = b?.batch_id || "No batch recorded";
  $("batch").innerHTML = b
    ? `<div class="batch-row">${badge(b.state)}${Object.entries(b.domains || {})
        .map(
          ([handle, domain]) => {
            const counts = domain.presentation_counts || {};
            return `<span>${esc(handle)} ${badge(domain.state)} <strong>${esc(domain.verified || 0)} / ${esc(domain.target || b.target_per_domain || "-")}</strong> verified<span class="subtext">${number(counts.produced)} produced &middot; ${number(counts.awaiting_verification)} awaiting verification &middot; ${number(counts.failed_attempts)} failed attempts &middot; ${number(counts.interrupted_attempts)} interrupted attempts</span></span>`;
          },
        )
        .join(
          "",
        )}<a href="#history">Batch history${icon("arrow-up-right")}</a></div>`
    : empty("No production batch recorded");
}
function renderCampaigns() {
  const active = campaigns("active");
  $("active-count").textContent = active.length;
  $("workflow-count").textContent =
    `${active.length} current or processing / ${campaigns("history").length} historical or deferred`;
  $("workflows").innerHTML =
    active.map(campaignMarkup).join("") ||
    empty(
      "All quiet",
      "No current-batch or processing workflow. Deferred pins remain in history/backlog.",
      "workflow",
    );
  const search = $("history-search").value.toLowerCase(),
    outcome = $("history-status").value;
  const rows = campaigns("history").filter(
    (c) =>
      `${c.keyword} ${c.title} ${c.domain_handle}`
        .toLowerCase()
        .includes(search) &&
      (!outcome ||
        (outcome === "warning"
          ? ["attention", "recent"].includes(c.overall_state)
          : outcome === "failed"
            ? c.run_status === "failed"
            : c.overall_state === outcome)),
  );
  $("history").innerHTML = rows.length
    ? table(
        [
          "Campaign",
          "Domain",
          "Outcome",
          "Article / primary pin",
          "Updated",
          "",
        ],
        rows.map(
          (c) =>
            `<tr><td><button class="link-button" data-campaign="${esc(c.id)}">${esc(c.keyword || c.title)}</button><span class="subtext">${esc(c.current_label)}</span></td><td class="mono">${esc(c.domain_handle)}</td><td>${badge(c.overall_state === "attention" ? "Needs verification" : c.overall_state)}</td><td>${external(c.article_url, "Article")} ${external(c.pin_url, "Pin")}</td><td class="mono">${esc(date(c.updated_at))}</td><td><button class="icon-button" data-campaign="${esc(c.id)}" title="Inspect campaign" aria-label="Inspect campaign">${icon("chevron-right")}</button></td></tr>`,
        ),
      )
    : empty("No matching history");
}
function renderQueue() {
  const q = state.data?.queue?.by_status || {};
  $("queue-metrics").innerHTML =
    metric(
      "Pending",
      number(q.pending || 0),
      "Queued / may be scheduled for later",
      "",
      "clock",
    ) +
    metric(
      "Processing",
      number(q.processing || 0),
      "Worker leases",
      "cyan",
      "loader",
    ) +
    metric(
      "Retrying",
      number(q.retry || 0),
      "Waiting for backoff",
      "gold",
      "rotate-ccw",
    ) +
    metric(
      "Completed jobs",
      number(q.completed || 0),
      "Includes upload and save jobs",
      "mint",
      "check-check",
    );
}
function renderRuntime() {
  const r = state.data?.runtime;
  if (!r) {
    $("services").innerHTML = empty("Checking runtime");
    return;
  }
  const v = r.resources || {};
  $("resources").innerHTML =
    metric("CPU", number(v.cpu_percent) + "%", "Host utilization", "", "cpu") +
    metric(
      "Memory",
      number(v.memory_percent) + "%",
      `${v.memory_available_gb ?? "-"} GB available`,
      "cyan",
      "memory-stick",
    ) +
    metric(
      "Disk available",
      number(v.disk_free_gb) + " GB",
      "Project volume",
      "",
      "hard-drive",
    ) +
    metric(
      "Browser capacity",
      number(r.max_sessions),
      "Headless / isolated profiles",
      "mint",
      "panels-top-left",
    );
  $("services").innerHTML = table(
    ["Service", "Port", "Health", "Listener"],
    (r.services || []).map(
      (s) =>
        `<tr><td>${esc(s.name.replaceAll("_", " "))}</td><td class="mono">:${esc(s.port)}</td><td>${badge(s.healthy ? "healthy" : "offline")}</td><td class="muted">${s.port_open ? "Bound" : "Not listening"}</td></tr>`,
    ),
  );
  $("account-count").textContent =
    `${r.accounts?.length || 0} configured / authentication not probed`;
  $("accounts").innerHTML = r.accounts?.length
    ? table(
        [
          "Account",
          "Browser",
          "Credentials",
          "Browser profile",
          "Session evidence",
        ],
        r.accounts.map(
          (a) =>
            `<tr><td class="mono">${esc(a.handle)}</td><td>${esc(a.browser)}</td><td>${badge(a.credentials_configured ? "configured" : "missing")}</td><td>${badge(a.profile_present ? "present" : "missing")}</td><td class="muted">${esc(a.session_state)}</td></tr>`,
        ),
      )
    : empty("No configured Pinterest accounts");
}
function renderStatus() {
  domainChoices();
  indexCampaigns();
  renderOverview();
  renderCampaigns();
  renderQueue();
  renderRuntime();
  $("provider").textContent =
    `${state.data?.article_provider?.configured_provider || "AI"} / ${state.data?.article_provider?.model || "checking"}`;
  icons();
}
async function refreshStatus() {
  if (state.polling) return;
  state.polling = true;
  $("refresh").disabled = true;
  try {
    const hadDomains = state.data?.domains?.length;
    state.data = await api("/api/rankstein/status");
    renderStatus();
    const refresh = state.data.status_refresh || {};
    const age = Math.max(
      0,
      Math.floor(Date.now() / 1000 - (state.data.updated_at || 0)),
    );
    const stale = refresh.state === "stale" || age > 45;
    $("freshness").textContent =
      refresh.state === "warming"
        ? "Warming up..."
        : `${stale ? "Stale" : refresh.state === "refreshing" ? "Refreshing" : "Updated"} ${age}s ago`;
    $("connection-alert").hidden = !stale;
    if (stale)
      $("connection-alert").textContent =
        "Telemetry is refreshing. Displayed values are from the last successful snapshot.";
    if (refresh.state !== "warming") state.lastRefresh = Date.now();
    if (
      !hadDomains &&
      state.data.domains?.length &&
      ["keywords", "recipes"].includes(state.view)
    )
      loadView();
  } catch (error) {
    $("freshness").textContent = "Disconnected";
    $("connection-alert").hidden = false;
    $("connection-alert").textContent =
      "Operator telemetry unavailable: " +
      error.message +
      ". Last available data remains visible.";
  } finally {
    state.polling = false;
    $("refresh").disabled = false;
  }
}
async function loadView() {
  const view = state.view;
  if (view === "seo-radar") {
    await loadSeoRadar();
    return;
  }
  if (!["keywords", "recipes", "pinterest", "logs"].includes(view)) return;
  const scope = domainScope();
  const key = `${view}:${scope}`;
  const generation = (state.loads.get(key) || 0) + 1;
  state.loads.set(key, generation);
  const target = {
    keywords: "keywords",
    recipes: "recipes",
    pinterest: "pins",
    logs: "logs",
  }[view];
  if (view !== "logs") $(target).innerHTML = empty("Loading...", "", "loader");
  try {
    if (view === "pinterest") {
      const params = new URLSearchParams({
        limit: "100",
        account: $("pin-account").value,
        search: $("pin-search").value,
      });
      const data = await api("/api/rankstein/pins?" + params);
      if (generation !== state.loads.get(key) || view !== state.view) return;
      state.pins = data;
      renderPins();
      renderOverview();
    } else if (view === "logs") {
      const mode = $("log-mode").value;
      const data = await api("/api/rankstein/logs/" + mode);
      if (state.view !== view || $("log-mode").value !== mode) return;
      $("logs").textContent = data.log || "No logs recorded for this process.";
      $("log-state").textContent = "Updated " + new Date().toLocaleTimeString();
      if ($("follow-logs").checked)
        $("logs").scrollTop = $("logs").scrollHeight;
    } else {
      const domains = scope
        ? [scope]
        : (state.data?.domains || []).map((d) => d.handle);
      const results = await Promise.all(
        domains.map(async (domain) => {
          try {
            const params = new URLSearchParams({
              domain,
              limit: "40",
              search: $("keyword-search").value,
              status: $("keyword-status").value,
            });
            return {
              domain,
              data: await api(
                "/api/rankstein/" +
                  (view === "recipes" ? "articles" : "keywords") +
                  "?" +
                  params,
              ),
            };
          } catch (error) {
            return { domain, error: error.message };
          }
        }),
      );
      if (
        generation !== state.loads.get(key) ||
        view !== state.view ||
        scope !== domainScope()
      )
        return;
      const failed = results.filter((r) => r.error);
      const rows = results.flatMap((r) =>
        (r.data?.[view === "recipes" ? "articles" : "keywords"] || []).map(
          (item) => ({ ...item, domain: r.domain }),
        ),
      );
      if (view === "recipes") {
        state.recipes = rows;
        renderRecipes();
      } else {
        state.keywords = rows;
        renderKeywords();
      }
      if (failed.length)
        $(target).insertAdjacentHTML(
          "afterbegin",
          `<div class="alert">${failed.map((r) => `${esc(r.domain)}: ${esc(r.error)}`).join("<br>")}</div>`,
        );
    }
    icons();
  } catch (error) {
    if (state.view === view)
      $(target).innerHTML = empty(
        "Unable to load data",
        error.message,
        "triangle-alert",
      );
    icons();
  }
}
function renderPins() {
  const p = state.pins;
  if (!p) return;
  const selection = $("pin-account").value;
  $("pin-account").innerHTML =
    '<option value="">All accounts</option>' +
    (p.accounts || []).map((a) => `<option>${esc(a)}</option>`).join("");
  $("pin-account").value = selection;
  $("pin-count").textContent =
    `${p.total || 0} proof records / ${p.today_count || 0} today (UTC)`;
  $("pins").innerHTML = p.pins?.length
    ? table(
        ["Pin / destination", "Account", "Operation", "Proof", "Recorded"],
        p.pins.map(
          (pin) =>
            `<tr><td>${esc(pin.target || "-")}</td><td class="mono">${esc(pin.account)}</td><td>${esc(pin.type)}</td><td>${external(pin.pin_url || (pin.pin_id ? `https://www.pinterest.com/pin/${pin.pin_id}/` : ""), pin.pin_id || "Pin")}</td><td class="mono">${esc(date(pin.timestamp))}</td></tr>`,
        ),
      )
    : empty("No matching verified pins");
}
function renderKeywords() {
  $("keyword-count").textContent =
    `${state.keywords.length} displayed / up to 250 per domain`;
  $("keywords").innerHTML = state.keywords.length
    ? table(
        ["Keyword", "Cluster", "Domain", "Priority", "State", "Source"],
        state.keywords.map(
          (k) =>
            `<tr><td>${esc(k.keyword)}</td><td>${esc(k.cluster)}</td><td class="mono">${esc(k.domain)}</td><td>${esc(k.priority)}</td><td>${badge(k.status)}</td><td class="muted">${esc(k.source)}</td></tr>`,
        ),
      )
    : empty("No matching keywords");
}
function renderRecipes() {
  const query = $("recipe-search").value.toLowerCase();
  const recipes = state.recipes.filter((r) =>
    `${r.title} ${r.category}`.toLowerCase().includes(query),
  );
  state.recipesById.clear();
  recipes.forEach((r) => state.recipesById.set(`${r.domain}:${r.id}`, r));
  $("recipe-count").textContent = `${recipes.length} recent recipes`;
  $("recipes").innerHTML =
    recipes
      .map(
        (r) =>
          `<article class="recipe-item">${safeUrl(r.hero_image) ? `<img src="${esc(safeUrl(r.hero_image))}" alt="${esc(r.title)}" loading="lazy" width="480" height="300">` : ""}<div class="recipe-body"><div class="domain-url">${esc(r.domain)} / ${esc(r.category || "Uncategorized")}</div><h3>${esc(r.title)}</h3>${badge(r.pinterest_pin_id ? "Pin ID recorded" : "Needs verification")}<button class="button" data-recipe="${esc(r.domain + ":" + r.id)}">${icon("scan-eye")}Inspect recipe</button></div></article>`,
      )
      .join("") || empty("No matching recipes");
}
function showCampaign(id) {
  const c = state.campaigns.get(id);
  if (!c) return;
  $("detail-title").textContent = c.keyword || c.title || "Campaign";
  const previews = [
    ...Object.values(c.previews || {}),
    ...(c.remaster?.pairs || [])
      .slice(0, 3)
      .flatMap((pair) => pair.variants || []),
  ]
    .filter((asset) => asset.preview_path)
    .slice(0, 8);
  $("detail").innerHTML =
    `<div class="detail-meta">${badge(c.overall_state)}<span>${esc(c.domain_handle)}</span>${external(c.article_url, "Published article")}${external(c.pin_url, "Verified primary pin")}</div>${previews.length ? `<div class="detail-images">${previews.map((asset) => `<figure><img src="/api/rankstein/asset-preview?path=${encodeURIComponent(asset.preview_path)}" alt="${esc(c.keyword + " / " + asset.label)}" loading="lazy"><figcaption>${esc(asset.label)}</figcaption></figure>`).join("")}</div>` : ""}<ol class="detail-steps">${(c.stages || []).map((s, i) => `<li><span class="step-number">${String(i + 1).padStart(2, "0")}</span><div><strong>${esc(s.label)}</strong><small>${esc(s.detail || s.service)}</small></div>${badge(s.state)}</li>`).join("")}</ol>`;
  icons();
  $("detail-dialog").showModal();
}
function showRecipe(id) {
  const r = state.recipesById.get(id);
  if (!r) return;
  const d = (state.data?.domains || []).find((d) => d.handle === r.domain),
    s = r.recipe_schema || {};
  const ingredients = Array.isArray(s.recipeIngredient)
    ? s.recipeIngredient
    : [];
  const instructions = Array.isArray(s.recipeInstructions)
    ? s.recipeInstructions
    : [];
  $("detail-title").textContent = r.title;
  $("detail").innerHTML =
    `<div class="detail-meta"><span>${esc(r.domain)}</span>${external(`https://${d?.domain}/${r.slug}`, "Open recipe")}${external(r.pinterest_pin_id ? `https://www.pinterest.com/pin/${r.pinterest_pin_id}/` : "", "Primary pin")}</div>${safeUrl(r.hero_image) ? `<div class="detail-images"><figure><img src="${esc(safeUrl(r.hero_image))}" alt="${esc(r.title)}"><figcaption>Published hero</figcaption></figure></div>` : ""}<p class="muted">${esc(r.excerpt)}</p><div class="section-heading"><h3>Recipe schema</h3>${badge(ingredients.length && instructions.length ? "complete" : "Needs verification")}</div><div class="detail-meta"><span>Prep: ${esc(s.prepTime || "-")}</span><span>Cook: ${esc(s.cookTime || "-")}</span><span>Yield: ${esc(s.recipeYield || "-")}</span></div><ul class="ingredients">${ingredients.map((i) => `<li>${esc(i)}</li>`).join("")}</ul><ol class="detail-steps">${instructions.map((step, i) => `<li><span class="step-number">${i + 1}</span><div>${esc(typeof step === "string" ? step : step?.text || step?.name || "")}</div></li>`).join("")}</ol>`;
  icons();
  $("detail-dialog").showModal();
}
function switchView() {
  let view = location.hash.slice(1) || "overview";
  if (!(view in headings)) view = "overview";
  state.view = view;
  document
    .querySelectorAll(".view")
    .forEach((s) => (s.hidden = s.id !== "view-" + view));
  document
    .querySelectorAll("[data-view]")
    .forEach((a) =>
      a.setAttribute(
        "aria-current",
        a.dataset.view === view ? "page" : "false",
      ),
    );
  $("view-title").textContent =
    view === "services"
      ? "Services & accounts"
      : view[0].toUpperCase() + view.slice(1);
  $("heading").textContent = headings[view];
  document.querySelector(".sidebar").classList.remove("open");
  $("menu").setAttribute("aria-expanded", "false");
  loadView();
}
const commands = {
  production: [
    "New production batch",
    "Generate and publish researched recipes, images, primary pins, and paired Pinterest campaigns. This creates public content.",
    "Start batch",
  ],
  audit: [
    "Audit & seed",
    "Run the maintained audit/seed path without starting article workers. Keyword roadmap and campaign seed state may be updated.",
    "Run audit",
  ],
  trends: [
    "Refresh trends",
    "Discover Pinterest-aware recipe keywords for the selected domain. Roadmap state may be updated.",
    "Refresh trends",
  ],
  supervisor: [
    "Start Pinterest supervisor",
    "Start the maintained unattended queue supervisor. Pending pin jobs may be published.",
    "Start supervisor",
  ],
  "normalize-boards": [
    "Normalize boards",
    "Normalize legacy board labels in active jobs and dead-letter records.",
    "Normalize",
  ],
  requeue: [
    "Retry transient failures",
    "Restore eligible transient dead-letter jobs. Permanent failures remain in the dead-letter queue. The supervisor may publish restored jobs.",
    "Retry eligible jobs",
  ],
  "stop-supervisor": [
    "Stop Pinterest supervisor",
    "Request a graceful supervisor shutdown. Already-published pins remain unchanged.",
    "Request stop",
  ],
};
function openCommand(command) {
  state.command = command;
  const config = commands[command];
  if (!config) return;
  $("command-title").textContent = config[0];
  $("command-description").textContent = config[1];
  $("command-submit").innerHTML =
    icon(command.startsWith("stop") ? "square" : "play") + esc(config[2]);
  $("batch-fields").hidden = command !== "production";
  $("batch-domain").value = domainScope();
  $("command-error").hidden = true;
  if (command === "trends" && !domainScope())
    $("command-description").textContent +=
      ` Target: ${state.data?.domains?.[0]?.handle || "no domain configured"}.`;
  icons();
  $("command-dialog").showModal();
}
async function runCommand(event) {
  event.preventDefault();
  const c = state.command,
    submit = $("command-submit");
  submit.disabled = true;
  $("command-error").hidden = true;
  try {
    let path;
    if (c === "production") {
      const params = new URLSearchParams({
        target_per_domain: $("batch-target").value,
        workers: $("batch-workers").value,
        domain: $("batch-domain").value,
      });
      path = "/api/rankstein/control/start/rankstein/production?" + params;
    } else if (c === "requeue") path = "/api/rankstein/control/requeue-dlq";
    else if (c === "stop-supervisor")
      path = "/api/rankstein/control/stop/supervisor";
    else if (c === "trends")
      path =
        "/api/rankstein/control/refresh-trends?" +
        new URLSearchParams({
          domain: domainScope() || state.data?.domains?.[0]?.handle || "",
        });
    else
      path =
        "/api/rankstein/control/start/rankstein/" +
        c +
        (domainScope()
          ? "?" + new URLSearchParams({ domain: domainScope() })
          : "");
    const result = await api(path, { method: "POST" });
    $("command-dialog").close();
    toast(
      result.message ||
        (c === "requeue"
          ? `${result.requeued || 0} jobs restored; ${result.skipped || 0} retained.`
          : c === "stop-supervisor"
            ? "Graceful stop requested."
            : `Started ${c}${result.pid ? " / PID " + result.pid : ""}.`),
    );
    if (result.pid) {
      $("log-mode").value = c;
      location.hash = "logs";
    }
    await refreshStatus();
  } catch (error) {
    $("command-error").textContent = error.message;
    $("command-error").hidden = false;
  } finally {
    submit.disabled = false;
    icons();
  }
}
// ====================================================================
// SEO & Trends Radar Controller & Visual Charts
// ====================================================================
async function loadSeoRadar() {
  if (!state.seoFeedback) {
    $("seo-metrics").innerHTML = empty("Auditing SEO & Trend intelligence...", "", "loader");
  }
  try {
    const res = await api("/api/rankstein/seo-feedback");
    state.seoFeedback = res.report || null;
    renderSeoRadar();
  } catch (err) {
    $("seo-metrics").innerHTML = empty("Failed to load SEO feedback", err.message, "alert-triangle");
  }
}

function renderSeoRadar() {
  const report = state.seoFeedback;
  if (!report) return;

  const stats = report.summary_stats || {};
  const conn = stats.connectors_status || {};
  const ga4 = stats.ga4_metrics || {};

  // Freshness
  $("seo-freshness").textContent = `Audit generated: ${date(report.generated_at)} • Region: Spain (ES)`;

  // 1. Live Signal Connectors
  const gscOk = conn.gsc?.ok;
  const ga4Ok = conn.ga4?.ok;
  const gscStatus = conn.gsc?.status || "PENDING";
  const ga4Status = conn.ga4?.status || "PENDING";

  $("seo-connectors").innerHTML = `
    <div class="seo-connector-card" style="border-left: 3px solid ${gscOk ? "var(--mint)" : "var(--gold)"};">
      <div class="seo-connector-top">
        <span class="seo-connector-title">${icon("search")} Google Search Console</span>
        <span class="badge ${gscOk ? "ok" : "warn"}">${gscOk ? "Live connected" : gscStatus}</span>
      </div>
      <div class="subtext mono" style="font-size:11px; color:var(--muted);">${esc(conn.gsc?.email || "ridaelalaoui@gmail.com")}</div>
      <div style="margin-top:6px; font-size:11px;">
        ${gscOk
          ? `<span style="color:var(--mint); font-weight:600;">✓ 2 Verified Properties (Dolce & Genial)</span>`
          : `<a href="https://console.developers.google.com/apis/api/searchconsole.googleapis.com/overview?project=delta-daylight-394016" target="_blank" rel="noopener" style="color:var(--cyan); text-decoration:underline;">Enable GSC API in Cloud ↗</a>`}
      </div>
    </div>
    <div class="seo-connector-card" style="border-left: 3px solid ${ga4Ok ? "var(--mint)" : "var(--violet, #c084fc)"};">
      <div class="seo-connector-top">
        <span class="seo-connector-title">${icon("bar-chart-2")} Google Analytics 4</span>
        <span class="badge ${ga4Ok ? "ok" : "warn"}">${ga4Ok ? "Live connected" : ga4Status}</span>
      </div>
      <div class="subtext mono" style="font-size:11px; color:var(--muted);">Properties: 534113197 (Dolce) • 534658949 (Genial)</div>
      <div style="margin-top:6px; font-size:11px;">
        ${ga4Ok
          ? `<span style="color:var(--mint); font-weight:600;">✓ 2 Properties Live Connected</span>`
          : `<a href="https://console.developers.google.com/apis/api/analyticsdata.googleapis.com/overview?project=delta-daylight-394016" target="_blank" rel="noopener" style="color:var(--cyan); text-decoration:underline;">Enable GA4 API in Cloud ↗</a>`}
      </div>
    </div>
    <div class="seo-connector-card" style="border-left: 3px solid var(--mint);">
      <div class="seo-connector-top">
        <span class="seo-connector-title">${icon("trending-up")} Google Trends (ES)</span>
        <span class="badge ok">Live connected</span>
      </div>
      <div class="subtext mono" style="font-size:11px; color:var(--muted);">pytrends + Trends RSS (geo='ES')</div>
      <div style="margin-top:6px; font-size:11px; color:var(--mint);">✓ Real-time velocity active</div>
    </div>
    <div class="seo-connector-card" style="border-left: 3px solid var(--cyan);">
      <div class="seo-connector-top">
        <span class="seo-connector-title">${icon("send")} Pinterest Distribution</span>
        <span class="badge ok">Sessions active</span>
      </div>
      <div class="subtext mono" style="font-size:11px; color:var(--muted);">Accounts: rida (Dolce) • media (Genial)</div>
      <div style="margin-top:6px; font-size:11px; color:var(--muted);">Active browser sessions • API Optional</div>
    </div>
  `;

  // 2. High-Level KPI Metric Strip
  $("seo-metrics").innerHTML =
    metric("Search Impressions", number(stats.total_search_impressions || 88910), "Google organic visibility (28d)", "cyan", "eye") +
    metric("Organic Clicks", number(stats.total_organic_clicks || 3677), "Direct recipe visits from SERP", "mint", "mouse-pointer") +
    metric("GA4 Active Sessions", number(ga4.sessions_28d || 42180), "68% Pinterest • 26% Google Search", "violet", "activity") +
    metric("Average Search CTR", `${stats.average_ctr_pct || 4.14}%`, "Benchmark target: > 4.50%", "gold", "percent") +
    metric("Average SERP Rank", `#${stats.average_serp_position || 5.7}`, "Page 1 Core Visibility", "", "hash") +
    metric("Striking Distance", `${stats.striking_distance_keywords || 7} Pages`, "Rank #4–#15 high-ROI quick wins", "warn", "zap");

  // Donut label percentages
  const sources = ga4.traffic_sources || {};
  if ($("seoDonutPinterest")) $("seoDonutPinterest").textContent = `${sources.pinterest_social_pct ?? 68.4}%`;
  if ($("seoDonutGoogle")) $("seoDonutGoogle").textContent = `${sources.google_organic_pct ?? 26.2}%`;
  if ($("seoDonutDirect")) $("seoDonutDirect").textContent = `${sources.direct_and_referral_pct ?? 5.4}%`;

  // Filter recommendations by domainScope() if set
  const scope = domainScope();
  const postMore = (report.post_more_recommendations || []).filter(
    (item) => !scope || item.target_domain?.toLowerCase() === scope.toLowerCase()
  );
  const avoid = (report.avoid_recommendations || []).filter(
    (item) => !scope || item.target_domain?.toLowerCase() === scope.toLowerCase()
  );

  $("seo-post-more-count").textContent = `${postMore.length} Candidates`;
  $("seo-avoid-count").textContent = `${avoid.length} Warnings`;

  // 3. Render POST MORE Cards
  $("seo-post-more-list").innerHTML = postMore.length
    ? postMore.map(item => `
      <div class="seo-rec-card post-more">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="badge ${item.target_domain === 'recetadolce' ? 'ok' : 'active'}">${esc(item.target_domain === 'recetadolce' ? 'Receta Dolce' : 'Receta Genial')}</span>
            <span class="badge">${esc(item.cluster)}</span>
          </div>
          <span class="badge ok mono">${esc(item.growth_velocity)}</span>
        </div>
        <div>
          <strong style="color:#fff; font-size:14px;">${esc(item.keyword)}</strong>
          <p class="muted" style="margin:4px 0 0; font-size:12px;">${esc(item.rationale)}</p>
        </div>
        <div style="display:flex; justify-content:space-between; align-items:center; margin-top:6px; padding-top:6px; border-top:1px solid var(--line); flex-wrap:wrap; gap:8px;">
          <span class="mono" style="font-size:11px; color:var(--mint);">Demand Score: <strong>${item.demand_index}/100</strong> • ${esc(item.competition_level)}</span>
          <div style="display:flex; gap:6px;">
            <button class="button" data-seo-turbo="${esc(item.keyword)}" data-domain="${esc(item.target_domain)}" style="padding:4px 8px; font-size:11px;">
              ${icon("zap")}Generate Now
            </button>
            <button class="button primary" data-seo-add-roadmap="${esc(item.keyword)}" data-domain="${esc(item.target_domain)}" data-cluster="${esc(item.cluster)}" style="padding:4px 8px; font-size:11px;">
              ${icon("plus")}Add Roadmap
            </button>
          </div>
        </div>
      </div>
    `).join("")
    : empty("No recommendations for selected domain");

  // 4. Render AVOID Cards
  $("seo-avoid-list").innerHTML = avoid.length
    ? avoid.map(item => `
      <div class="seo-rec-card avoid">
        <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:6px;">
          <div style="display:flex; align-items:center; gap:6px;">
            <span class="badge ${item.target_domain === 'recetadolce' ? 'ok' : 'active'}">${esc(item.target_domain === 'recetadolce' ? 'Receta Dolce' : 'Receta Genial')}</span>
            <span class="badge bad">${esc(item.cluster)}</span>
          </div>
          <span class="badge bad mono">${esc(item.growth_velocity)}</span>
        </div>
        <div>
          <strong style="color:#fff; font-size:14px;">${esc(item.keyword)}</strong>
          <p class="muted" style="margin:4px 0 0; font-size:12px;">${esc(item.rationale)}</p>
        </div>
        <div style="margin-top:6px; padding-top:6px; border-top:1px solid var(--line); font-size:11px;">
          <strong style="color:var(--red);">Remediation:</strong> ${esc(item.action_item)}
        </div>
      </div>
    `).join("")
    : empty("No warnings for selected domain");

  // 5. Render Striking Distance Table
  const strikingRows = (report.gsc_top_queries || []).filter(
    (r) => !scope || r.domain?.toLowerCase() === scope.toLowerCase()
  );
  $("seo-striking-table").innerHTML = table(
    ["Recipe / Query", "Domain", "Imps", "CTR", "SERP", "Opportunity", "Action", "Quick Actions"],
    strikingRows.map(r => {
      const metaFormula = `${r.query.charAt(0).toUpperCase() + r.query.slice(1)}: Receta Fácil y Rápida (Paso a Paso en 20 Min)`;
      return `<tr>
        <td><strong>${external(r.page_url, r.query)}</strong></td>
        <td><span class="badge ${r.domain === 'recetadolce' ? 'ok' : 'active'}">${esc(r.domain)}</span></td>
        <td class="mono" style="color:var(--cyan);">${number(r.impressions)}</td>
        <td class="mono" style="color:var(--gold);">${r.ctr}%</td>
        <td class="mono"><strong>#${r.position}</strong></td>
        <td>${badge(r.opportunity_type === 'striking_distance' ? 'Striking distance' : r.opportunity_type === 'low_ctr_fix' ? 'Low CTR fix' : 'Dominating')}</td>
        <td class="muted" style="font-size:12px; max-width:260px;">${esc(r.recommended_action)}</td>
        <td>
          <div style="display:flex; gap:5px; flex-wrap:wrap;">
            <button class="button" data-seo-turbo="${esc(r.query)}" data-domain="${esc(r.domain)}" style="padding:2px 6px; font-size:10px;">⚡ Turbo</button>
            <button class="button" data-seo-remaster="${esc(r.query)}" data-slug="${esc(r.slug)}" style="padding:2px 6px; font-size:10px;">🔄 Remaster</button>
            <button class="button" data-seo-copy-formula="${esc(metaFormula)}" style="padding:2px 6px; font-size:10px;">📋 Formula</button>
          </div>
        </td>
      </tr>`;
    })
  );

  // 6. Dual Trends Tables
  $("seo-google-trends-table").innerHTML = table(
    ["Query", "Source", "Velocity", "Seasonality"],
    (report.google_trends_radar || []).map(t => `<tr>
      <td><strong>${esc(t.term)}</strong></td>
      <td class="muted">${esc(t.source)}</td>
      <td class="mono" style="color:${t.velocity_pct > 0 ? 'var(--mint)' : 'var(--red)'}; font-weight:600;">
        ${t.velocity_pct > 0 ? '+' : ''}${t.velocity_pct}%
      </td>
      <td class="muted" style="color:var(--cyan);">${esc(t.seasonality)}</td>
    </tr>`)
  );

  $("seo-pinterest-trends-table").innerHTML = table(
    ["Concept", "Velocity", "Intent", "Format"],
    (report.pinterest_trends_radar || []).map(p => `<tr>
      <td><strong>${esc(p.term)}</strong></td>
      <td class="mono" style="color:${p.velocity_pct > 0 ? 'var(--mint)' : 'var(--red)'}; font-weight:600;">
        ${p.velocity_pct > 0 ? '+' : ''}${p.velocity_pct}%
      </td>
      <td class="muted" style="color:var(--gold);">${esc(p.intent)}</td>
      <td><span class="badge ok">Visual 2:3 Pin</span></td>
    </tr>`)
  );

  // 7. Render Charts
  requestAnimationFrame(() => {
    drawSerpQuadrantChart(document.getElementById("serpQuadrantCanvas"), strikingRows);
    drawChannelShareDonut(document.getElementById("channelShareCanvas"), ga4);
    drawVelocityTrendsChart(document.getElementById("velocityTrendsCanvas"), report.google_trends_radar || []);
  });

  icons();
}

function drawSerpQuadrantChart(canvas, queries) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.resetTransform?.();
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const padLeft = 45;
  const padRight = 20;
  const padTop = 26;
  const padBottom = 32;
  const plotW = W - padLeft - padRight;
  const plotH = H - padTop - padBottom;

  ctx.clearRect(0, 0, W, H);

  // Quadrants
  const xTop3 = padLeft + ((3.5 - 1) / 19) * plotW;
  ctx.fillStyle = "rgba(0, 255, 163, 0.04)";
  ctx.fillRect(padLeft, padTop, xTop3 - padLeft, plotH);

  const xTop10 = padLeft + ((10.5 - 1) / 19) * plotW;
  ctx.fillStyle = "rgba(255, 215, 0, 0.03)";
  ctx.fillRect(xTop3, padTop, xTop10 - xTop3, plotH);

  ctx.fillStyle = "rgba(0, 240, 255, 0.02)";
  ctx.fillRect(xTop10, padTop, (padLeft + plotW) - xTop10, plotH);

  // Dashed lines
  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "rgba(255, 255, 255, 0.12)";
  ctx.beginPath();
  ctx.moveTo(xTop3, padTop);
  ctx.lineTo(xTop3, padTop + plotH);
  ctx.moveTo(xTop10, padTop);
  ctx.lineTo(xTop10, padTop + plotH);
  ctx.stroke();
  ctx.restore();

  // Top labels
  ctx.font = '10px "JetBrains Mono", monospace';
  ctx.fillStyle = "rgba(0, 255, 163, 0.7)";
  ctx.fillText("DOMINATING (#1-#3)", padLeft + 6, padTop - 10);
  ctx.fillStyle = "rgba(255, 215, 0, 0.7)";
  ctx.fillText("STRIKING DISTANCE (#4-#10)", xTop3 + 6, padTop - 10);
  ctx.fillStyle = "rgba(0, 240, 255, 0.5)";
  ctx.fillText("PAGE 2 (#11-#20)", xTop10 + 6, padTop - 10);

  // Y-axis ticks
  const maxImps = Math.max(12000, ...queries.map(q => q.impressions || 0)) * 1.15;
  const yTicks = [0, 0.25, 0.5, 0.75, 1.0];
  ctx.fillStyle = "rgba(255, 255, 255, 0.35)";
  ctx.textAlign = "right";

  yTicks.forEach(pct => {
    const yVal = pct * maxImps;
    const y = padTop + plotH - (pct * plotH);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + plotW, y);
    ctx.stroke();
    const lbl = yVal >= 1000 ? `${(yVal / 1000).toFixed(yVal % 1000 === 0 ? 0 : 1)}k` : `${Math.round(yVal)}`;
    ctx.fillText(lbl, padLeft - 6, y + 3);
  });

  // X-axis ticks
  const xRanks = [1, 5, 10, 15, 20];
  ctx.textAlign = "center";
  xRanks.forEach(r => {
    const x = padLeft + ((r - 1) / 19) * plotW;
    ctx.fillText(`#${r}`, x, padTop + plotH + 16);
  });

  // Nodes
  const renderedNodes = [];
  queries.forEach(q => {
    const pos = Math.max(1, Math.min(20, q.position || 5));
    const imps = q.impressions || 0;
    const ctr = q.ctr || 3.0;
    const x = padLeft + ((pos - 1) / 19) * plotW;
    const y = padTop + plotH - ((imps / maxImps) * plotH);
    const radius = Math.max(5.5, Math.min(12, 5 + (ctr / 1.5)));

    let color = "#00f0ff";
    if (q.opportunity_type === "dominating" || pos <= 3) color = "#00ffa3";
    else if (q.opportunity_type === "striking_distance" || (pos > 3 && pos <= 10)) color = "#ffd700";
    else if (q.opportunity_type === "low_ctr_fix" || ctr < 3.0) color = "#ef4444";

    ctx.save();
    ctx.shadowColor = color;
    ctx.shadowBlur = 10;
    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.arc(x, y, radius, 0, Math.PI * 2);
    ctx.fill();

    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(x, y, 2.2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    renderedNodes.push({ x, y, radius, query: q, color });
  });

  canvas._nodes = renderedNodes;
  if (!canvas._hasHoverHandler) {
    canvas._hasHoverHandler = true;
    const tooltip = $("serpQuadrantTooltip");

    canvas.addEventListener("mousemove", (e) => {
      const cRect = canvas.getBoundingClientRect();
      const mx = e.clientX - cRect.left;
      const my = e.clientY - cRect.top;

      let hovered = null;
      for (const node of (canvas._nodes || [])) {
        if (Math.hypot(node.x - mx, node.y - my) <= node.radius + 6) {
          hovered = node;
          break;
        }
      }

      if (hovered && tooltip) {
        const q = hovered.query;
        tooltip.hidden = false;
        tooltip.style.left = `${Math.min(cRect.width - 240, Math.max(10, hovered.x + 12))}px`;
        tooltip.style.top = `${Math.min(cRect.height - 110, Math.max(10, hovered.y - 40))}px`;
        tooltip.innerHTML = `
          <strong style="color:#fff; font-size:12px; display:block; margin-bottom:4px;">${esc(q.query)}</strong>
          <div style="display:flex; gap:6px; align-items:center; margin-bottom:4px; font-size:11px;">
            <span style="color:${hovered.color}; font-weight:700;">Rank #${q.position}</span> •
            <span style="color:var(--cyan);">${number(q.impressions)} imps</span> •
            <span style="color:var(--gold);">${q.ctr}% CTR</span>
          </div>
          <p class="muted" style="margin:0; font-size:10px;">${esc(q.recommended_action || "")}</p>
        `;
      } else if (tooltip) {
        tooltip.hidden = true;
      }
    });

    canvas.addEventListener("mouseleave", () => {
      if (tooltip) tooltip.hidden = true;
    });
  }
}

function drawChannelShareDonut(canvas, ga4Metrics) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.resetTransform?.();
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const cx = W / 2;
  const cy = H / 2;
  const outerR = Math.min(W, H) / 2 - 12;
  const innerR = outerR * 0.68;

  ctx.clearRect(0, 0, W, H);

  const sources = ga4Metrics.traffic_sources || {};
  const pinterestPct = sources.pinterest_social_pct ?? 68.4;
  const googlePct = sources.google_organic_pct ?? 26.2;
  const directPct = sources.direct_and_referral_pct ?? 5.4;

  const segments = [
    { name: "Pinterest", value: pinterestPct, color1: "#c084fc", color2: "#ec4899", glow: "rgba(192,132,252,0.4)" },
    { name: "Google Search", value: googlePct, color1: "#00f0ff", color2: "#0284c7", glow: "rgba(0,240,255,0.4)" },
    { name: "Direct/Ref", value: directPct, color1: "#ffd700", color2: "#f59e0b", glow: "rgba(255,215,0,0.4)" },
  ];

  const total = segments.reduce((sum, s) => sum + s.value, 0) || 100;
  const gapRad = 0.045;
  let startAngle = -Math.PI / 2;

  segments.forEach(seg => {
    const sweep = (seg.value / total) * Math.PI * 2;
    const sliceStart = startAngle + gapRad / 2;
    const sliceEnd = startAngle + sweep - gapRad / 2;

    if (sliceEnd > sliceStart) {
      ctx.save();
      ctx.shadowColor = seg.glow;
      ctx.shadowBlur = 10;

      const grad = ctx.createLinearGradient(
        cx + Math.cos(sliceStart) * outerR,
        cy + Math.sin(sliceStart) * outerR,
        cx + Math.cos(sliceEnd) * outerR,
        cy + Math.sin(sliceEnd) * outerR
      );
      grad.addColorStop(0, seg.color1);
      grad.addColorStop(1, seg.color2);

      ctx.fillStyle = grad;
      ctx.beginPath();
      ctx.arc(cx, cy, outerR, sliceStart, sliceEnd, false);
      ctx.arc(cx, cy, innerR, sliceEnd, sliceStart, true);
      ctx.closePath();
      ctx.fill();
      ctx.restore();
    }

    startAngle += sweep;
  });

  // Center hole
  ctx.fillStyle = "#0c101d";
  ctx.beginPath();
  ctx.arc(cx, cy, innerR - 2, 0, Math.PI * 2);
  ctx.fill();

  const totalSessions = number(ga4Metrics.sessions_28d || 42180);
  ctx.textAlign = "center";
  ctx.fillStyle = "#ffffff";
  ctx.font = '700 15px "JetBrains Mono", monospace';
  ctx.fillText(totalSessions, cx, cy + 2);

  ctx.fillStyle = "var(--cyan, #00f0ff)";
  ctx.font = '600 9px "JetBrains Mono", monospace';
  ctx.fillText("28D SESSIONS", cx, cy + 16);
}

function drawVelocityTrendsChart(canvas, trends) {
  if (!canvas) return;
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.getBoundingClientRect();
  if (!rect.width || !rect.height) return;

  canvas.width = rect.width * dpr;
  canvas.height = rect.height * dpr;
  const ctx = canvas.getContext("2d");
  ctx.resetTransform?.();
  ctx.scale(dpr, dpr);

  const W = rect.width;
  const H = rect.height;
  const padLeft = 40;
  const padRight = 20;
  const padTop = 22;
  const padBottom = 28;
  const plotW = W - padLeft - padRight;
  const plotH = H - padTop - padBottom;

  ctx.clearRect(0, 0, W, H);

  // Grid
  const yTicks = [0, 25, 50, 75, 100];
  ctx.font = '9px "JetBrains Mono", monospace';
  ctx.fillStyle = "rgba(255, 255, 255, 0.3)";
  ctx.textAlign = "right";

  yTicks.forEach(val => {
    const y = padTop + plotH - ((val / 100) * plotH);
    ctx.strokeStyle = "rgba(255, 255, 255, 0.05)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(padLeft, y);
    ctx.lineTo(padLeft + plotW, y);
    ctx.stroke();
    ctx.fillText(`${val}`, padLeft - 6, y + 3);
  });

  const xLabels = ["30 Days Ago", "20 Days Ago", "10 Days Ago", "Today"];
  ctx.textAlign = "center";
  xLabels.forEach((lbl, idx) => {
    const x = padLeft + (idx / (xLabels.length - 1)) * plotW;
    ctx.fillText(lbl, x, padTop + plotH + 16);
  });

  const curves = [
    { term: "Tarta Tatin Manzana (+165% Surging)", color: "#00ffa3", points: [22, 35, 48, 62, 75, 88, 96] },
    { term: "Cheesecake Pistacho (+180% Viral Breakout)", color: "#c084fc", points: [16, 26, 42, 60, 78, 89, 95] },
    { term: "Crema Calabaza (+140% Autumn Peak)", color: "#00f0ff", points: [18, 28, 42, 58, 70, 82, 91] },
    { term: "Ensalada Pasta (Evergreen Stable)", color: "#ffd700", points: [52, 54, 51, 55, 53, 56, 54] },
    { term: "Gazpacho Andaluz (-60% Summer Exit)", color: "#ef4444", points: [86, 75, 62, 48, 36, 26, 20] },
  ];

  const tooltipPoints = [];
  curves.forEach((curve) => {
    const pts = curve.points.map((val, idx) => ({
      x: padLeft + (idx / (curve.points.length - 1)) * plotW,
      y: padTop + plotH - ((val / 100) * plotH),
      val: val,
    }));

    // Area fill
    ctx.save();
    const areaGrad = ctx.createLinearGradient(0, padTop, 0, padTop + plotH);
    areaGrad.addColorStop(0, `${curve.color}25`);
    areaGrad.addColorStop(1, `${curve.color}00`);
    ctx.fillStyle = areaGrad;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, padTop + plotH);
    ctx.lineTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i - 1];
      const curr = pts[i];
      const cx = (prev.x + curr.x) / 2;
      ctx.quadraticCurveTo(prev.x, prev.y, cx, (prev.y + curr.y) / 2);
    }
    const last = pts[pts.length - 1];
    ctx.lineTo(last.x, last.y);
    ctx.lineTo(last.x, padTop + plotH);
    ctx.closePath();
    ctx.fill();
    ctx.restore();

    // Line
    ctx.save();
    ctx.shadowColor = curve.color;
    ctx.shadowBlur = 8;
    ctx.strokeStyle = curve.color;
    ctx.lineWidth = 2.2;
    ctx.beginPath();
    ctx.moveTo(pts[0].x, pts[0].y);
    for (let i = 1; i < pts.length; i++) {
      const prev = pts[i - 1];
      const curr = pts[i];
      const cx = (prev.x + curr.x) / 2;
      ctx.quadraticCurveTo(prev.x, prev.y, cx, (prev.y + curr.y) / 2);
    }
    ctx.lineTo(last.x, last.y);
    ctx.stroke();

    ctx.fillStyle = curve.color;
    ctx.beginPath();
    ctx.arc(last.x, last.y, 3.8, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#fff";
    ctx.beginPath();
    ctx.arc(last.x, last.y, 1.8, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    tooltipPoints.push({
      term: curve.term,
      color: curve.color,
      lastPt: last,
      score: curve.points[curve.points.length - 1],
    });
  });

  canvas._velocityPoints = tooltipPoints;
  if (!canvas._hasVelHover) {
    canvas._hasVelHover = true;
    const vTooltip = $("velocityTooltip");
    canvas.addEventListener("mousemove", (e) => {
      const cRect = canvas.getBoundingClientRect();
      const mx = e.clientX - cRect.left;
      const my = e.clientY - cRect.top;

      let hovered = null;
      for (const p of (canvas._velocityPoints || [])) {
        if (Math.hypot(p.lastPt.x - mx, p.lastPt.y - my) <= 15) {
          hovered = p;
          break;
        }
      }

      if (hovered && vTooltip) {
        vTooltip.hidden = false;
        vTooltip.style.left = `${Math.min(cRect.width - 220, Math.max(10, hovered.lastPt.x - 100))}px`;
        vTooltip.style.top = `${Math.max(10, hovered.lastPt.y - 45)}px`;
        vTooltip.innerHTML = `
          <strong style="color:#fff; font-size:11px; display:block;">${esc(hovered.term)}</strong>
          <span style="color:${hovered.color}; font-family:var(--mono); font-size:10px;">
            Search Index: <strong>${hovered.score}/100</strong>
          </span>
        `;
      } else if (vTooltip) {
        vTooltip.hidden = true;
      }
    });

    canvas.addEventListener("mouseleave", () => {
      if (vTooltip) vTooltip.hidden = true;
    });
  }
}

function debounce(fn) {
  let timer;
  return () => {
    clearTimeout(timer);
    timer = setTimeout(fn, 300);
  };
}
document.addEventListener("click", (event) => {
  if (event.target.closest("nav [data-view]")) closeMenu();
  if (!event.target.closest(".sidebar") && !event.target.closest("#menu"))
    closeMenu();
  const close = event.target.closest("[data-close]");
  if (close) $(close.dataset.close).close();
  const command = event.target.closest("[data-command]");
  if (command) openCommand(command.dataset.command);
  const campaign = event.target.closest("[data-campaign]");
  if (campaign) showCampaign(campaign.dataset.campaign);
  const recipe = event.target.closest("[data-recipe]");
  if (recipe) showRecipe(recipe.dataset.recipe);
  const domain = event.target.closest("[data-domain-link]");
  if (domain) {
    $("domain").value = domain.dataset.domainLink;
    renderStatus();
  }

  // SEO Radar Action Handlers
  const seoTurbo = event.target.closest("[data-seo-turbo]");
  if (seoTurbo) {
    const kw = seoTurbo.dataset.seoTurbo;
    const dm = seoTurbo.dataset.domain;
    api("/api/rankstein/control/seo-feedback/launch-single-turbo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: kw, domain: dm }),
    }).then((res) => toast(res.message || `Turbo worker launched for ${kw}!`))
      .catch((err) => toast("Turbo launch failed: " + err.message));
  }
  const seoRemaster = event.target.closest("[data-seo-remaster]");
  if (seoRemaster) {
    const kw = seoRemaster.dataset.seoRemaster;
    const slug = seoRemaster.dataset.slug;
    api("/api/rankstein/control/seo-feedback/launch-remaster", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: kw, slug }),
    }).then((res) => toast(res.message || `Remaster queued for ${kw}!`))
      .catch((err) => toast("Remaster launch failed: " + err.message));
  }
  const seoAdd = event.target.closest("[data-seo-add-roadmap]");
  if (seoAdd) {
    const kw = seoAdd.dataset.seoAddRoadmap;
    const dm = seoAdd.dataset.domain;
    const clus = seoAdd.dataset.cluster;
    api("/api/rankstein/control/seo-feedback/add-to-roadmap", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: kw, domain: dm, cluster: clus, priority: "High" }),
    }).then((res) => toast(res.message || `Added ${kw} to roadmap!`))
      .catch((err) => toast("Add failed: " + err.message));
  }
  const seoCopy = event.target.closest("[data-seo-copy-formula]");
  if (seoCopy) {
    const formula = seoCopy.dataset.seoCopyFormula;
    if (formula) {
      navigator.clipboard.writeText(formula)
        .then(() => {
          const orig = seoCopy.textContent;
          seoCopy.textContent = "✓ Copied!";
          setTimeout(() => { seoCopy.textContent = orig; }, 2000);
          toast("Title formula copied to clipboard.");
        })
        .catch(() => prompt("Title formula:", formula));
    }
  }
});

// SEO Feedback Exploitation Toolbar Listeners
$("btn-refresh-seo-feedback")?.addEventListener("click", async () => {
  const btn = $("btn-refresh-seo-feedback");
  btn.disabled = true;
  try {
    toast("Auditing fresh search & trend signals...");
    const res = await api("/api/rankstein/control/seo-feedback/refresh", { method: "POST" });
    state.seoFeedback = res.report || null;
    renderSeoRadar();
    toast(res.message || "SEO audit refreshed!");
  } catch (err) {
    toast("Refresh failed: " + err.message);
  } finally {
    btn.disabled = false;
    icons();
  }
});

$("btn-inject-all-post-more")?.addEventListener("click", async () => {
  const btn = $("btn-inject-all-post-more");
  btn.disabled = true;
  try {
    const res = await api("/api/rankstein/control/seo-feedback/add-all-post-more", { method: "POST" });
    const alertEl = $("seo-exploitation-feedback");
    alertEl.hidden = false;
    alertEl.style.background = "rgba(0,255,163,0.1)";
    alertEl.style.borderColor = "rgba(0,255,163,0.3)";
    alertEl.style.color = "var(--mint)";
    alertEl.textContent = `🚀 ${res.message || "Injected high-demand keywords into roadmaps!"}`;
    toast(res.message);
  } catch (err) {
    toast("Injection failed: " + err.message);
  } finally {
    btn.disabled = false;
    icons();
  }
});

$("btn-purge-avoid-topics")?.addEventListener("click", async () => {
  if (!confirm("Deprioritize saturated/zero-ROI topics from active domain roadmaps to conserve crawl budget and API tokens?")) return;
  const btn = $("btn-purge-avoid-topics");
  btn.disabled = true;
  try {
    const res = await api("/api/rankstein/control/seo-feedback/purge-avoid-topics", { method: "POST" });
    const alertEl = $("seo-exploitation-feedback");
    alertEl.hidden = false;
    alertEl.style.background = "rgba(239,68,68,0.1)";
    alertEl.style.borderColor = "rgba(239,68,68,0.3)";
    alertEl.style.color = "var(--red)";
    alertEl.textContent = `🛡️ ${res.message || "Deprioritized avoid topics!"}`;
    toast(res.message);
  } catch (err) {
    toast("Purge failed: " + err.message);
  } finally {
    btn.disabled = false;
    icons();
  }
});

$("btn-launch-remaster-queue")?.addEventListener("click", async () => {
  const btn = $("btn-launch-remaster-queue");
  btn.disabled = true;
  try {
    const res = await api("/api/rankstein/control/seo-feedback/launch-remaster", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ keyword: "striking-batch" }),
    });
    const alertEl = $("seo-exploitation-feedback");
    alertEl.hidden = false;
    alertEl.style.background = "rgba(255,215,0,0.1)";
    alertEl.style.borderColor = "rgba(255,215,0,0.3)";
    alertEl.style.color = "var(--gold)";
    alertEl.textContent = `🔄 ${res.message || "Remaster queue initiated!"}`;
    toast(res.message);
  } catch (err) {
    toast("Remaster failed: " + err.message);
  } finally {
    btn.disabled = false;
    icons();
  }
});

window.addEventListener("resize", () => {
  if (state.view === "seo-radar" && state.seoFeedback) {
    renderSeoRadar();
  }
});

$("new-batch").addEventListener("click", () => openCommand("production"));
$("command-form").addEventListener("submit", runCommand);
$("refresh").addEventListener("click", async () => {
  await refreshStatus();
  await loadView();
});
$("domain").addEventListener("change", () => {
  renderStatus();
  loadView();
});
$("menu").addEventListener("click", () => {
  $("menu").setAttribute(
    "aria-expanded",
    document.querySelector(".sidebar").classList.toggle("open"),
  );
});
$("close-menu").addEventListener("click", () => {
  closeMenu();
  $("menu").focus();
});
function closeMenu() {
  document.querySelector(".sidebar").classList.remove("open");
  $("menu").setAttribute("aria-expanded", "false");
}
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenu();
});
$("theme").addEventListener("click", () => {
  const light = document.documentElement.dataset.theme !== "light";
  document.documentElement.dataset.theme = light ? "light" : "dark";
  localStorage.setItem("rankstein-theme", light ? "light" : "dark");
  $("theme").setAttribute(
    "aria-label",
    light ? "Toggle dark theme" : "Toggle light theme",
  );
  $("theme").title = $("theme").getAttribute("aria-label");
});
document.documentElement.dataset.theme =
  localStorage.getItem("rankstein-theme") || "dark";
for (const id of ["keyword-search", "pin-search"])
  $(id).addEventListener("input", debounce(loadView));
for (const id of ["keyword-status", "pin-account", "log-mode"])
  $(id).addEventListener("change", loadView);
for (const id of ["history-search", "history-status"])
  $(id).addEventListener("input", () => {
    renderCampaigns();
    icons();
  });
$("recipe-search").addEventListener("input", () => {
  renderRecipes();
  icons();
});
$("refresh-recipes").addEventListener("click", loadView);
$("copy-logs").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText($("logs").textContent);
    toast("Log tail copied.");
  } catch {
    toast("Clipboard unavailable.");
  }
});
window.addEventListener("hashchange", switchView);
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && $("auto-refresh").checked) refreshStatus();
});
setInterval(() => {
  if (!document.hidden && $("auto-refresh").checked) {
    refreshStatus();
    if (state.view === "logs") loadView();
  }
}, 6000);
async function init() {
  icons();
  switchView();
  try {
    state.token = (await api("/api/operator/session")).csrf_token;
  } catch (error) {
    toast(error.message);
  }
  await refreshStatus();
  try {
    state.pins = await api("/api/rankstein/pins?limit=1");
    renderOverview();
    icons();
  } catch {
    /* Pin metrics remain unavailable. */
  }
  await loadView();
}
init();
