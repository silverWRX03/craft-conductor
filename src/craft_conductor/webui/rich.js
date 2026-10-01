"use strict";
// Shared by the control panel (app.js) and the friend's page (join.js).
// ---------------------------------------------------------- rich text (mod pages)
// Modrinth descriptions are Markdown with bits of HTML; CurseForge's are HTML. Both are
// turned into DOM through an allowlist, so nothing from outside can run script here.
const RICH_TAGS = new Set(["A", "P", "BR", "HR", "H1", "H2", "H3", "H4", "H5", "H6", "UL", "OL", "LI", "STRONG", "B",
  "EM", "I", "U", "S", "DEL", "CODE", "PRE", "BLOCKQUOTE", "IMG", "TABLE", "THEAD", "TBODY", "TR", "TH", "TD",
  "DETAILS", "SUMMARY", "DIV", "SPAN", "CENTER", "SUB", "SUP", "KBD", "FIGURE", "FIGCAPTION"]);
const RICH_DROP = new Set(["SCRIPT", "STYLE", "IFRAME", "OBJECT", "EMBED", "NOSCRIPT", "TEMPLATE", "SVG", "MATH",
  "FORM", "INPUT", "BUTTON", "TEXTAREA", "SELECT", "LINK", "META", "BASE", "VIDEO", "AUDIO"]);
function richFromHtml(html) {
  const doc = new DOMParser().parseFromString(html, "text/html");  // inert: nothing runs or loads
  const out = document.createDocumentFragment();
  const walk = (node, into) => {
    for (const child of node.childNodes) {
      if (child.nodeType === 3) { into.append(child.textContent); continue; }
      if (child.nodeType !== 1) continue;
      const tag = child.tagName;
      if (RICH_DROP.has(tag)) continue;
      if (!RICH_TAGS.has(tag)) { walk(child, into); continue; }
      const el = document.createElement(tag === "CENTER" ? "div" : tag.toLowerCase());
      if (tag === "A") {
        const href = child.getAttribute("href") || "";
        if (/^https?:\/\//i.test(href)) { el.href = href; el.target = "_blank"; el.rel = "noopener noreferrer"; }
      } else if (tag === "IMG") {
        const src = child.getAttribute("src") || "";
        if (!/^https:\/\//i.test(src)) continue;
        el.src = src; el.alt = child.getAttribute("alt") || ""; el.loading = "lazy"; el.referrerPolicy = "no-referrer";
        for (const a of ["width", "height"]) if (/^\d{1,4}$/.test(child.getAttribute(a) || "")) el.setAttribute(a, child.getAttribute(a));
      } else if (tag === "TD" || tag === "TH") {
        if (/^\d{1,2}$/.test(child.getAttribute("colspan") || "")) el.setAttribute("colspan", child.getAttribute("colspan"));
      }
      walk(child, el);
      into.append(el);
    }
  };
  walk(doc.body, out);
  return out;
}
function mdToHtml(md) {
  const esc = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  const inline = (s) => s
    .replace(/`([^`]+)`/g, (_, c) => `<code>${esc(c)}</code>`)
    .replace(/!\[([^\]]*)\]\((\S+?)(?:\s+"[^"]*")?\)/g, '<img alt="$1" src="$2">')
    .replace(/\[([^\]]+)\]\((\S+?)(?:\s+"[^"]*")?\)/g, '<a href="$2">$1</a>')
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>").replace(/__([^_]+)__/g, "<strong>$1</strong>")
    .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
    .replace(/~~([^~]+)~~/g, "<del>$1</del>")
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2">$2</a>');
  const out = [];
  let list = null, para = [];
  const flush = () => {
    if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
    if (list) { out.push(`</${list}>`); list = null; }
  };
  const lines = md.replace(/\r\n?/g, "\n").split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (/^\s*```/.test(line)) {
      flush();
      const code = [];
      while (++i < lines.length && !/^\s*```/.test(lines[i])) code.push(lines[i]);
      out.push(`<pre><code>${esc(code.join("\n"))}</code></pre>`);
      continue;
    }
    let m;
    if (!line.trim()) { flush(); continue; }
    if ((m = line.match(/^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$/))) { flush(); out.push(`<h${m[1].length}>${inline(m[2])}</h${m[1].length}>`); continue; }
    if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) { flush(); out.push("<hr>"); continue; }
    if ((m = line.match(/^\s*>\s?(.*)$/))) { flush(); out.push(`<blockquote>${inline(m[1])}</blockquote>`); continue; }
    if ((m = line.match(/^\s*([-*+]|\d+[.)])\s+(.*)$/))) {
      if (para.length) { out.push(`<p>${inline(para.join(" "))}</p>`); para = []; }
      const kind = /\d/.test(m[1]) ? "ol" : "ul";
      if (list !== kind) { if (list) out.push(`</${list}>`); out.push(`<${kind}>`); list = kind; }
      out.push(`<li>${inline(m[2])}</li>`);
      continue;
    }
    if (/^\s*<\/?[a-zA-Z][^>]*>\s*$/.test(line) || /^\s*<(div|center|p|img|details|summary|table|h\d|br|a)\b/i.test(line)) {
      flush(); out.push(line); continue;  // raw HTML block (sanitised below)
    }
    if (list) { out.push(`</${list}>`); list = null; }
    para.push(line.trim());
  }
  flush();
  return out.join("\n");
}
function richText(text, format) {
  const div = document.createElement("div");
  div.className = "rich";
  div.append(richFromHtml(format === "html" ? text : mdToHtml(text || "")));
  return div;
}
