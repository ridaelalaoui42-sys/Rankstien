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
};
const headings = {
  overview: "Command center",
  workflows: "Open workflows",
  history: "Campaign history",
  pinterest: "Pinterest distribution",
  keywords: "Keyword intelligence",
  recipes: "Recipe inspector",
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
    : ["active", "running", "processing", "researching", "queued"].includes(key)
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
  const list =
    state.data?.pipeline?.[
      kind === "active" ? "ongoing_campaigns" : "history_campaigns"
    ] || [];
  return list.filter(
    (c) => !domainScope() || c.domain_handle === domainScope(),
  );
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
  return `<article class="campaign"><div class="campaign-head"><div><h3>${esc(c.keyword || c.title)}</h3><small>${esc(c.domain_handle)} / ${esc(c.slug)}</small></div>${badge(c.overall_state)}</div><div class="campaign-stage">Last recorded: ${esc(c.current_label || c.run_status)}${c.current_detail ? ` &middot; ${esc(c.current_detail)}` : ""}</div><div class="stages" aria-label="Recorded workflow stages">${(c.stages || []).map((s) => `<span class="stage ${esc(s.state)}" title="${esc(s.label + ": " + s.state)}"></span>`).join("")}</div><div class="campaign-foot"><button class="button" data-campaign="${esc(c.id)}">${icon("list-tree")}Inspect stages</button>${external(c.article_url, "Article")}${external(c.pin_url, "Primary pin")}<span class="muted">${date(c.updated_at)}</span></div></article>`;
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
      "Open workflows",
      number(active.length),
      domainScope() || "All configured domains",
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
      "No active campaigns",
      "Waiting for the next production batch.",
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
  const b = d.production_batch;
  $("batch-id").textContent = b?.batch_id || "No batch recorded";
  $("batch").innerHTML = b
    ? `<div class="batch-row">${badge(b.state)}${Object.entries(b.domains || {})
        .map(
          ([handle, domain]) =>
            `<span>${esc(handle)} <strong>${esc(domain.verified || 0)} / ${esc(domain.target || b.target_per_domain || "-")}</strong> verified</span>`,
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
    `${active.length} displayed / ${state.data?.pipeline?.ongoing_total ?? "-"} ongoing across all domains`;
  $("workflows").innerHTML =
    active.map(campaignMarkup).join("") ||
    empty(
      "All quiet",
      "No ongoing campaign evidence in the current snapshot.",
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
      "Ready for distribution",
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
