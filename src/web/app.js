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
    const submit = h("button", { class: "btn" });
    const modeBanner = h("div", { class: "box", style: "margin:4px 0" });
    const syncMode = () => {
      if (dryToggle.checked) {
        modeBanner.className = "box warn";
        modeBanner.innerHTML = "<b>PREVIEW MODE.</b> Runs every check and shows you the post — but <b>nothing is sent to LinkedIn</b>. Turn the toggle off to publish.";
        submit.className = "btn ghost";
        submit.textContent = "Run preview (dry run)";
      } else {
        modeBanner.className = "box danger";
        modeBanner.innerHTML = "<b>LIVE.</b> This <b>WILL post to your LinkedIn</b>" +
          (state.overview?.config?.approval_required ? " after you approve it." : " once it passes the checks.");
        submit.className = "btn err";
        submit.textContent = "Publish to LinkedIn →";
      }
    };
    dryToggle.addEventListener("change", syncMode);
    syncMode();

    submit.addEventListener("click", async () => {
      if (!contentTa.value.trim()) { toast("write some content first", "warn"); return; }
      const live = !dryToggle.checked;
      if (live && !confirm("Publish this to your real LinkedIn account?" +
          (state.overview?.config?.approval_required ? "\n\nIt will pause for your approval first." : ""))) return;
      submit.disabled = true; submit.textContent = "Submitting…";
      try {
        const fd = new FormData();
        fd.append("text", contentTa.value.trim());
        fd.append("title", titleIn.value.trim());
        fd.append("tone", toneSel.value);
        fd.append("dry_run", live ? "false" : "true");
        if (imageFile) fd.append("image", imageFile);
        const d = await api("/api/compose", { method: "POST", body: fd });
        toast(d.dry_run ? "Preview run started — nothing will be posted" : "LIVE run started", d.dry_run ? "" : "ok");
        runPanel.hidden = false;
        trackRun(runPanel, d.upload_id, d.dry_run);
        contentTa.value = ""; titleIn.value = ""; imageFile = null; dzImg.hidden = true;
        dzText.textContent = "Drop an image here, or click to choose";
      } catch (e) {
        toast(e.message, "err");
      } finally { submit.disabled = false; syncMode(); }
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
          h("label", { class: "toggle", style: "margin:6px 0" }, dryToggle, h("span", { class: "track" }), h("span", {}, "Dry run")),
          modeBanner,
          h("div", { style: "margin-top:12px" }, submit),
          runPanel,
        ),
      ),
    );
  };

  async function trackRun(panel, uploadId, dryRun) {
    panel.innerHTML = "";
    const bar = h("div", { class: "progress" }, h("i", { style: "width:8%" }));
    const label = h("div", { class: "muted", style: "margin:8px 0 4px", html: "Starting…" });
    const outcome = h("div", { style: "margin-top:10px" });
    panel.append(h("hr", { class: "hr" }), h("h3", {}, "Status"), bar, label, outcome);
    const steps = { processing: 25, awaiting_approval: 55, scheduled: 70, publishing: 88, published: 100, approved: 100, failed: 100, rejected: 100 };
    let tries = 0;
    const poll = async () => {
      tries++;
      let post = null;
      try {
        const list = await api(`/api/posts?limit=6`);
        post = (list.posts || []).find((p) => p.upload_id === uploadId);
      } catch { /* keep trying */ }
      if (!post) {
        if (tries > 40) { label.innerHTML = "Still starting… check the Posts tab."; return; }
        return setTimeout(poll, 1500);
      }
      bar.firstChild.style.width = (steps[post.status] || 20) + "%";
      label.innerHTML = `Status: <b>` + post.status.replace(/_/g, " ") + `</b>` + (post.failed_at_node ? ` (at ${post.failed_at_node})` : "");

      if (post.status === "published") {
        outcome.innerHTML = "";
        outcome.append(h("div", { class: "box ok" }, h("b", {}, "✓ Published to LinkedIn.")),
          h("div", { class: "inline", style: "margin-top:8px" },
            post.linkedin_url && h("a", { class: "btn sm", href: post.linkedin_url, target: "_blank" }, "View on LinkedIn ↗"),
            h("button", { class: "btn sm ghost", onclick: () => openPost(post.id) }, "Open post")));
        return;
      }
      if (post.status === "approved") {   // a dry run finished — nothing was posted
        outcome.innerHTML = "";
        outcome.append(
          h("div", { class: "box warn" }, h("b", {}, "Preview passed every check — but this was a dry run, so nothing was posted to LinkedIn.")),
          h("div", { class: "inline", style: "margin-top:8px" },
            h("button", { class: "btn sm ghost", onclick: () => openPost(post.id) }, "Review the draft"),
            h("button", {
              class: "btn sm err", onclick: async (e) => {
                if (!confirm("Publish this to your real LinkedIn account now?")) return;
                e.target.disabled = true; e.target.textContent = "Publishing…";
                try { await api(`/api/posts/${post.id}/publish`, { method: "POST" }); toast("Publishing…", "ok"); tries = 0; poll(); }
                catch (err) { toast(err.message, "err"); e.target.disabled = false; e.target.textContent = "Publish to LinkedIn"; }
              }
            }, "Publish to LinkedIn")));
        return;
      }
      if (post.status === "failed") {
        outcome.innerHTML = "";
        outcome.append(h("div", { class: "box danger" }, h("b", {}, "Failed: "), esc(post.last_error || "unknown")),
          h("button", { class: "btn sm ghost", style: "margin-top:8px", onclick: () => openPost(post.id) }, "Open post"));
        return;
      }
      if (post.status === "rejected") { outcome.innerHTML = "<span class='muted'>Rejected — not published.</span>"; return; }
      if (post.status === "awaiting_approval") {
        outcome.innerHTML = "";
        outcome.append(h("div", { class: "box" }, "Waiting for your approval before it publishes."),
          h("button", { class: "btn sm", style: "margin-top:8px", onclick: () => go("approvals") }, "Go to Approvals →"));
      }
      if (tries < 200) setTimeout(poll, 1800);
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
        h("td", {}, p.linkedin_url
          ? h("a", { href: p.linkedin_url, target: "_blank", onclick: (e) => e.stopPropagation() }, "on LinkedIn ↗")
          : h("span", { class: "muted" }, "—")),
        !compact && h("td", { class: "muted" }, p.source || "—"),
        !compact && h("td", {}, p.has_image ? "🖼" : ""),
        h("td", { class: "muted" }, fmtCost(p.cost_usd)),
        h("td", { class: "muted" }, ago(p.created_at)),
      ));
    });
    return h("table", {},
      h("thead", {}, h("tr", {},
        h("th", {}, "Post"), h("th", {}, "Status"), h("th", {}, "LinkedIn"),
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
    if (["failed", "rejected", "approved"].includes(p.status) && !p.linkedin_post_id) {
      actions.append(
        h("button", {
          class: "btn sm err", onclick: async (e) => {
            if (!confirm("Publish this to your real LinkedIn account?")) return;
            e.target.disabled = true; e.target.textContent = "Publishing…";
            try { await api(`/api/posts/${id}/publish`, { method: "POST" }); toast("Publishing to LinkedIn…", "ok"); closeDrawer(); setTimeout(() => openPost(id), 1500); }
            catch (err) { toast(err.message, "err"); e.target.disabled = false; e.target.textContent = "Publish to LinkedIn"; }
          }
        }, "Publish to LinkedIn"),
        h("button", { class: "btn sm ghost", onclick: () => retryPost(id, true) }, "Re-run preview"));
    }
    if (p.linkedin_url) actions.append(h("a", { class: "btn sm ghost", href: p.linkedin_url, target: "_blank" }, "View on LinkedIn ↗"));
    actions.append(h("button", { class: "btn sm ghost", onclick: () => { navigator.clipboard?.writeText(draft.value); toast("Copied"); } }, "Copy text"));
    if (p.linkedin_post_id) actions.append(h("button", {
      class: "btn sm err", onclick: async (e) => {
        if (!confirm("Delete this post from LinkedIn? This cannot be undone.")) return;
        e.target.disabled = true; e.target.textContent = "Deleting…";
        try {
          const r = await api(`/api/posts/${id}/delete-linkedin`, { method: "POST" });
          toast("Deleted from LinkedIn", "ok");
          openPost(id);
        } catch (err) { toast(err.message, "err"); e.target.disabled = false; e.target.textContent = "Delete from LinkedIn"; }
      }
    }, "Delete from LinkedIn"));

    const tl = h("div", { class: "timeline" });
    (d.logs || []).forEach((l) => tl.append(h("div", { class: "ev " + l.level },
      h("span", { class: "dot2" }), h("span", { class: "lt mono" }, new Date(l.ts).toLocaleTimeString() + " "),
      l.node ? h("b", {}, `[${l.node}] `) : "", l.message)));
    if (!(d.logs || []).length) tl.append(h("div", { class: "muted" }, "no log events recorded"));

    const statusNote = {
      approved: ["warn", "Passed every check in a dry run — <b>not posted to LinkedIn</b>. Use “Publish to LinkedIn” below to send it for real."],
      published: ["ok", "Live on LinkedIn."],
      awaiting_approval: ["", "Waiting for your approval before it publishes."],
      scheduled: ["", "Approved — will publish automatically at its scheduled slot."],
      failed: ["danger", "The pipeline stopped. See the error and timeline below."],
      rejected: ["danger", "Rejected — not published."],
    }[p.status];

    panel.innerHTML = "";
    panel.append(
      h("div", { class: "close", onclick: closeDrawer }, "✕"),
      h("div", { class: "inline" }, h("h1", { style: "margin:0" }, p.title || "Untitled post"), pill(p.status)),
      statusNote ? h("div", { class: "box " + statusNote[0], html: statusNote[1] }) : "",
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

  views.schedule = async () => {
    const [s, q, srcs] = await Promise.all([
      api("/api/schedule"), api("/api/schedule/queue"), api("/api/sources").catch(() => ({ sources: [] })),
    ]);
    const cfg = s.schedule;
    const wdNames = s.weekday_names;

    // ---- config form ----
    const slotWrap = h("div", { class: "chips", style: "margin:4px 0" });
    const renderSlots = () => {
      slotWrap.innerHTML = "";
      cfg.slots.forEach((t, i) => slotWrap.append(h("span", { class: "chip" }, t + " ",
        h("a", { style: "color:var(--err)", onclick: () => { cfg.slots.splice(i, 1); renderSlots(); } }, "✕"))));
      const add = h("input", { type: "time", style: "width:120px" });
      add.addEventListener("change", () => { if (add.value && !cfg.slots.includes(add.value)) { cfg.slots.push(add.value); cfg.slots.sort(); renderSlots(); } });
      slotWrap.append(add);
    };
    renderSlots();

    const wdState = new Set(cfg.weekdays);
    const wdChips = wdNames.map((n, i) => {
      const chip = h("span", { class: "chip", style: wdState.has(i) ? "background:var(--accent-2);color:#fff;border-color:var(--accent-2)" : "" }, n);
      chip.addEventListener("click", () => {
        if (wdState.has(i)) { wdState.delete(i); chip.style.cssText = ""; }
        else { wdState.add(i); chip.style.cssText = "background:var(--accent-2);color:#fff;border-color:var(--accent-2)"; }
      });
      return chip;
    });
    const limitIn = h("input", { type: "number", min: "1", max: "100", value: cfg.daily_limit, style: "width:90px" });
    const fromIn = h("input", { type: "date", value: cfg.active_from || "" });
    const untilIn = h("input", { type: "date", value: cfg.active_until || "" });
    const enabledCb = h("input", { type: "checkbox", ...(cfg.enabled ? { checked: true } : {}) });
    const autoCb = h("input", { type: "checkbox", ...(cfg.auto_publish ? { checked: true } : {}) });
    const apprCb = h("input", { type: "checkbox", ...(cfg.require_approval ? { checked: true } : {}) });

    const save = h("button", {
      class: "btn", onclick: async (e) => {
        e.target.disabled = true;
        try {
          await api("/api/schedule", { method: "PUT", json: {
            slots: cfg.slots,
            weekdays: [...wdState].sort((a, b) => a - b),
            daily_limit: +limitIn.value,
            active_from: fromIn.value || null, active_until: untilIn.value || null,
            enabled: enabledCb.checked, auto_publish: autoCb.checked, require_approval: apprCb.checked,
          } });
          toast("Schedule saved", "ok"); render();
        } catch (err) { toast(err.message, "err"); e.target.disabled = false; }
      }
    }, "Save schedule");

    const perDay = cfg.slots.length;
    const activeDays = cfg.weekdays.length;

    const configCard = h("div", { class: "card" },
      h("h3", {}, "How many & when"),
      h("p", { class: "muted", style: "font-size:12px" },
        `Right now: up to `, h("b", {}, `${Math.min(cfg.daily_limit, perDay)}`), ` posts on each of `,
        h("b", {}, `${activeDays}`), ` day(s)/week — times below are in `, h("b", {}, s.timezone), `.`),
      h("label", { class: "field" }, h("span", {}, "Publish times (slots)"), slotWrap),
      h("label", { class: "field" }, h("span", {}, "Max posts per day"), limitIn),
      h("label", { class: "field" }, h("span", {}, "Active weekdays (click to toggle)"), h("div", { class: "chips" }, ...wdChips)),
      h("div", { class: "grid c2" },
        h("label", { class: "field" }, h("span", {}, "Start date (optional)"), fromIn),
        h("label", { class: "field" }, h("span", {}, "End date (optional)"), untilIn)),
      h("hr", { class: "hr" }),
      h("label", { class: "toggle", style: "margin:6px 0" }, enabledCb, h("span", { class: "track" }), h("span", {}, "Schedule enabled (pause everything if off)")),
      h("label", { class: "toggle", style: "margin:6px 0" }, autoCb, h("span", { class: "track" }), h("span", {}, "Auto-publish files from folders / Drive (off = dry-run only)")),
      h("label", { class: "toggle", style: "margin:6px 0" }, apprCb, h("span", { class: "track" }), h("span", {}, "Still require my approval on each post")),
      h("div", { style: "margin-top:12px" }, save),
    );

    // ---- upcoming queue ----
    const queueCard = h("div", { class: "card pad0" });
    queueCard.append(h("div", { style: "padding:14px 18px" }, h("h3", { style: "margin:0" }, `Upcoming (${q.total})`)));
    if (!q.days.length) queueCard.append(h("div", { class: "empty" }, "Nothing queued. Drop files in the content folder or add a Drive source."));
    q.days.forEach((day) => {
      const wrap = h("div", { style: "padding:8px 18px;border-top:1px solid var(--line)" },
        h("b", {}, day.date === "unscheduled" ? "Unscheduled" : new Date(day.date + "T00:00").toDateString()));
      day.posts.forEach((p) => wrap.append(h("div", { class: "inline", style: "margin:6px 0;font-size:13px" },
        h("span", { class: "mono", style: "width:52px;color:var(--muted)" }, p.slot || "—"),
        h("a", { onclick: () => openPost(p.id) }, p.title), pill(p.status),
        h("button", {
          class: "btn sm ghost", onclick: async () => {
            const nd = prompt("New date (YYYY-MM-DD):", day.date === "unscheduled" ? "" : day.date);
            if (!nd) return;
            const nt = prompt("New time (HH:MM):", p.slot || "09:00");
            if (!nt) return;
            try { await api(`/api/posts/${p.id}/schedule`, { method: "PATCH", json: { scheduled_date: nd, scheduled_slot: nt } }); toast("Rescheduled", "ok"); render(); }
            catch (e) { toast(e.message, "err"); }
          }
        }, "reschedule"))));
      queueCard.append(wrap);
    });

    // ---- sources ----
    const srcCard = h("div", { class: "card" }, h("h3", {}, "Content sources"));
    srcCard.append(h("p", { class: "muted", style: "font-size:12px" },
      "Add a Google Drive folder — the system checks it every 2 min and runs any new doc through the pipeline on the schedule above. Share the folder with your service-account email (the one in credentials.json)."));
    (srcs.sources || []).forEach((src) => srcCard.append(h("div", { class: "inline", style: "margin:6px 0;font-size:13px" },
      h("b", {}, src.name), h("span", { class: "mono muted" }, src.location),
      src.last_error ? h("span", { style: "color:var(--err)" }, "err: " + src.last_error.slice(0, 40)) : h("span", { class: "muted" }, src.last_polled_at ? "ok" : "not polled"),
      h("button", { class: "btn sm ghost", onclick: async () => { await api(`/api/sources/${src.id}`, { method: "PATCH", json: { enabled: !src.enabled } }); render(); } }, src.enabled ? "disable" : "enable"),
      h("button", { class: "btn sm err", onclick: async () => { if (confirm("Remove this source?")) { await api(`/api/sources/${src.id}`, { method: "DELETE" }); render(); } } }, "remove"))));
    const nameIn = h("input", { type: "text", placeholder: "label, e.g. 'LinkedIn queue'", style: "max-width:220px" });
    const locIn = h("input", { type: "text", placeholder: "Google Drive folder ID (from its URL)", style: "max-width:340px" });
    srcCard.append(h("hr", { class: "hr" }),
      h("div", { class: "inline" }, nameIn, locIn,
        h("button", {
          class: "btn sm", onclick: async () => {
            if (!locIn.value.trim()) { toast("folder ID required", "warn"); return; }
            try { await api("/api/sources", { method: "POST", json: { kind: "gdrive", name: nameIn.value, location: locIn.value.trim() } }); toast("Source added", "ok"); render(); }
            catch (e) { toast(e.message, "err"); }
          }
        }, "Add Drive folder"),
        h("button", { class: "btn sm ghost", onclick: async () => { const r = await api("/api/sources/poll", { method: "POST" }); toast(`Imported ${r.imported} file(s)`, "ok"); render(); } }, "Poll now")));

    viewEl.append(
      h("div", { class: "inline", style: "margin-bottom:12px" }, h("h1", {}, "Schedule"), h("div", { class: "spacer" }),
        h("button", { class: "btn ghost", onclick: render }, "↻ Refresh")),
      h("div", { class: "grid c2" }, configCard, h("div", {}, queueCard, h("div", { style: "height:14px" }), srcCard)),
    );
  };

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
