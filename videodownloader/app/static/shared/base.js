/* Helpers shared by the downloader and the media library. */
const UI = (() => {
  const design = document.documentElement.dataset.design || "glass";
  const terminal = design === "terminal";
  const TRASH_PIXELS = [[6, 0, 4, 1], [5, 1, 1, 1], [10, 1, 1, 1], [1, 2, 14, 2], [3, 5, 1, 9], [12, 5, 1, 9], [4, 4, 8, 1], [6, 6, 1, 6], [9, 6, 1, 6], [4, 14, 8, 1]];
  const TRASH = `<svg class="line" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2"/><path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6"/><path d="M10 11v6M14 11v6"/></svg>`
    + `<svg class="pixel" viewBox="0 0 16 16" fill="currentColor">${TRASH_PIXELS.map(([x, y, w, h]) => `<rect x="${x}" y="${y}" width="${w}" height="${h}"/>`).join("")}</svg>`;

  function size(bytes, approx = false) {
    if (bytes == null) return terminal ? "?" : "–";
    const units = terminal ? ["B", "K", "M", "G", "T"] : ["B", "KB", "MB", "GB", "TB"];
    let i = 0, v = bytes;
    while (v >= 1024 && i < units.length - 1) { v /= 1024; i++; }
    let text = i === 0 ? String(v) : v.toFixed(v < 10 ? (terminal ? 1 : 2) : 1);
    if (!terminal) text = text.replace(".", ",");
    return (approx ? "~" : "") + text + (terminal ? "" : " ") + units[i];
  }
  function duration(sec) {
    if (sec == null) return "";
    sec = Math.round(sec);
    const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
    return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
  }
  function ago(ts) {
    const d = (Date.now() / 1000 - ts) / 86400;
    if (d < 1) return "heute";
    if (d < 2) return "gestern";
    if (d < 30) return `vor ${Math.floor(d)} Tagen`;
    return new Date(ts * 1000).toLocaleDateString("de-DE");
  }
  function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
    if (!res.ok) throw new Error((await res.text()) || res.statusText);
    return res.status === 204 ? null : res.json();
  }
  function toast(text) {
    let t = document.getElementById("toast");
    if (!t) { t = document.createElement("div"); t.id = "toast"; t.className = "toast"; document.body.append(t); }
    t.textContent = text; t.classList.add("show");
    clearTimeout(toast.timer); toast.timer = setTimeout(() => t.classList.remove("show"), 2800);
  }
  function setText(el, text) { if (el && el.textContent !== text) el.textContent = text; }
  return { design, terminal, TRASH, size, duration, ago, esc, api, toast, setText };
})();
