/* ─────────────────────────────────────────────────────────────────────────────
   Hye-tasion — Frontend JavaScript
   ───────────────────────────────────────────────────────────────────────────── */

const API = "/api";

// API key — set via the browser console: localStorage.setItem("hyebot_api_key", "your-key")
function getApiKey() {
  return localStorage.getItem("hyebot_api_key") || "";
}

// ─── Tab navigation ──────────────────────────────────────────────────────────
document.querySelectorAll(".nav-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-btn").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab").forEach((t) => t.classList.remove("active"));
    btn.classList.add("active");
    const tab = document.getElementById("tab-" + btn.dataset.tab);
    if (tab) tab.classList.add("active");

    // Lazy-load data for each tab
    switch (btn.dataset.tab) {
      case "dashboard": loadDashboard(); break;
      case "ideas":     loadIdeas();     break;
      case "abtests":   loadABTests();   break;
      case "analysis":  break; // loaded on button click
      case "sources":   loadSources();   break;
    }
  });
});

// ─── Helpers ─────────────────────────────────────────────────────────────────
async function api(path, opts = {}) {
  const url = API + path;
  const res = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": getApiKey(),
      ...(opts.headers || {}),
    },
    ...opts,
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.detail || res.statusText);
  }
  return res.json();
}

function showStatus(msg, type = "info") {
  const el = document.getElementById("action-status");
  el.textContent = msg;
  el.className = "status-msg " + (type === "error" ? "error" : type === "success" ? "success" : "");
  el.classList.remove("hidden");
  setTimeout(() => el.classList.add("hidden"), 5000);
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s;
  return d.innerHTML;
}

function badgeClass(status) {
  return "badge badge-" + (status || "pending");
}

// ─── DASHBOARD ───────────────────────────────────────────────────────────────
async function loadDashboard() {
  try {
    const s = await api("/stats");
    document.getElementById("stat-sources").textContent = s.sources;
    document.getElementById("stat-articles").textContent = s.articles_scraped;
    document.getElementById("stat-pending").textContent = s.post_ideas.pending;
    document.getElementById("stat-posted").textContent = s.post_ideas.posted;
    document.getElementById("stat-abtests").textContent = s.ab_tests.active;
    document.getElementById("stat-reddit-posts").textContent = s.reddit_posts_analyzed;
  } catch (e) {
    console.warn("Stats fetch failed:", e.message);
  }
  loadRecommendations();
}

async function loadRecommendations() {
  try {
    const r = await api("/reddit/recommendations?subreddit=ArmeniansGlobal");
    const el = document.getElementById("recommendations-list");
    if (r.recommendations && r.recommendations.length) {
      el.innerHTML = r.recommendations.map((rec) => `
        <div class="rec-item">
          <div class="rec-type">${esc(rec.type)}</div>
          <div>${esc(rec.advice)}</div>
        </div>
      `).join("");
    } else {
      el.innerHTML = '<p class="muted">' + esc(r.message || "No recommendations yet.") + "</p>";
    }
  } catch (e) {
    console.warn("Recommendations fetch failed:", e.message);
  }
}

// Quick-action buttons
document.getElementById("btn-scrape-all").addEventListener("click", async () => {
  try { await api("/scrape/all", { method: "POST" }); showStatus("Full scrape started in background.", "success"); }
  catch (e) { showStatus("Scrape failed: " + e.message, "error"); }
});

document.getElementById("btn-collect-reddit").addEventListener("click", async () => {
  try { await api("/reddit/collect", { method: "POST" }); showStatus("Reddit data collection started.", "success"); }
  catch (e) { showStatus("Reddit collect failed: " + e.message, "error"); }
});

document.getElementById("btn-run-analysis").addEventListener("click", async () => {
  try {
    showStatus("Running analysis…");
    const r = await api("/reddit/analyze", { method: "POST" });
    showStatus("Analysis complete!", "success");
    loadRecommendations();
  } catch (e) { showStatus("Analysis failed: " + e.message, "error"); }
});

document.getElementById("btn-generate-ideas").addEventListener("click", async () => {
  try {
    const r = await api("/generate-ideas", { method: "POST" });
    showStatus(`Generated ${r.generated} post ideas.`, "success");
    loadDashboard();
  } catch (e) { showStatus("Idea generation failed: " + e.message, "error"); }
});

// ─── POST IDEAS ──────────────────────────────────────────────────────────────

let ideasPage = 0;
const ideasLimit = 20;

async function loadIdeas() {
  const status = document.getElementById("filter-status").value;
  const skip = ideasPage * ideasLimit;
  let url = `/post-ideas?skip=${skip}&limit=${ideasLimit}`;
  if (status) url += `&status=${status}`;
  try {
    const data = await api(url);
    renderIdeas(data.items, data.total);
  } catch (e) {
    document.getElementById("ideas-list").innerHTML = '<p class="muted">Failed to load ideas.</p>';
  }
}

function renderIdeas(ideas, total) {
  const el = document.getElementById("ideas-list");
  if (!ideas.length) { el.innerHTML = '<p class="muted">No post ideas found.</p>'; return; }
  el.innerHTML = ideas.map((idea) => `
    <div class="idea-card" data-id="${idea.id}">
      <div>
        <div class="idea-title" onclick="openIdeaModal(${idea.id})">${esc(idea.title)}</div>
        <div class="idea-meta">
          <span class="${badgeClass(idea.status)}">${esc(idea.status)}</span>
          <span>${esc(idea.source_category || "")}</span>
          <span>${esc(idea.post_type || "")}</span>
          <span>r/${esc(idea.target_subreddit)}</span>
          ${idea.predicted_engagement_score ? `<span>⚡ ${Math.round(idea.predicted_engagement_score)}</span>` : ""}
        </div>
      </div>
      <div class="idea-actions">
        ${idea.status === "pending" || idea.status === "rejected" ? `
          <button class="btn btn-green btn-sm" onclick="approveIdea(${idea.id}, false)">✓ Approve</button>
          <button class="btn btn-yellow btn-sm" onclick="approveIdea(${idea.id}, true)">A/B Test</button>
          ${idea.status !== "rejected" ? `<button class="btn btn-red btn-sm" onclick="rejectIdea(${idea.id})">✗ Reject</button>` : ""}
        ` : ""}
      </div>
    </div>
  `).join("");

  // Pagination
  const pages = Math.ceil(total / ideasLimit);
  const pag = document.getElementById("ideas-pagination");
  if (pages > 1) {
    let html = "";
    for (let i = 0; i < pages; i++) {
      html += `<button class="page-btn ${i === ideasPage ? "active" : ""}" onclick="goToIdeasPage(${i})">${i + 1}</button>`;
    }
    pag.innerHTML = html;
  } else {
    pag.innerHTML = "";
  }
}

window.goToIdeasPage = function (p) { ideasPage = p; loadIdeas(); };

document.getElementById("filter-status").addEventListener("change", () => { ideasPage = 0; loadIdeas(); });
document.getElementById("btn-generate-ideas-2").addEventListener("click", async () => {
  try {
    const r = await api("/generate-ideas", { method: "POST" });
    showStatus(`Generated ${r.generated} post ideas.`, "success");
    loadIdeas();
  } catch (e) { showStatus("Generation failed: " + e.message, "error"); }
});

// ─── Idea modal ──────────────────────────────────────────────────────────────

window.openIdeaModal = async function (id) {
  try {
    const idea = await api(`/post-ideas/${id}`);
    document.getElementById("modal-title").textContent = "Post Idea #" + idea.id;
    document.getElementById("modal-body").innerHTML = `
      <div class="field-label">Title</div>
      <textarea id="modal-edit-title" rows="2">${esc(idea.title)}</textarea>

      <div class="field-label">Body</div>
      <textarea id="modal-edit-body" rows="5">${esc(idea.body || "")}</textarea>

      <div class="field-label">Notes</div>
      <textarea id="modal-edit-notes" rows="2">${esc(idea.notes || "")}</textarea>

      <div class="field-label">Status</div>
      <div class="field-value"><span class="${badgeClass(idea.status)}">${esc(idea.status)}</span></div>

      <div class="field-label">Source</div>
      <div class="field-value">${idea.source_url ? `<a href="${esc(idea.source_url)}" target="_blank" rel="noopener">${esc(idea.source_url)}</a>` : "—"}</div>

      <div class="field-label">Category / Type / Method</div>
      <div class="field-value">${esc(idea.source_category || "—")} / ${esc(idea.post_type || "—")} / ${esc(idea.generation_method || "—")}</div>

      ${idea.predicted_engagement_score ? `<div class="field-label">Predicted Engagement</div><div class="field-value">⚡ ${Math.round(idea.predicted_engagement_score)}</div>` : ""}
      ${idea.reddit_post_id ? `<div class="field-label">Reddit Post</div><div class="field-value"><a href="https://reddit.com/${esc(idea.reddit_post_id)}" target="_blank" rel="noopener">${esc(idea.reddit_post_id)}</a></div>` : ""}
    `;

    const footer = document.getElementById("modal-footer");
    footer.innerHTML = `
      <button class="btn btn-primary btn-sm" onclick="saveIdeaEdits(${idea.id})">Save Edits</button>
      ${idea.status === "pending" || idea.status === "rejected" ? `
        <button class="btn btn-green btn-sm" onclick="approveIdea(${idea.id}, false); closeModal();">Approve & Post</button>
        <button class="btn btn-yellow btn-sm" onclick="approveIdea(${idea.id}, true); closeModal();">Approve & A/B</button>
        ${idea.status !== "rejected" ? `<button class="btn btn-red btn-sm" onclick="rejectIdea(${idea.id}); closeModal();">Reject</button>` : ""}
      ` : ""}
    `;

    document.getElementById("modal-overlay").classList.remove("hidden");
  } catch (e) {
    showStatus("Failed to load idea: " + e.message, "error");
  }
};

window.saveIdeaEdits = async function (id) {
  const title = document.getElementById("modal-edit-title").value.trim();
  const body = document.getElementById("modal-edit-body").value.trim();
  const notes = document.getElementById("modal-edit-notes").value.trim();
  try {
    await api(`/post-ideas/${id}`, { method: "PATCH", body: JSON.stringify({ title, body, notes }) });
    showStatus("Idea updated.", "success");
    loadIdeas();
  } catch (e) { showStatus("Save failed: " + e.message, "error"); }
};

window.approveIdea = async function (id, abTest = false) {
  try {
    const body = abTest
      ? { post_immediately: false, create_ab_test: true, num_ab_variants: 2 }
      : { post_immediately: true, create_ab_test: false };
    const r = await api(`/post-ideas/${id}/approve`, { method: "POST", body: JSON.stringify(body) });
    showStatus(r.message || "Approved!", "success");
    loadIdeas();
  } catch (e) { showStatus("Approve failed: " + e.message, "error"); }
};

window.rejectIdea = async function (id) {
  const reason = prompt("Rejection reason (optional):");
  try {
    await api(`/post-ideas/${id}/reject`, { method: "POST", body: JSON.stringify({ reason: reason || "" }) });
    showStatus("Idea rejected.", "success");
    loadIdeas();
  } catch (e) { showStatus("Reject failed: " + e.message, "error"); }
};

function closeModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

document.getElementById("modal-close").addEventListener("click", closeModal);
document.getElementById("modal-overlay").addEventListener("click", (e) => {
  if (e.target === document.getElementById("modal-overlay")) closeModal();
});

// ─── A/B TESTS ───────────────────────────────────────────────────────────────

async function loadABTests() {
  try {
    const tests = await api("/ab-tests");
    const el = document.getElementById("abtests-list");
    if (!tests.length) { el.innerHTML = '<p class="muted">No A/B tests yet. Approve a post idea with A/B testing.</p>'; return; }
    el.innerHTML = tests.map((t) => `
      <div class="ab-card">
        <div class="ab-card-header">
          <div>
            <div class="ab-name">${esc(t.name)}</div>
            <div class="ab-meta">
              r/${esc(t.subreddit)} · Created ${new Date(t.created_at).toLocaleDateString()}
              ${t.concluded_at ? " · Concluded " + new Date(t.concluded_at).toLocaleDateString() : ""}
            </div>
          </div>
          <div class="idea-actions">
            ${t.is_active ? `
              <button class="btn btn-primary btn-sm" onclick="postABVariants(${t.id})">Post Variants</button>
              <button class="btn btn-secondary btn-sm" onclick="refreshABMetrics(${t.id})">Refresh</button>
              <button class="btn btn-accent btn-sm" onclick="analyzeABTest(${t.id})">Analyze</button>
            ` : `<span class="badge badge-posted">Concluded</span>`}
          </div>
        </div>
        <div class="variants-grid" id="variants-${t.id}"><p class="muted">Click to load…</p></div>
        <button class="btn btn-secondary btn-sm" style="margin-top:0.5rem" onclick="loadABVariants(${t.id})">Load Variants</button>
      </div>
    `).join("");
  } catch (e) {
    document.getElementById("abtests-list").innerHTML = '<p class="muted">Failed to load A/B tests.</p>';
  }
}

window.loadABVariants = async function (testId) {
  try {
    const t = await api(`/ab-tests/${testId}`);
    const el = document.getElementById("variants-" + testId);
    if (!t.variants || !t.variants.length) { el.innerHTML = '<p class="muted">No variants.</p>'; return; }
    el.innerHTML = t.variants.map((v) => `
      <div class="variant-card ${t.winner_variant_id === v.id ? "variant-winner" : ""}">
        <div class="variant-label">Variant ${esc(v.label)} ${t.winner_variant_id === v.id ? "🏆" : ""}</div>
        <div class="variant-title">${esc(v.title)}</div>
        <div class="variant-stats">
          <span>Strategy: ${esc(v.title_strategy || "—")}</span>
          <span>Score: ${v.score ?? "—"}</span>
          <span>↑ ${v.upvote_ratio ? (v.upvote_ratio * 100).toFixed(0) + "%" : "—"}</span>
          <span>💬 ${v.num_comments ?? "—"}</span>
          <span class="${badgeClass(v.status)}">${esc(v.status)}</span>
        </div>
      </div>
    `).join("");
  } catch (e) { showStatus("Failed to load variants: " + e.message, "error"); }
};

window.postABVariants = async function (testId) {
  try {
    const r = await api(`/ab-tests/${testId}/post-variants`, { method: "POST" });
    showStatus(r.message, "success");
  } catch (e) { showStatus("Post variants failed: " + e.message, "error"); }
};

window.refreshABMetrics = async function (testId) {
  try {
    await api(`/ab-tests/${testId}/refresh-metrics`, { method: "POST" });
    showStatus("Metrics refreshed.", "success");
    loadABVariants(testId);
  } catch (e) { showStatus("Refresh failed: " + e.message, "error"); }
};

window.analyzeABTest = async function (testId) {
  try {
    const r = await api(`/ab-tests/${testId}/analyze`, { method: "POST" });
    let msg = `Status: ${r.status}`;
    if (r.winner) msg += ` | Winner: Variant ${r.winner} (+${r.improvement_pct}%)`;
    if (r.better_strategy) msg += ` | Strategy: ${r.better_strategy}`;
    showStatus(msg, r.significant ? "success" : "info");
    loadABVariants(testId);
    loadABTests();
  } catch (e) { showStatus("Analysis failed: " + e.message, "error"); }
};

// ─── ENGAGEMENT ANALYSIS ─────────────────────────────────────────────────────

document.getElementById("btn-show-patterns").addEventListener("click", async () => {
  const sub = document.getElementById("analysis-subreddit").value.trim() || "armenia";
  try {
    const patterns = await api(`/reddit/patterns?subreddit=${encodeURIComponent(sub)}`);
    renderPatterns(patterns, sub);
  } catch (e) { showStatus("Patterns fetch failed: " + e.message, "error"); }
});

document.getElementById("btn-top-posts").addEventListener("click", async () => {
  const sub = document.getElementById("analysis-subreddit").value.trim() || "armenia";
  try {
    const data = await api(`/reddit/posts?subreddit=${encodeURIComponent(sub)}&limit=30`);
    renderTopPosts(data.items, sub);
  } catch (e) { showStatus("Posts fetch failed: " + e.message, "error"); }
});

function renderPatterns(patterns, sub) {
  const el = document.getElementById("analysis-content");
  if (!patterns.length) {
    el.innerHTML = `<p class="muted">No patterns for r/${esc(sub)}. Run "Collect Reddit Data" then "Run Engagement Analysis" first.</p>`;
    return;
  }

  // Group by type
  const byType = {};
  patterns.forEach((p) => {
    if (!byType[p.type]) byType[p.type] = [];
    byType[p.type].push(p);
  });

  let html = `<h3 style="margin-bottom:1rem;">Engagement patterns for r/${esc(sub)}</h3>`;
  for (const [type, items] of Object.entries(byType)) {
    const maxScore = Math.max(...items.map((i) => i.avg_score), 1);
    html += `<div class="patterns-section"><h3>${esc(type)}</h3>`;
    items.sort((a, b) => b.avg_score - a.avg_score);
    items.slice(0, 15).forEach((p) => {
      const pct = Math.max(5, (p.avg_score / maxScore) * 100);
      html += `
        <div class="pattern-bar-row">
          <div class="pattern-bar-label" title="${esc(p.value)}">${esc(p.value)}</div>
          <div class="pattern-bar-track"><div class="pattern-bar-fill" style="width:${pct}%"></div></div>
          <div class="pattern-bar-val">${Math.round(p.avg_score)}</div>
        </div>`;
    });
    html += `</div>`;
  }
  el.innerHTML = html;
}

function renderTopPosts(posts, sub) {
  const el = document.getElementById("analysis-content");
  if (!posts.length) {
    el.innerHTML = `<p class="muted">No Reddit posts stored for r/${esc(sub)}.</p>`;
    return;
  }
  let html = `<h3 style="margin-bottom:1rem;">Top posts in r/${esc(sub)}</h3>`;
  html += `<div class="card-list">`;
  posts.forEach((p) => {
    const permalink = p.permalink || `https://reddit.com/r/${esc(sub)}/comments/${esc(p.reddit_id)}`;
    const author = p.author ? `u/${esc(p.author)}` : "[deleted]";
    html += `
      <div class="idea-card">
        <div>
          <div class="idea-title"><a href="${esc(permalink)}" target="_blank" rel="noopener">${esc(p.title)}</a></div>
          <div class="idea-meta">
            <span>by ${author}</span>
            <span>⬆ ${p.score}</span>
            <span>↑ ${(p.upvote_ratio * 100).toFixed(0)}%</span>
            <span>💬 ${p.num_comments}</span>
            <span>${esc(p.post_type || "")}</span>
            <span>${p.has_question ? "❓" : ""}</span>
            <span>${p.has_numbers ? "🔢" : ""}</span>
            <span>Words: ${p.title_word_count || "—"}</span>
            <span>Sentiment: ${p.sentiment_score != null ? p.sentiment_score.toFixed(2) : "—"}</span>
          </div>
        </div>
      </div>`;
  });
  html += `</div>`;
  el.innerHTML = html;
}

// ─── SOURCES ─────────────────────────────────────────────────────────────────

async function loadSources() {
  try {
    const sources = await api("/sources");
    const el = document.getElementById("sources-list");
    if (!sources.length) { el.innerHTML = '<p class="muted">No sources yet. Run a scrape to populate.</p>'; return; }
    el.innerHTML = sources.map((s) => `
      <div class="source-card">
        <div>
          <div class="source-name">${esc(s.name)}</div>
          <div class="source-meta">
            ${esc(s.category)} ·
            <a href="${esc(s.url)}" target="_blank" rel="noopener">${esc(s.url)}</a>
          </div>
        </div>
        <div>
          <div style="text-align:right;font-weight:700;">${s.article_count || 0} articles</div>
          <div class="source-meta">${s.last_scraped_at ? "Last: " + new Date(s.last_scraped_at).toLocaleString() : "Never scraped"}</div>
        </div>
      </div>
    `).join("");
  } catch (e) {
    document.getElementById("sources-list").innerHTML = '<p class="muted">Failed to load sources.</p>';
  }
}

// ─── Initial load ────────────────────────────────────────────────────────────
loadDashboard();
