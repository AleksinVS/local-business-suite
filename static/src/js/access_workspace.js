(function () {
  "use strict";

  var root = document.querySelector("[data-access-workspace]");
  if (!root) return;
  var compact = window.matchMedia("(max-width: 1200px)");
  var focusKey = "access-workspace-focus";
  var activePanel = null;

  function revealFieldSidebar() {
    var field = document.querySelector(".access-sidebar-editor[data-access-panel='field']");
    var sidebar = field && field.closest(".sidebar-nav--access");
    if (!sidebar) return;
    sidebar.classList.remove("collapsed");
    var toggle = document.querySelector('.sidebar-toggle[aria-controls="sidebar"]');
    if (toggle) {
      toggle.setAttribute("aria-expanded", "true");
      toggle.setAttribute("aria-label", "Свернуть боковую панель");
    }
  }

  function isCompact() { return compact.matches; }

  function findActivePanel() {
    var inspector = document.querySelector(".access-inspector.drawer.active");
    var field = document.querySelector(".access-sidebar-editor[data-access-panel='field']");
    return field && isCompact() ? field : (inspector || field);
  }

  function isModalPanel(panel) {
    return Boolean(panel && (panel.classList.contains("access-inspector") || isCompact()));
  }

  function focusables(container) {
    return Array.from(container.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])"));
  }

  function markBackground() {
    activePanel = findActivePanel();
    var modal = isModalPanel(activePanel);
    var background = document.querySelectorAll("[data-access-workspace], .access-workspace-head, .access-tabs, .access-table-panel, .site-header, .sidebar-nav");
    background.forEach(function (region) {
      if (!modal || region === activePanel || region.contains(activePanel)) region.removeAttribute("inert");
      else region.setAttribute("inert", "");
    });
    if (activePanel && modal) {
      activePanel.setAttribute("role", "dialog");
      activePanel.setAttribute("aria-modal", "true");
      activePanel.removeAttribute("aria-hidden");
    } else if (activePanel) {
      activePanel.removeAttribute("role");
      activePanel.removeAttribute("aria-modal");
    }
  }

  function rememberFocus(link) {
    if (!link) return;
    try { sessionStorage.setItem(focusKey, link.getAttribute("href") || ""); } catch (_) {}
  }

  function restoreFocus() {
    var href;
    try { href = sessionStorage.getItem(focusKey); } catch (_) { return true; }
    if (!href) return true;
    // Keep the source reference while a server-rendered panel is open.  The
    // next close navigation will render the list and only then consume it.
    if (activePanel) return false;
    var target = Array.from(root.querySelectorAll("a[href]")).find(function (link) { return link.getAttribute("href") === href; });
    if (!target) {
      try { sessionStorage.removeItem(focusKey); } catch (_) {}
      return true;
    }
    try { sessionStorage.removeItem(focusKey); } catch (_) {}
    target.focus();
    return true;
  }

  function dirtyForms() {
    return Array.from(document.querySelectorAll(".access-context-form[data-access-dirty='true']"));
  }

  function canLeave() {
    var dirty = dirtyForms();
    if (!dirty.length) return true;
    if (!window.confirm("Есть несохранённые изменения. Покинуть редактор?")) return false;
    // Confirmation means that the current draft is intentionally discarded.
    // Clearing the marker also prevents a second beforeunload prompt while the
    // accepted link or form navigation is being completed.
    dirty.forEach(function (form) { form.dataset.accessDirty = "false"; });
    return true;
  }

  function trapFocus(event) {
    if (!isModalPanel(activePanel) || event.key !== "Tab") return;
    var items = focusables(activePanel);
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

  document.addEventListener("click", function (event) {
    var sidebarToggle = event.target.closest(".sidebar-toggle");
    if (sidebarToggle && !canLeave()) {
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    var link = event.target.closest("a");
    if (!link) return;
    var sameOrigin = link.origin === window.location.origin;
    if (!sameOrigin || !canLeave()) {
      if (!sameOrigin) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      return;
    }
    if (link.closest(".access-panel-close, .access-inspector-overlay")) return;
    var source = link.closest(".access-object-link, .access-cell-link, .access-status-link");
    if (source && !findActivePanel()) rememberFocus(source);
  }, true);

  document.addEventListener("submit", function (event) {
    var form = event.target;
    if (!form || form.matches(".access-context-form") || canLeave()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
  }, true);

  document.addEventListener("keydown", function (event) {
    activePanel = findActivePanel();
    if (!activePanel) return;
    if (event.key === "Tab") { trapFocus(event); return; }
    if (event.key !== "Escape" || !canLeave()) return;
    var close = activePanel.querySelector(".access-panel-close");
    if (!close) return;
    event.preventDefault();
    close.click();
  });

  document.querySelectorAll(".access-context-form").forEach(markDirty);
  window.addEventListener("beforeunload", function (event) {
    if (!dirtyForms().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
  compact.addEventListener?.("change", markBackground);
  revealFieldSidebar();
  markBackground();
  if (!restoreFocus()) {
    window.requestAnimationFrame(restoreFocus);
    document.addEventListener("DOMContentLoaded", restoreFocus, { once: true });
  }
  if (isModalPanel(activePanel)) {
    var initial = focusables(activePanel)[0];
    if (initial) initial.focus();
  }
})();
