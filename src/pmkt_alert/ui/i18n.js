"use strict";
// English UI: the app is written in Vietnamese; in English mode every visible text node and the
// placeholder/title/aria-label attributes are swapped through I18N_EN (exact match first, then the
// longest known phrases inside text that carries numbers or names). Originals are kept so switching back is exact.
const I18N = (() => {
  const dict = window.I18N_EN || {};
  const phrases = Object.keys(dict).filter((k) => k.length >= 4 && dict[k] !== k).sort((a, b) => b.length - a.length);
  const ATTRS = ["placeholder", "title", "aria-label"];
  const orig = new WeakMap();  // text node → original Vietnamese
  const origAttr = new WeakMap();  // element → {attr: original}
  let lang = "vi";
  let busy = false;

  function en(text) {
    const key = text.replace(/\s+/g, " ").trim();
    if (!key) return text;
    if (dict[key] !== undefined) return text.replace(key, dict[key]);
    let out = text;
    for (const p of phrases) if (out.includes(p)) out = out.split(p).join(dict[p]);
    return out;
  }
  function textNode(n) {
    const p = n.parentNode;
    if (p && p.tagName === "OPTION" && !p.hasAttribute("value")) return;  // its text is its value (PIC names, accounts)
    if (p && p.tagName === "TEXTAREA") return;  // editable content (e.g. the Slack message) is user text
    if (!orig.has(n)) orig.set(n, n.nodeValue);
    const want = lang === "en" ? en(orig.get(n)) : orig.get(n);
    if (n.nodeValue !== want) n.nodeValue = want;
  }
  function attrs(el) {
    let o = origAttr.get(el);
    for (const a of ATTRS) {
      if (!el.hasAttribute(a)) continue;
      if (!o) { o = {}; origAttr.set(el, o); }
      if (!(a in o)) o[a] = el.getAttribute(a);
      const want = lang === "en" ? en(o[a]) : o[a];
      if (el.getAttribute(a) !== want) el.setAttribute(a, want);
    }
  }
  function walk(root) {
    if (root.nodeType === 3) { textNode(root); return; }
    if (root.nodeType !== 1 || root.tagName === "SCRIPT" || root.tagName === "STYLE") return;
    if (root.closest && root.closest("[data-no-i18n]")) return;
    attrs(root);
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT | NodeFilter.SHOW_TEXT, {
      acceptNode: (n) => (n.nodeType === 1 && (n.tagName === "SCRIPT" || n.tagName === "STYLE" || n.hasAttribute("data-no-i18n"))
        ? NodeFilter.FILTER_REJECT : NodeFilter.FILTER_ACCEPT),
    });
    for (let n = tw.nextNode(); n; n = tw.nextNode()) (n.nodeType === 3 ? textNode(n) : attrs(n));
  }
  const mo = new MutationObserver((records) => {
    if (busy) return;
    busy = true;
    for (const r of records) {
      if (r.type === "childList") r.addedNodes.forEach(walk);
      else if (r.type === "characterData") { orig.delete(r.target); textNode(r.target); }
      else if (r.type === "attributes" && origAttr.get(r.target)) { delete origAttr.get(r.target)[r.attributeName]; attrs(r.target); }
    }
    mo.takeRecords();
    busy = false;
  });
  return {
    get lang() { return lang; },
    set(l) {
      lang = l === "en" ? "en" : "vi";
      document.documentElement.lang = lang;
      busy = true; walk(document.body); mo.takeRecords(); busy = false;
      mo.observe(document.body, { subtree: true, childList: true, characterData: true, attributes: true, attributeFilter: ATTRS });
    },
    t: (text) => (lang === "en" ? en(text) : text),  // for alert()/confirm()/prompt() text that never reaches the DOM
  };
})();
