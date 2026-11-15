// Reel Engine dashboard — plain JS, no build step.
const S = { tab: "radar", niche: "", window: 7, sort: "outlier", q: "", board: "", limit: 60, rows: [] };
const $ = (s, el = document) => el.querySelector(s);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const fmt = (n) => n == null ? "–" : n >= 1e6 ? (n / 1e6).toFixed(1) + "M" : n >= 1e3 ? (n / 1e3).toFixed(1) + "K" : Math.round(n) + "";
const ago = (iso) => { if (!iso) return ""; const h = (Date.now() - Date.parse(iso)) / 36e5; return h < 1 / 60 ? "just now" : h < 1 ? Math.round(h * 60) + "m ago" : h < 24 ? Math.round(h) + "h ago" : Math.round(h / 24) + "d ago"; };
const api = async (path, opts) => { const r = await fetch(path, opts); if (!r.ok) throw new Error(await r.text()); return r.json(); };
const save = (k, v) => { try { localStorage.setItem("re." + k, v); } catch (e) {} };
const load = (k) => { try { return localStorage.getItem("re." + k); } catch (e) { return null; } };

async function init() {
  const niches = await api("/api/niches");
  $("#niche").innerHTML = niches.map((n) => `<option value="${esc(n.slug)}">${esc(n.name)}</option>`).join("");
  S.niche = load("niche") || niches[0]?.slug || "";
  $("#niche").value = S.niche;
  $("#niche").onchange = (e) => { S.niche = e.target.value; save("niche", S.niche); refresh(); };
  $("#tabs").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.tab = b.dataset.tab; [...$("#tabs").children].forEach((x) => x.classList.toggle("on", x === b)); refresh(); };
  $("#window").onclick = (e) => { const b = e.target.closest("button"); if (!b) return; S.window = +b.dataset.w; [...$("#window").children].forEach((x) => x.classList.toggle("on", x === b)); refresh(); };
  $("#sort").onchange = (e) => { S.sort = e.target.value; refresh(); };
  let t; $("#q").oninput = (e) => { clearTimeout(t); t = setTimeout(() => { S.q = e.target.value.trim(); refresh(); }, 300); };
  $("#board").onchange = (e) => { S.board = e.target.value; refresh(); };
  $("#close").onclick = closeDetail; $("#scrim").onclick = closeDetail;
  document.addEventListener("keydown", (e) => e.key === "Escape" && closeDetail());
  refresh();
}

async function refresh() {
  S.limit = 60;
  const st = await api("/api/stats?niche=" + encodeURIComponent(S.niche));
  $("#stats").textContent = `${st.total || 0} reels · ${st.creators || 0} creators · ${st.analyzed || 0} decoded` + (st.last_scan ? ` · scanned ${ago(st.last_scan)}` : "");
  const gridTabs = ["radar", "library", "mine"];
  $("#controls").classList.toggle("hide", !gridTabs.includes(S.tab));
  $("#board").classList.toggle("hide", S.tab !== "library");
  if (S.tab === "library") {
    const boards = await api("/api/boards?niche=" + encodeURIComponent(S.niche));
    $("#board").innerHTML = `<option value="">All boards</option>` + boards.map((b) => `<option ${b.board === S.board ? "selected" : ""}>${esc(b.board)}</option>`).join("");
  }
  if (gridTabs.includes(S.tab)) return renderGrid();
  if (S.tab === "cards") return renderCards();
  if (S.tab === "scripts") return renderScripts();
}

async function renderGrid() {
  const p = new URLSearchParams({ niche: S.niche, window: S.window, sort: S.sort, limit: S.limit });
  if (S.q) p.set("q", S.q);
  if (S.tab === "library") p.set("saved", 1);
  if (S.tab === "mine") p.set("mine", 1);
  let rows = await api("/api/reels?" + p);
  if (S.tab === "library" && S.board) rows = rows.filter((r) => r.board === S.board);
  S.rows = rows;
  if (!rows.length) {
    $("#view").innerHTML = S.tab === "radar" && !S.q ? $("#empty-radar").innerHTML
      : `<div class="empty"><h2>${S.tab === "library" ? "Nothing saved yet" : S.tab === "mine" ? "No reels from your account yet" : "No matches"}</h2><p>${S.tab === "library" ? "Open a reel on the Radar and press Save." : S.tab === "mine" ? "Add your username as <code>self_username</code> in the niche recipe, then scrape." : "Try a wider time window or another search."}</p></div>`;
    return;
  }
  $("#view").innerHTML = `<div class="grid">${rows.map(card).join("")}</div>` + (rows.length >= S.limit ? `<button class="more" id="more">Show more</button>` : "");
  $("#view").querySelectorAll(".card").forEach((el) => {
    el.onclick = () => openDetail(el.dataset.sc);
    const v = el.querySelector("video");
    if (v) { el.onmouseenter = () => v.play().catch(() => {}); el.onmouseleave = () => { v.pause(); v.currentTime = 0; }; }
  });
  const more = $("#more"); if (more) more.onclick = () => { S.limit += 60; renderGrid(); };
}

function card(r) {
  const hot = (r.outlier || 0) >= 3;
  const thumb = r.has_thumb ? `<img loading="lazy" src="/media/${r.shortcode}/thumb.jpg" alt="">` : (r.has_analysis ? `<img loading="lazy" src="/media/${r.shortcode}/frames/00.jpg" alt="">` : "");
  const vid = r.has_video ? `<video muted loop playsinline preload="none" src="/media/${r.shortcode}/video.mp4"></video>` : "";
  return `<article class="card" data-sc="${esc(r.shortcode)}">
    <div class="media">${thumb}${vid}
      ${r.outlier ? `<span class="badge ${hot ? "" : "low"}">${r.outlier}x</span>` : ""}
      <div class="flags">${r.has_card ? `<span class="ok">Style Card</span>` : r.has_analysis ? `<span>decoded</span>` : ""}${r.saved ? "<span>saved</span>" : ""}</div>
    </div>
    <div class="meta">
      <div class="owner">@${esc(r.owner || "unknown")} · ${ago(r.posted_at)}</div>
      <div class="nums"><div><b>${fmt(r.views_best)}</b><span>views</span></div><div><b>${fmt(r.likes)}</b><span>likes</span></div><div><b>${fmt(r.comments)}</b><span>comm.</span></div>${r.shares != null ? `<div><b>${fmt(r.shares)}</b><span>shares</span></div>` : ""}</div>
      <div class="cap">${esc((r.caption || "").slice(0, 160))}</div>
    </div></article>`;
}

function closeDetail() { $("#drawer").hidden = true; $("#scrim").hidden = true; $("#detail").innerHTML = ""; }

async function openDetail(sc) {
  const r = await api("/api/reels/" + encodeURIComponent(sc));
  const a = r.analysis, c = r.stylecard, m = a?.metrics || {};
  const igLink = r.source === "file" ? "" : r.source === "url" ? "" : `https://www.instagram.com/reel/${r.shortcode}/`;
  const player = r.has_video ? `<video id="player" controls playsinline src="/media/${r.shortcode}/video.mp4"></video>`
    : `<div class="noplay">Video not downloaded yet.<br><br><code>engine.cmd analyze --reel ${esc(r.shortcode)}</code></div>`;
  $("#detail").innerHTML = `<div class="detail">
    <div>${player}
      <div class="row" style="margin-top:12px">
        <button class="btn ${r.saved ? "" : "primary"}" id="savebtn">${r.saved ? "Saved ✓" : "Save to Library"}</button>
        ${igLink ? `<a class="btn" href="${igLink}" target="_blank" rel="noopener">Open on Instagram</a>` : ""}
      </div>
      <div class="row" style="margin-top:10px"><input id="boardin" placeholder="Board, e.g. Price reveal" value="${esc(r.board || "")}"><input id="tagsin" placeholder="Tags" value="${esc(r.tags || "")}"></div>
      <p class="hint">Board and tags save when you leave the field.</p>
      ${sparkline(r.snapshots)}
    </div>
    <div>
      <div class="owner">@${esc(r.owner)} · posted ${ago(r.posted_at)} · ${esc(r.source || "")}</div>
      <div class="kpis" style="margin-top:10px">
        <div class="kpi hot"><b>${r.outlier ? r.outlier + "x" : "–"}</b><span>vs creator median ${fmt(r.creator_median)}</span></div>
        <div class="kpi"><b>${fmt(r.views_best)}</b><span>views · ${fmt(r.likes)} likes · ${fmt(r.shares)} shares</span></div>
        <div class="kpi"><b>${r.engagement ?? "–"}%</b><span>engagement</span></div>
        <div class="kpi"><b>${fmt(r.velocity)}</b><span>views / hour</span></div>
      </div>
      <div class="box md">${esc(r.caption || "")}</div>
      ${a ? analysisHtml(r, a, m) : `<h3>Breakdown</h3><div class="box hint">Not decoded yet. Run <code>engine.cmd analyze --reel ${esc(r.shortcode)}</code>, then ask Claude Code: “make a style card for ${esc(r.shortcode)}”.</div>`}
      ${c ? styleCardHtml(c) : a ? `<h3>Style Card</h3><div class="box hint">No Style Card yet. In Claude Code, ask: “make a style card for ${esc(r.shortcode)}”.</div>` : ""}
      ${r.breakdown ? `<h3>Hook & structure breakdown</h3><div class="box md">${esc(r.breakdown)}</div>` : ""}
    </div></div>`;
  $("#drawer").hidden = false; $("#scrim").hidden = false; $("#drawer").scrollTop = 0;
  $("#savebtn").onclick = async () => { await api(`/api/reels/${sc}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ saved: !r.saved }) }); openDetail(sc); refreshQuiet(); };
  const saveField = (k) => async (e) => { await api(`/api/reels/${sc}/save`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [k]: e.target.value, saved: true }) }); refreshQuiet(); };
  $("#boardin").onchange = saveField("board"); $("#tagsin").onchange = saveField("tags");
  const player2 = $("#player");
  $("#detail").querySelectorAll("[data-t]").forEach((el) => el.onclick = () => { if (player2) { player2.currentTime = +el.dataset.t; player2.play(); } });
}

function refreshQuiet() { if (["radar", "library", "mine"].includes(S.tab)) renderGrid(); }

function sparkline(snaps) {
  const pts = (snaps || []).filter((s) => s.views != null);
  if (pts.length < 2) return "";
  const xs = pts.map((p) => Date.parse(p.ts)), ys = pts.map((p) => p.views);
  const x0 = Math.min(...xs), x1 = Math.max(...xs), y1 = Math.max(...ys), y0 = Math.min(...ys);
  const path = pts.map((p, i) => `${i ? "L" : "M"}${((xs[i] - x0) / (x1 - x0 || 1) * 300).toFixed(1)},${(56 - (ys[i] - y0) / (y1 - y0 || 1) * 50).toFixed(1)}`).join("");
  return `<h3>Views over time</h3><svg class="spark" viewBox="0 0 300 60" preserveAspectRatio="none"><path d="${path}" fill="none" stroke="var(--accent)" stroke-width="2"/></svg>
    <div class="legend"><span>${fmt(y0)}</span><span>${pts.length} checks</span><span>${fmt(y1)}</span></div>`;
}

function analysisHtml(r, a, m) {
  const dur = a.video?.duration || 1;
  const hookEnd = Math.min(3, dur);
  const words = a.transcript?.words || [];
  const transcript = words.length
    ? words.map((w) => `<span data-t="${w.start}" class="${w.start < 3 ? "hook" : ""}">${esc(w.word)}</span>`).join(" ")
    : `<span class="hint">No speech found.</span>`;
  const shots = (a.shots || []).map((s) => `<div class="shot" data-t="${s.start}" title="${s.start}s – ${s.end}s" style="left:${s.start / dur * 100}%;width:${(s.end - s.start) / dur * 100}%"></div>`).join("");
  const pal = (a.colour?.palette || []).map((p) => `<div title="${esc(p.hex)} · ${Math.round(p.share * 100)}%" style="background:${color(p.hex, "#333")};width:${+p.share * 100}%"></div>`).join("");
  const frames = (a.frames || []).map((f) => {
    const v = f.vision && !f.vision.error ? f.vision : null;
    const note = v ? [v.shot_type, v.on_screen_text && `“${v.on_screen_text}”`].filter(Boolean).join(" · ") : "";
    return `<figure><img data-t="${f.t}" src="/media/${r.shortcode}/${f.file}" alt=""><figcaption>${f.t}s${note ? " · " + esc(note.slice(0, 80)) : ""}</figcaption></figure>`;
  }).join("");
  return `
    <h3>Hook (first 3 seconds)</h3><div class="box"><b>${esc(m.hook_text || "—")}</b></div>
    <h3>Transcript <span class="hint">· ${esc(a.transcript?.language || "")} · click a word to jump</span></h3><div class="box transcript md">${transcript}</div>
    <h3>Cuts <span class="hint">· ${m.shots} shots · ${m.cuts_per_10s} cuts per 10 s · avg ${m.avg_shot_seconds}s</span></h3>
    <div class="timeline"><div class="hookzone" style="width:${hookEnd / dur * 100}%"></div>${shots}</div>
    <div class="legend"><span>0s</span><span>hook zone shaded</span><span>${Math.round(dur)}s</span></div>
    <h3>Colour <span class="hint">· ${esc(a.colour?.grade || "")}</span></h3><div class="swatches">${pal}</div>
    <h3>Key frames ${a.vision_model ? `<span class="hint">· read by ${esc(a.vision_model)}</span>` : ""}</h3><div class="frames">${frames}</div>
    <h3>Numbers</h3><dl class="box kv">
      <dt>Duration</dt><dd>${m.duration}s</dd><dt>Words per minute</dt><dd>${m.words_per_minute}</dd>
      <dt>Speech coverage</dt><dd>${Math.round((m.speech_ratio || 0) * 100)}%</dd><dt>First cut at</dt><dd>${m.first_cut_at ?? "no cuts"}${m.first_cut_at != null ? "s" : ""}</dd>
      <dt>Brightness / saturation</dt><dd>${a.colour?.brightness ?? "–"} / ${a.colour?.saturation ?? "–"}</dd></dl>`;
}

const color = (v, d) => /^#[0-9a-f]{3,8}$/i.test(String(v || "")) ? v : d;

function styleCardHtml(c) {
  const cap = { ...(c.captions || {}) };
  cap.color = color(cap.color, "#fff"); cap.highlight_color = color(cap.highlight_color, "#ffd400"); cap.box_color = color(cap.box_color, "#000");
  const pace = c.pacing || {};
  const capStyle = `color:${cap.color || "#fff"};text-transform:${cap.case === "upper" ? "uppercase" : "none"};${cap.background === "box" ? `background:${cap.box_color || "#000"};` : ""}${cap.stroke ? "-webkit-text-stroke:1px #000;" : ""}`;
  const sample = (cap.sample || "This flat costs less than your rent").split(" ");
  const hi = Math.min(2, sample.length - 1);
  return `<h3>Style Card</h3><div class="sc">
    <h4>${esc(c.name || "Style")}</h4><div class="sub">${esc(c.summary || "")}</div>
    <div class="capsample" style="${capStyle}">${sample.map((w, i) => i === hi ? `<span style="color:${cap.highlight_color || "#ffd400"}">${esc(w)}</span>` : esc(w)).join(" ")}</div>
    <dl class="kv">
      <dt>Hook</dt><dd>${esc(c.hook?.type || "")} — ${esc(c.hook?.text || "")}</dd>
      <dt>Captions</dt><dd>${esc([cap.style, cap.position, cap.font, cap.case].filter(Boolean).join(" · "))}</dd>
      <dt>Pacing</dt><dd>${pace.cuts_per_10s ?? "–"} cuts / 10 s${pace.zoom_on_cut ? ` · ${pace.punch_in_pct || ""}% punch-in on cuts` : ""}</dd>
      <dt>Colour</dt><dd>${esc(c.colour?.grade || "")}</dd>
      <dt>Audio</dt><dd>${esc([c.audio?.music, c.audio?.energy].filter(Boolean).join(" · "))}</dd>
      <dt>CTA</dt><dd>${esc(c.cta || "")}</dd>
    </dl>
    ${(c.structure || []).length ? `<h3>Structure</h3><div class="box md">${c.structure.map((s) => `${s.start}–${s.end}s  ${esc(s.part)}: ${esc(s.what)}`).join("\n")}</div>` : ""}
    ${(c.do || []).length ? `<h3>Copy this</h3><div class="box md">${c.do.map((x) => "• " + esc(x)).join("\n")}</div>` : ""}
  </div>`;
}

async function renderCards() {
  const cards = await api("/api/cards");
  if (!cards.length) {
    $("#view").innerHTML = `<div class="empty"><h2>No Style Cards yet</h2><p>Decode a reel, then in Claude Code ask:<br><code>make a style card for &lt;shortcode&gt;</code><br><br>To merge several into your own look:<br><code>make a house style from my 3 favourite style cards</code></p></div>`;
    return;
  }
  $("#view").innerHTML = `<div class="cards">${cards.map((c) => `<div class="sc-wrap" ${c._shortcode ? `data-sc="${esc(c._shortcode)}"` : ""}>${styleCardHtml(c).replace("<h3>Style Card</h3>", `<div class="hint" style="margin-bottom:6px">${c._kind === "house" ? "House style · " + esc(c._file) : "From reel " + esc(c._shortcode)}</div>`)}</div>`).join("")}</div>`;
  $("#view").querySelectorAll("[data-sc]").forEach((el) => { el.style.cursor = "pointer"; el.onclick = () => openDetail(el.dataset.sc); });
}

async function renderScripts() {
  const scripts = await api("/api/scripts");
  if (!scripts.length) {
    $("#view").innerHTML = `<div class="empty"><h2>No scripts yet</h2><p>In Claude Code, ask:<br><code>write 3 scripts on home-loan mistakes using the style of &lt;shortcode&gt;</code></p></div>`;
    return;
  }
  $("#view").innerHTML = `<div class="scripts">${scripts.map((s) => `<div class="sc"><h4>${esc(s.title)}</h4><div class="sub">${esc(s.file)} · ${new Date(s.modified * 1000).toLocaleString()}</div><div class="md">${esc(s.text)}</div></div>`).join("")}</div>`;
}

init();
