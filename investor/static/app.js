/* Shared helpers for every StockRadar page. */
const SR = (() => {
  const $ = (s, el = document) => el.querySelector(s);
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  const url = (u) => /^https?:\/\//i.test(u || "") ? esc(u) : "#";  // never render javascript: links from feeds

  const api = async (path) => {
    const r = await fetch(path);
    if (!r.ok) throw new Error(`${path} → ${r.status}`);
    return r.json();
  };

  // ── Formatting ──
  const pct = (v, d = 1, sign = false) => v == null ? "—" : `${sign && v > 0 ? "+" : ""}${(v * 100).toFixed(d)}%`;
  const x = (v, d = 1) => v == null ? "—" : `${v.toFixed(d)}×`;
  const n = (v, d = 2) => v == null ? "—" : Number(v).toFixed(d);
  const money = (v) => v == null ? "—" : `$${Number(v).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  const cap = (v) => {
    if (v == null) return "—";
    const a = Math.abs(v);
    if (a >= 1e12) return `$${(v / 1e12).toFixed(2)}T`;
    if (a >= 1e9) return `$${(v / 1e9).toFixed(1)}B`;
    if (a >= 1e6) return `$${(v / 1e6).toFixed(0)}M`;
    return `$${Math.round(v).toLocaleString()}`;
  };
  const ago = (iso) => {
    if (!iso) return "";
    const s = (Date.now() - new Date(iso).getTime()) / 1000;
    if (s < 3600) return `${Math.max(1, Math.round(s / 60))}m ago`;
    if (s < 86400) return `${Math.round(s / 3600)}h ago`;
    return `${Math.round(s / 86400)}d ago`;
  };
  const chg = (v) => v == null ? "" : `<span class="${v >= 0 ? "chg-up" : "chg-dn"} num">${v >= 0 ? "▲" : "▼"} ${pct(Math.abs(v))}</span>`;

  // ── Scores ──
  const band = (v) => v == null ? "s-na" : v >= 65 ? "s-hi" : v >= 40 ? "s-mid" : "s-lo";
  const pill = (v, label) => `<span class="score ${band(v)}" title="${label ? esc(label) + " score " : ""}${v == null ? "n/a" : Math.round(v)} / 100">${label ? `<span>${esc(label)}</span>` : ""}<b>${v == null ? "–" : Math.round(v)}</b></span>`;
  const WARN_TAGS = new Set(["Hype Warning"]);
  const tags = (list) => `<div class="tags">${(list || []).map((t) => `<span class="tag ${WARN_TAGS.has(t) ? "warn" : ""}">${esc(t)}</span>`).join("")}</div>`;

  const pickCard = (r, extra = "") => `
    <a class="card pick" href="/stock/${encodeURIComponent(r.ticker)}">
      <div class="pick-head">
        <div><div class="tkr">${esc(r.ticker)}</div><div class="co">${esc(r.name)}</div></div>
        <div style="text-align:right"><div class="num">${money(r.price)}</div><div class="small muted">${esc(r.sector || "")}</div></div>
      </div>
      <div class="scorebar">${pill(r.value, "Value")}${pill(r.growth, "Growth")}${pill(r.quality, "Quality")}${pill(r.momentum, "Momentum")}</div>
      ${extra}
      <ul class="why">${(r.reasons?.good || []).slice(0, 2).map((w) => `<li>${esc(w)}</li>`).join("")}${(r.reasons?.bad || []).slice(0, 1).map((w) => `<li class="bad">${esc(w)}</li>`).join("")}</ul>
      ${tags(r.tags)}
    </a>`;

  // ── Watchlist (per-browser) ──
  const WL = "sr-watchlist";
  const watchlist = {
    all() { try { return JSON.parse(localStorage.getItem(WL)) || []; } catch (e) { return []; } },
    has(t) { return this.all().includes(t); },
    toggle(t) {
      const cur = this.all();
      const next = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
      try { localStorage.setItem(WL, JSON.stringify(next)); } catch (e) {}
      return next.includes(t);
    },
  };

  const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ── Page chrome ──
  const initChrome = async () => {
    $("#themeBtn")?.addEventListener("click", () => {
      const root = document.documentElement;
      const dark = root.dataset.theme ? root.dataset.theme === "dark" : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("sr-theme", root.dataset.theme); } catch (e) {}
      window.dispatchEvent(new Event("sr-theme"));
    });
    try {
      const meta = await api("/api/meta");
      SR.meta = meta;
      if (meta.status?.demo) $("#demoBanner").hidden = false;
      window.dispatchEvent(new Event("sr-meta"));
    } catch (e) { console.warn(e); }
    try {
      const all = await api("/api/screen?limit=2000");
      $("#tickerlist").innerHTML = all.results.map((r) => `<option value="${esc(r.ticker)}">${esc(r.name)}</option>`).join("");
    } catch (e) {}
  };

  return { $, esc, url, api, pct, x, n, money, cap, ago, chg, band, pill, tags, pickCard, watchlist, cssVar, initChrome };
})();
SR.initChrome();
