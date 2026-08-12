(function () {
  "use strict";

  var root = document.querySelector("[data-access-workspace]");
  if (!root) return;
  var compact = window.matchMedia("(max-width: 1499px)");
  var panel = root.querySelector("[data-access-panel]");
  var focusKey = "access-workspace-focus";

  function isCompact() { return compact.matches; }

  function focusables(container) {
    return Array.from(container.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"));
  }

  function setPanelMode() {
    panel = root.querySelector("[data-access-panel]");
    var backgroundRegions = root.querySelectorAll(".access-workspace-head, .access-tabs, .access-table-panel, [data-access-panel]");
    if (!panel) {
      backgroundRegions.forEach(function (region) { region.removeAttribute("inert"); });
      return;
    }
    if (isCompact()) {
      panel.setAttribute("role", "dialog");
      panel.setAttribute("aria-modal", "true");
      backgroundRegions.forEach(function (region) {
        if (region !== panel) region.setAttribute("inert", "");
      });
    } else {
      panel.removeAttribute("role");
      panel.removeAttribute("aria-modal");
      backgroundRegions.forEach(function (region) { region.removeAttribute("inert"); });
    }
  }

  function rememberFocus(link) {
    if (!link) return;
    try { sessionStorage.setItem(focusKey, link.getAttribute("href") || ""); } catch (_) {}
  }

  function restoreFocus() {
    if (panel) return;
    var href;
    try { href = sessionStorage.getItem(focusKey); sessionStorage.removeItem(focusKey); } catch (_) { return; }
    if (!href) return;
    var target = Array.from(root.querySelectorAll("a[href]")).find(function (link) { return link.getAttribute("href") === href; });
    if (target) target.focus();
  }

  function dirtyForms() {
    return Array.from(root.querySelectorAll("form[data-access-dirty='true']"));
  }

  function canLeave() {
    return !dirtyForms().length || window.confirm("Есть несохранённые изменения. Покинуть редактор?");
  }

  function trapFocus(event) {
    if (!panel || !isCompact() || event.key !== "Tab") return;
    var items = focusables(panel);
    if (!items.length) return;
    var first = items[0];
    var last = items[items.length - 1];
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  }

  function markDirty(form) {
    if (form.dataset.accessDirtyBound === "true") return;
    form.dataset.accessDirtyBound = "true";
    form.addEventListener("input", function () { form.dataset.accessDirty = "true"; });
    form.addEventListener("change", function () { form.dataset.accessDirty = "true"; });
    form.addEventListener("submit", function () { form.dataset.accessDirty = "false"; });
  }

  root.addEventListener("click", function (event) {
    var link = event.target.closest("a");
    if (!link || !root.contains(link)) return;
    if (!canLeave()) { event.preventDefault(); return; }
    if (link.closest(".access-object-link, .access-cell-link, .access-status-link")) rememberFocus(link);
    // Close buttons navigate through their explicit safe href.  Do not mutate
    // the DOM with pushState: the server remains the source of URL state.
  });

  document.addEventListener("keydown", function (event) {
    if (!panel || !root.contains(panel)) return;
    if (event.key === "Tab") { trapFocus(event); return; }
    if (event.key !== "Escape") return;
    var close = panel.querySelector(".access-panel-close");
    if (!close || !canLeave()) return;
    event.preventDefault();
    close.click();
  });

  root.querySelectorAll("form").forEach(markDirty);
  window.addEventListener("beforeunload", function (event) {
    if (!dirtyForms().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
  setPanelMode();
  compact.addEventListener?.("change", setPanelMode);
  restoreFocus();
  if (panel) {
    var initial = focusables(panel)[0];
    if (initial && isCompact()) initial.focus();
  }
})();
