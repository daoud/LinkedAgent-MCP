/* LinkedIn Auto-Publisher — dashboard SPA (vanilla JS, no build step) */
(() => {
  "use strict";

  const $ = (s, r = document) => r.querySelector(s);
  const $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const viewEl = $("#view");
  const KEY_STORE = "lp_api_key";

  // ---------------------------------------------------------------- api
  function apiKey() { return localStorage.getItem(KEY_STORE) || ""; }
  async function api(path, opts = {}) {
    const headers = opts.headers || {};
    if (apiKey()) headers["X-API-Key"] = apiKey();
    if (opts.json !== undefined) {
      headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.json);
      delete opts.json;
    }
    let res;
    try {
      res = await fetch(path, { ...opts, headers });
    } catch (e) {
      throw new Error("network error — is the server running?");
    }
    let data = {};
    try { data = await res.json(); } catch { /* non-json */ }
    if (!res.ok && data.ok === undefined) throw new Error(data.error || data.detail || `HTTP ${res.status}`);
    if (data.ok === false) throw new Error(data.error || "request failed");
    return data;
  }

  // ---------------------------------------------------------------- dom
  function h(tag, attrs = {}, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") e.className = v;
      else if (k === "html") e.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
      else if (v === true) e.setAttribute(k, "");
      else if (v !== false && v != null) e.setAttribute(k, v);
    }
    for (const kid of kids.flat()) {
      if (kid == null || kid === false) continue;
      e.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
    }
    return e;
  }
  const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function toast(msg, kind = "") {
    const t = h("div", { class: `toast ${kind}` }, msg);
    $("#toasts").append(t);
    setTimeout(() => { t.style.opacity = "0"; setTimeout(() => t.remove(), 300); }, kind === "err" ? 6000 : 3500);
  }
  const fmtCost = (v) => v == null ? "—" : "$" + Number(v).toFixed(4);
  const fmtTime = (s) => s ? new Date(s).toLocaleString() : "—";
  const ago = (s) => {
    if (!s) return "—";
    const d = (Date.now() - new Date(s)) / 1000;
    if (d < 60) return "just now";
    if (d < 3600) return Math.floor(d / 60) + "m ago";
    if (d < 86400) return Math.floor(d / 3600) + "h ago";
    return Math.floor(d / 86400) + "d ago";
  };
  const pill = (s) => h("span", { class: `pill ${s}` }, (s || "").replace(/_/g, " "));

  // ---------------------------------------------------------------- state
  const state = { view: "overview", overview: null, postFilter: "all", logSeq: 0, logPaused: false, logTimer: null };

  // ---------------------------------------------------------------- router
  function go(view) {
    state.view = view;
    $$("#nav a").forEach((a) => a.classList.toggle("active", a.dataset.view === view));
    if (state.logTimer && view !== "logs") { clearInterval(state.logTimer); state.logTimer = null; }
    location.hash = view;
    render();
  }
  window.addEventListener("hashchange", () => {
    const v = location.hash.slice(1);
    if (v.startsWith("post/")) { openPost(v.slice(5)); return; }
    if (v && v !== state.view) go(v);
  });

  function render() {
    const fn = views[state.view] || views.overview;
    viewEl.innerHTML = "";
    fn().catch((e) => {
      viewEl.append(h("div", { class: "card" }, h("h1", {}, "Something went wrong"),
        h("p", { class: "muted" }, e.message),
        h("button", { class: "btn ghost", onclick: render }, "Retry")));
    });
  }

  // ---------------------------------------------------------------- views
  const views = {};

  views.overview = async () => {
    const d = await api("/api/overview");
    state.overview = d;
    updateStatusBar(d);
    const c = d.counts || {};
    const cards = [
      ["Published", d.published ?? 0],
      ["Awaiting approval", d.pending_approvals ?? 0],
      ["Failed", c.failed ?? 0],
      ["Cost this month", fmtCost(d.month_cost_usd) + " / $" + d.month_budget_usd],
    ];
    const grid = h("div", { class: "grid c4" });
    cards.forEach(([label, val]) => grid.append(
      h("div", { class: "stat" }, h("div", { class: "stat-val" }, String(val)), h("div", { class: "stat-label" }, label))));

    const budgetPct = Math.min(100, (d.month_cost_usd / (d.month_budget_usd || 1)) * 100);
    const cfg = d.config || {};
    const cfgCard = h("div", { class: "card" },
      h("h2", {}, "Current configuration"),
      h("div", { class: "kv" },
        h("b", {}, "Approval required"), h("span", {}, cfg.approval_required ? "yes — posts pause for a human" : "no — fully automatic"),
        h("b", {}, "Auto dry-run"), h("span", {}, String(cfg.auto_publish_dry_run) + "  (folder-watcher path)"),
        h("b", {}, "Model"), h("span", {}, cfg.llm_model || "—"),
        h("b", {}, "Post slots"), h("span", {}, (cfg.post_slots || "") + "  ·  " + cfg.timezone + "  ·  limit " + cfg.daily_post_limit + "/day"),
        h("b", {}, "Storage"), h("span", {}, cfg.storage_mode),
        h("b", {}, "Approvals via"), h("span", {}, cfg.google_sheet_configured ? "Google Sheet + this UI" : "this UI / API only"),
        h("b", {}, "Slack"), h("span", {}, cfg.slack_configured ? "connected" : "not configured"),
        h("b", {}, "LinkedIn author"), h("span", { class: "mono" }, cfg.linkedin_profile_urn || "not set"),
      ),
      h("div", { class: "progress", style: "margin-top:10px" }, h("i", { style: `width:${budgetPct}%` })),
      h("small", {}, `LLM budget used: ${budgetPct.toFixed(0)}%`),
    );

    const recent = h("div", { class: "card pad0" });
    const posts = (await api("/api/posts?limit=8")).posts || [];
    recent.append(h("div", { style: "padding:14px 18px" }, h("h2", { style: "margin:0" }, "Recent posts")));
    recent.append(postTable(posts, true));

    viewEl.append(
      h("div", { class: "inline", style: "margin-bottom:16px" },
        h("h1", {}, "Overview"), h("div", { class: "spacer" }),
        h("button", { class: "btn", onclick: () => go("compose") }, "＋ Compose a post")),
      grid,
      h("div", { class: "grid c2", style: "margin-top:16px" }, cfgCard, recent),
    );
  };

  const STARTERS = {
    "Product update": "We just shipped {feature}.\n\nWhat it means for you: {benefit}.\n\nThe reason we built it: {why}.\n\nTry it and tell us what you think.",
    "Hiring": "We're hiring a {role} to join {team}.\n\nWhat you'll work on: {work}.\nWhat we look for: {qualities}.\n\nKnow someone great? Send them our way.",
    "Thought leadership": "Most people think {common_belief}.\n\nAfter {experience}, I've come to believe the opposite: {contrarian_take}.\n\nHere's what changed my mind: {evidence}.",
    "Milestone": "Today we crossed {milestone}.\n\nIt took {time} and {effort}.\n\nThank you to {people} who made it happen.\n\nWhat's next: {next}.",
    "Lesson learned": "A mistake I made: {mistake}.\n\nWhat it cost: {cost}.\n\nWhat I'd do differently: {lesson}.",
  };
  const TONES = ["professional and insightful", "conversational and warm", "bold and punchy", "thought-leadership", "storytelling", "analytical and data-driven"];

  views.compose = async () => {
    let imageFile = null;
    const contentTa = h("textarea", { rows: "12", placeholder: "Write your raw thoughts here. Claude rewrites this into a LinkedIn post — it does not post it verbatim." });
    const titleIn = h("input", { type: "text", placeholder: "Internal label (optional) — e.g. 'Q3 launch announcement'" });
    const toneSel = h("select", {}, ...TONES.map((t) => h("option", { value: t }, t)));
    const dryToggle = h("input", { type: "checkbox", checked: true });

    const chips = h("div", { class: "chips" },
      ...Object.entries(STARTERS).map(([name, body]) =>
        h("span", { class: "chip", onclick: () => { contentTa.value = contentTa.value ? contentTa.value + "\n\n" + body : body; contentTa.focus(); } }, name)));

    const dzImg = h("img", { hidden: true });
    const dzText = h("div", {}, "Drop an image here, or click to choose  ·  jpg / png / webp / gif, up to 12 MB");
    const fileInput = h("input", { type: "file", accept: "image/*", hidden: true });
    const dz = h("div", { class: "dropzone" }, dzText, dzImg);
    const setImg = (f) => {
      if (!f) return;
      if (!f.type.startsWith("image/")) { toast("not an image", "err"); return; }
      imageFile = f;
      const url = URL.createObjectURL(f);
      dzImg.src = url; dzImg.hidden = false;
      dzText.textContent = `${f.name} — click to replace, or `;
      const rm = h("a", { onclick: (e) => { e.stopPropagation(); imageFile = null; dzImg.hidden = true; dzText.textContent = "Drop an image here, or click to choose"; } }, "remove");
      dzText.append(rm);
    };
    dz.addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => setImg(fileInput.files[0]));
    dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("drag"); });
    dz.addEventListener("dragleave", () => dz.classList.remove("drag"));
    dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("drag"); setImg(e.dataTransfer.files[0]); });

    const runPanel = h("div", { hidden: true });
    const submit = h("button", { class: "btn" }, "Generate & run pipeline");

    submit.addEventListener("click", async () => {
      if (!contentTa.value.trim()) { toast("write some content first", "warn"); return; }
      submit.disabled = true; submit.textContent = "Submitting…";
      try {
        const fd = new FormData();
        fd.append("text", contentTa.value.trim());
        fd.append("title", titleIn.value.trim());
        fd.append("tone", toneSel.value);
        fd.append("dry_run", dryToggle.checked ? "true" : "false");
        if (imageFile) fd.append("image", imageFile);
        const d = await api("/api/compose", { method: "POST", body: fd });
        toast(`Pipeline started (${d.dry_run ? "dry run" : "LIVE"})`, "ok");
        runPanel.hidden = false;
        trackRun(runPanel, d.upload_id, d.dry_run);
        contentTa.value = ""; titleIn.value = ""; imageFile = null; dzImg.hidden = true;
        dzText.textContent = "Drop an image here, or click to choose";
      } catch (e) {
        toast(e.message, "err");
      } finally { submit.disabled = false; submit.textContent = "Generate & run pipeline"; }
    });

    viewEl.append(
      h("h1", {}, "Compose"),
      h("p", { class: "muted" }, "Write raw content, pick a tone, optionally attach an image. The pipeline sanitises → rewrites with Claude → validates → schedules → (approval) → publishes."),
      h("div", { class: "grid c2" },
        h("div", { class: "card" },
          h("h3", {}, "Starters (click to insert)"), chips,
          h("label", { class: "field" }, h("span", {}, "Content"), contentTa),
          h("label", { class: "field" }, h("span", {}, "Title / label"), titleIn),
          h("label", { class: "field" }, h("span", {}, "Tone"), toneSel),
        ),
        h("div", { class: "card" },
          h("h3", {}, "Image (optional)"), dz, fileInput,
          h("hr", { class: "hr" }),
          h("h3", {}, "Run options"),
          h("label", { class: "toggle", style: "margin:6px 0" }, dryToggle, h("span", { class: "track" }), h("span", {}, "Dry run (validate everything, do NOT post to LinkedIn)")),
          h("p", { class: "muted", style: "font-size:12px" }, "Turn dry run OFF to publish for real. If approval is required, the post will pause at 'awaiting approval' — handle it in the Approvals tab."),
          h("div", { style: "margin-top:14px" }, submit),
          runPanel,
        ),
      ),
    );
  };

  async function trackRun(panel, uploadId, dryRun) {
    panel.innerHTML = "";
    const bar = h("div", { class: "progress" }, h("i", { style: "width:8%" }));
    const label = h("div", { class: "muted", style: "margin:8px 0 4px", html: "Starting…" });
    const link = h("div", {});
    panel.append(h("hr", { class: "hr" }), h("h3", {}, "Live status"), bar, label, link);
    const steps = { processing: 25, awaiting_approval: 55, scheduled: 70, publishing: 88, published: 100, approved: 100, failed: 100, rejected: 100 };
    let tries = 0;
    const poll = async () => {
      tries++;
      let post = null;
      try {
        const list = await api(`/api/posts?limit=5`);
        post = (list.posts || []).find((p) => p.upload_id === uploadId);
      } catch { /* keep trying */ }
      if (!post) {
        if (tries > 40) { label.innerHTML = "Still starting… check the Posts tab."; return; }
        return setTimeout(poll, 1500);
      }
      bar.firstChild.style.width = (steps[post.status] || 20) + "%";
      label.innerHTML = `Status: ` + post.status.replace(/_/g, " ") + (post.failed_at_node ? ` (at ${post.failed_at_node})` : "");
      if (["published", "approved", "failed", "rejected"].includes(post.status)) {
        link.innerHTML = "";
        if (post.status === "failed") { label.innerHTML += ` — ${esc(post.last_error || "")}`; }
        const btn = h("button", { class: "btn sm ghost", onclick: () => openPost(post.id) }, "Open post");
        link.append(btn);
        if (post.linkedin_url) link.append(" ", h("a", { href: post.linkedin_url, target: "_blank" }, "View on LinkedIn ↗"));
        if (post.status === "awaiting_approval") link.append(" ", h("button", { class: "btn sm", onclick: () => go("approvals") }, "Go to approvals"));
        return;
      }
      if (post.status === "awaiting_approval") {
        link.innerHTML = "";
        link.append(h("button", { class: "btn sm", onclick: () => go("approvals") }, "Approve / reject →"));
      }
      if (tries < 120) setTimeout(poll, 1800);
    };
    poll();
  }

  function postTable(posts, compact) {
    if (!posts.length) return h("div", { class: "empty" }, "No posts yet.");
    const tb = h("tbody");
    posts.forEach((p) => {
      tb.append(h("tr", { onclick: () => openPost(p.id) },
        h("td", {}, h("div", {}, p.title || h("span", { class: "muted" }, "(untitled)")),
          h("small", { class: "mono" }, (p.preview || "").slice(0, 70))),
        h("td", {}, pill(p.status)),
        !compact && h("td", { class: "muted" }, p.source || "—"),
        !compact && h("td", {}, p.has_image ? "🖼" : ""),
        h("td", { class: "muted" }, fmtCost(p.cost_usd)),
        h("td", { class: "muted" }, ago(p.created_at)),
      ));
    });
    return h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Post"), h("th", {}, "Status"),
        !compact && h("th", {}, "Source"), !compact && h("th", {}, "Img"),
        h("th", {}, "Cost"), h("th", {}, "Created"))),
      tb);
  }

  views.posts = async () => {
    const filters = ["all", "processing", "awaiting_approval", "scheduled", "published", "failed", "rejected"];
    const tabs = h("div", { class: "tabs" }, ...filters.map((f) =>
      h("a", { class: f === state.postFilter ? "active" : "", onclick: () => { state.postFilter = f; render(); } }, f.replace(/_/g, " "))));
    const d = await api(`/api/posts?status=${state.postFilter}&limit=100`);
    viewEl.append(
      h("div", { class: "inline", style: "margin-bottom:8px" }, h("h1", {}, "Posts"), h("div", { class: "spacer" }),
        h("button", { class: "btn ghost", onclick: render }, "↻ Refresh"),
        h("button", { class: "btn", onclick: () => go("compose") }, "＋ Compose")),
      tabs,
      h("div", { class: "card pad0" }, postTable(d.posts || [], false)),
    );
  };

  async function openPost(id) {
    const drawer = $("#drawer"), panel = $("#drawer-panel");
    drawer.hidden = false;
    if (location.hash !== "#post/" + id) history.replaceState(null, "", "#post/" + id);
    panel.innerHTML = "";
    panel.append(h("div", { class: "close", onclick: closeDrawer }, "✕"), h("p", { class: "muted" }, "Loading…"));
    $(".drawer-back").onclick = closeDrawer;
    let d;
    try { d = await api(`/api/posts/${id}`); }
    catch (e) { panel.innerHTML = ""; panel.append(h("div", { class: "close", onclick: closeDrawer }, "✕"), h("p", { class: "muted" }, e.message)); return; }
    const p = d.post;
    const canEdit = !["published", "publishing"].includes(p.status);
    const draft = h("textarea", { rows: "10", ...(canEdit ? {} : { readonly: true }) }, );
    draft.value = p.transformed_text || "";

    const actions = h("div", { class: "inline", style: "margin:14px 0" });
    if (canEdit) actions.append(h("button", {
      class: "btn sm", onclick: async (e) => {
        e.target.disabled = true;
        try { await api(`/api/posts/${id}`, { method: "PATCH", json: { transformed_text: draft.value } }); toast("Draft saved", "ok"); }
        catch (err) { toast(err.message, "err"); } finally { e.target.disabled = false; }
      }
    }, "Save draft"));
    if (p.status === "awaiting_approval") {
      actions.append(
        h("button", { class: "btn sm ok", onclick: () => decidePost(id, "approved") }, "Approve"),
        h("button", { class: "btn sm err", onclick: () => decidePost(id, "rejected") }, "Reject"));
    }
    if (["failed", "rejected", "approved"].includes(p.status)) {
      actions.append(
        h("button", { class: "btn sm ghost", onclick: () => retryPost(id, true) }, "Retry (dry run)"),
        h("button", { class: "btn sm warn", onclick: () => retryPost(id, false) }, "Retry LIVE"));
    }
    if (p.linkedin_url) actions.append(h("a", { class: "btn sm ghost", href: p.linkedin_url, target: "_blank" }, "View on LinkedIn ↗"));
    actions.append(h("button", { class: "btn sm ghost", onclick: () => { navigator.clipboard?.writeText(draft.value); toast("Copied"); } }, "Copy text"));

    const tl = h("div", { class: "timeline" });
    (d.logs || []).forEach((l) => tl.append(h("div", { class: "ev " + l.level },
      h("span", { class: "dot2" }), h("span", { class: "lt mono" }, new Date(l.ts).toLocaleTimeString() + " "),
      l.node ? h("b", {}, `[${l.node}] `) : "", l.message)));
    if (!(d.logs || []).length) tl.append(h("div", { class: "muted" }, "no log events recorded"));

    panel.innerHTML = "";
    panel.append(
      h("div", { class: "close", onclick: closeDrawer }, "✕"),
      h("div", { class: "inline" }, h("h1", { style: "margin:0" }, p.title || "Untitled post"), pill(p.status)),
      h("div", { class: "kv" },
        h("b", {}, "Source"), h("span", {}, p.source || "—"),
        h("b", {}, "Tone"), h("span", {}, p.tone || "—"),
        h("b", {}, "Scheduled"), h("span", {}, p.scheduled_date ? `${p.scheduled_date} ${p.scheduled_slot || ""}` : "—"),
        h("b", {}, "Tokens / cost"), h("span", {}, `${p.tokens_used ?? "—"} · ${fmtCost(p.cost_usd)}`),
        h("b", {}, "LinkedIn id"), h("span", { class: "mono" }, p.linkedin_post_id || "—"),
        p.last_error ? h("b", {}, "Last error") : "", p.last_error ? h("span", { style: "color:var(--err)" }, p.last_error) : "",
      ),
      p.image_url ? h("img", { src: p.image_url, style: "max-height:200px;border-radius:8px;margin:6px 0" }) : "",
      h("h3", {}, "Raw content"),
      h("div", { class: "pre" }, p.raw_content || "—"),
      h("h3", {}, canEdit ? "Draft (editable — this exact text is what publishes)" : "Final text"),
      draft,
      actions,
      h("h3", {}, "Timeline"),
      tl,
    );
  }
  function closeDrawer() {
    $("#drawer").hidden = true;
    if (location.hash.startsWith("#post/")) history.replaceState(null, "", "#" + state.view);
  }

  async function decidePost(id, decision) {
    try { await api(`/api/posts/${id}/decision`, { method: "POST", json: { decision } });
      toast(`Post ${decision}`, decision === "approved" ? "ok" : "warn"); closeDrawer(); refreshBadges(); setTimeout(render, 600);
    } catch (e) { toast(e.message, "err"); }
  }
  async function retryPost(id, dry) {
    try { await api(`/api/posts/${id}/retry?dry_run=${dry}`, { method: "POST" });
      toast(`Retry started (${dry ? "dry run" : "LIVE"})`, "ok"); closeDrawer(); setTimeout(render, 600);
    } catch (e) { toast(e.message, "err"); }
  }

  views.approvals = async () => {
    const d = await api("/api/approvals");
    const list = d.approvals || [];
    viewEl.append(h("div", { class: "inline", style: "margin-bottom:12px" }, h("h1", {}, "Approvals"),
      h("div", { class: "spacer" }), h("button", { class: "btn ghost", onclick: render }, "↻ Refresh")));
    if (!list.length) { viewEl.append(h("div", { class: "card empty" }, "Nothing waiting for approval.")); return; }
    const grid = h("div", { class: "grid c2" });
    list.forEach((a) => {
      grid.append(h("div", { class: "card" },
        h("div", { class: "inline" }, h("b", {}, a.title || "Untitled"),
          h("small", { class: "muted" }, a.expires_in_h != null ? `expires in ${a.expires_in_h}h` : "")),
        h("div", { class: "pre", style: "max-height:200px;margin:10px 0" }, a.preview_text || ""),
        h("small", { class: "muted" }, a.scheduled_date ? `scheduled ${a.scheduled_date} ${a.scheduled_slot || ""}` : "no slot yet"),
        h("div", { class: "inline", style: "margin-top:12px" },
          h("button", { class: "btn ok", onclick: () => decideApproval(a.id, "approved") }, "Approve & publish"),
          h("button", { class: "btn err", onclick: () => decideApproval(a.id, "rejected") }, "Reject"),
          h("button", { class: "btn ghost sm", onclick: () => openPost(a.post_id) }, "Open post")),
      ));
    });
    viewEl.append(grid);
  };
  async function decideApproval(id, decision) {
    try { await api(`/api/approvals/${id}`, { method: "POST", json: { decision } });
      toast(`${decision}`, decision === "approved" ? "ok" : "warn"); refreshBadges(); setTimeout(render, 700);
    } catch (e) { toast(e.message, "err"); }
  }

  views.prompt = async () => {
    const d = await api("/api/templates");
    const all = d.templates || [];
    const active = all.find((t) => t.is_active) || all[0];
    const nameIn = h("input", { type: "text", value: active?.name || "linkedin_post" });
    const ta = h("textarea", { rows: "18", class: "mono" }, active?.template_text || "");
    ta.value = active?.template_text || "";
    const save = h("button", {
      class: "btn", onclick: async (e) => {
        if (!ta.value.includes("{content}")) { toast("template must contain {content}", "err"); return; }
        e.target.disabled = true;
        try { const r = await api("/api/templates", { method: "POST", json: { name: nameIn.value.trim(), template_text: ta.value } });
          toast(`Saved v${r.version} & activated`, "ok"); render();
        } catch (err) { toast(err.message, "err"); } finally { e.target.disabled = false; }
      }
    }, "Save as new version & activate");

    const history = h("div", { class: "card pad0" });
    history.append(h("div", { style: "padding:12px 16px" }, h("h3", { style: "margin:0" }, "Versions")));
    const tb = h("tbody");
    all.forEach((t) => tb.append(h("tr", {},
      h("td", {}, t.name + " v" + t.version),
      h("td", {}, t.is_active ? pill("published") : h("span", { class: "muted" }, "inactive")),
      h("td", { class: "muted" }, ago(t.created_at)),
      h("td", {}, t.is_active ? "" : h("button", { class: "btn sm ghost", onclick: async () => { try { await api(`/api/templates/${t.id}/activate`, { method: "POST" }); toast("Activated"); render(); } catch (e) { toast(e.message, "err"); } } }, "Activate")),
    )));
    history.append(h("table", {}, h("thead", {}, h("tr", {}, h("th", {}, "Template"), h("th", {}, "State"), h("th", {}, "Created"), h("th", {}, ""))), tb));

    viewEl.append(
      h("h1", {}, "Prompt Studio"),
      h("p", { class: "muted" }, "This is the system prompt Claude uses to rewrite raw content. Use ", h("code", {}, "{content}"), " and ", h("code", {}, "{tone}"), " placeholders. Saving creates a new version and makes it active immediately."),
      h("div", { class: "grid c2" },
        h("div", { class: "card" },
          h("label", { class: "field" }, h("span", {}, "Template name"), nameIn),
          h("label", { class: "field" }, h("span", {}, "Template text"), ta),
          save),
        history),
    );
  };

  views.logs = async () => {
    const box = h("div", { class: "logbox" });
    const levelSel = h("select", { style: "width:auto" }, ...["", "info", "warning", "error"].map((l) => h("option", { value: l }, l || "all levels")));
    const search = h("input", { type: "search", placeholder: "filter…", style: "width:200px" });
    const pauseBtn = h("button", { class: "btn ghost sm" }, state.logPaused ? "▶ Resume" : "⏸ Pause");
    state.logSeq = 0;

    const append = (items) => {
      const atBottom = box.scrollTop + box.clientHeight >= box.scrollHeight - 40;
      items.forEach((l) => {
        box.append(h("span", { class: "logline " + l.level },
          h("span", { class: "lt" }, new Date(l.ts).toLocaleTimeString() + " "),
          h("span", { class: "lg" }, (l.logger || "").padEnd(14).slice(0, 14) + " "),
          l.message, "\n"));
      });
      while (box.childElementCount > 4000) box.firstChild.remove();
      if (atBottom) box.scrollTop = box.scrollHeight;
    };
    const tick = async () => {
      if (state.logPaused) return;
      try {
        const d = await api(`/api/logs?after_seq=${state.logSeq}&level=${levelSel.value}&q=${encodeURIComponent(search.value)}`);
        if (d.logs?.length) { append(d.logs); state.logSeq = d.latest_seq; }
        else state.logSeq = d.latest_seq ?? state.logSeq;
      } catch { /* transient */ }
    };
    pauseBtn.onclick = () => { state.logPaused = !state.logPaused; pauseBtn.textContent = state.logPaused ? "▶ Resume" : "⏸ Pause"; };
    levelSel.onchange = search.oninput = () => { box.innerHTML = ""; state.logSeq = 0; tick(); };

    viewEl.append(
      h("div", { class: "inline", style: "margin-bottom:10px" }, h("h1", {}, "Logs"),
        h("small", { class: "muted" }, "live tail of everything — pipeline, API, scheduler, HTTP"),
        h("div", { class: "spacer" }), levelSel, search, pauseBtn,
        h("button", { class: "btn ghost sm", onclick: async () => { await api("/api/logs/clear", { method: "POST" }); box.innerHTML = ""; state.logSeq = 0; } }, "Clear")),
      box,
    );
    await tick();
    if (state.logTimer) clearInterval(state.logTimer);
    state.logTimer = setInterval(tick, 2000);
  };

  views.ops = async () => {
    const out = h("div", { class: "pre" }, "Output appears here.");
    const runBtn = (label, action, cls = "ghost") => h("button", {
      class: "btn " + cls, onclick: async (e) => {
        e.target.disabled = true; out.textContent = `Running ${action}…`;
        try {
          const d = await api(`/api/ops/${action}`, { method: "POST" });
          out.textContent = `$ ${action}  (exit ${d.exit_code}, ${d.took_s}s)\n\n${d.output || "(no output)"}`;
          toast(`${action}: exit ${d.exit_code}`, d.exit_code === 0 ? "ok" : "warn");
        } catch (err) { out.textContent = err.message; toast(err.message, "err"); }
        finally { e.target.disabled = false; }
      }
    }, label);

    const authBtn = h("button", {
      class: "btn ghost", onclick: async () => {
        try { const d = await api("/api/ops/linkedin-auth-url"); out.textContent = d.url + "\n\n" + d.note; window.open(d.url, "_blank"); }
        catch (e) { toast(e.message, "err"); }
      }
    }, "Get LinkedIn auth URL");

    const healthBtn = h("button", {
      class: "btn ghost", onclick: async () => {
        try { const r = await fetch("/health"); out.textContent = JSON.stringify(await r.json(), null, 2); }
        catch (e) { out.textContent = String(e); }
      }
    }, "Health check");

    const cfg = (await api("/api/config")).config || {};
    const cfgRows = Object.entries(cfg).map(([k, v]) => h("div", {}, h("b", { class: "muted" }, k + ": "), String(v)));

    viewEl.append(
      h("h1", {}, "Ops"),
      h("p", { class: "muted" }, "Run project scripts without leaving the browser. Output is also written to the Logs tab."),
      h("div", { class: "grid c2" },
        h("div", { class: "card" },
          h("h3", {}, "Database & templates"),
          h("div", { class: "inline" }, runBtn("Run migrations", "migrate"), runBtn("Seed prompt template", "seed")),
          h("h3", {}, "LinkedIn"),
          h("div", { class: "inline" }, runBtn("Check token expiry", "token"), authBtn),
          h("h3", {}, "Health & deploy"),
          h("div", { class: "inline" }, healthBtn, runBtn("Production checklist", "checklist")),
        ),
        h("div", { class: "card" }, h("h3", {}, "Effective config"), h("div", { class: "mono", style: "font-size:12px;line-height:1.9" }, ...cfgRows)),
      ),
      h("h3", {}, "Console"), out,
    );
  };

  // ---------------------------------------------------------------- status bar
  function updateStatusBar(d) {
    const dbDot = $("#dot-db"), tkDot = $("#dot-token"), tkLabel = $("#token-label");
    dbDot.className = "dot " + (d.db_ok ? "ok" : "err");
    const t = d.token || {};
    tkDot.className = "dot " + ({ ok: "ok", warning: "warn", critical: "err", expired: "err" }[t.state] || "");
    tkLabel.textContent = t.days != null ? `token ${t.days}d` : "token ?";
    tkLabel.title = t.message || "";
  }
  async function refreshBadges() {
    try {
      const d = await api("/api/overview");
      const b = $("#nav-approvals");
      const n = d.pending_approvals || 0;
      b.textContent = n; b.hidden = n === 0;
      updateStatusBar(d);
    } catch { /* ignore */ }
  }

  // ---------------------------------------------------------------- boot
  $("#api-key").value = apiKey();
  $("#api-key").addEventListener("change", (e) => { localStorage.setItem(KEY_STORE, e.target.value.trim()); toast("API key saved"); refreshBadges(); });
  $$("#nav a").forEach((a) => a.addEventListener("click", () => go(a.dataset.view)));
  window.addEventListener("keydown", (e) => { if (e.key === "Escape") closeDrawer(); });

  const start = location.hash.slice(1) || "overview";
  if (start.startsWith("post/")) { go("posts"); openPost(start.slice(5)); }
  else go(start);
  refreshBadges();
  setInterval(refreshBadges, 15000);
})();
