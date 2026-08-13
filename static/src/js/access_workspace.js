(function () {
  "use strict";

  var root = document.querySelector("[data-access-workspace]");
  if (!root) return;
  var compact = window.matchMedia("(max-width: 1200px)");
  var focusKey = "access-workspace-focus";
  var activePanel = null;
  var pendingNavigation = null;

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
    root = document.querySelector("[data-access-workspace]");
    if (!root) return true;
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
    form.addEventListener("submit", function (event) {
      form.dataset.accessSubmittedDirty = form.dataset.accessDirty === "true" ? "true" : "false";
      var submitter = event.submitter;
      if (submitter) {
        form.dataset.accessSubmitterName = submitter.name || "";
        form.dataset.accessSubmitterValue = submitter.value || "";
      }
      form.dataset.accessDirty = "false";
    });
  }

  function refreshPanels() {
    root = document.querySelector("[data-access-workspace]");
    var navigation = pendingNavigation;
    pendingNavigation = null;
    var fieldHost = document.getElementById("access-field-sidebar-host");
    var chatHost = document.getElementById("access-ai-chat-host");
    var launcher = document.querySelector("[data-access-ai-launcher]");
    var hasField = Boolean(fieldHost && fieldHost.querySelector("[data-access-panel='field']"));
    fieldHost?.classList.toggle("is-empty", !hasField);
    if (chatHost) {
      if (!hasField) {
        fieldHost?.classList.remove("is-collapsed");
        chatHost.classList.remove("is-collapsed");
        chatHost.classList.add("is-expanded");
        chatHost.setAttribute("aria-hidden", "false");
        launcher?.setAttribute("aria-expanded", "false");
      } else if (!chatHost.classList.contains("is-expanded")) {
        fieldHost?.classList.remove("is-collapsed");
        chatHost.classList.add("is-collapsed");
        chatHost.classList.remove("is-expanded");
        chatHost.setAttribute("aria-hidden", "true");
        launcher?.setAttribute("aria-expanded", "false");
      }
      launcher?.toggleAttribute("hidden", !hasField || chatHost.classList.contains("is-expanded"));
    }
    document.querySelectorAll(".access-context-form").forEach(markDirty);
    document.querySelectorAll("[data-access-bundle-form]").forEach(function (bundle) {
      var active = bundle.querySelector("input[name='active_editor']");
      setActiveEditor(bundle, active && active.value ? active.value : "roles");
    });
    document.querySelectorAll(".role-capability-editor").forEach(function (editor) {
      window.SharedRoleCapabilityEditor?.init(editor);
    });
    revealFieldSidebar();
    window.SharedSidebarResize?.init({
      handle: document.querySelector("[data-access-sidebar-resize]"),
      sidebar: document.getElementById("sidebar"),
      layoutClass: "access-sidebar-layout",
      occupiedVar: "--access-sidebar-occupied-width",
    });
    markBackground();
    if (navigation && navigation.isClose) {
      restoreFocus();
    } else if (navigation && navigation.isForm) {
      var form = document.querySelector(".access-context-form");
      if (navigation.submitterValue === "apply") {
        var status = document.querySelector(".access-field-sidebar-host .flash[role='status'][tabindex='-1'], .access-inspector-host .flash[role='status'][tabindex='-1']");
        if (status) { status.focus(); return; }
      }
      var submitter = form && Array.from(form.querySelectorAll("button, input[type='submit']")).find(function (candidate) {
        return candidate.name === navigation.submitterName && candidate.value === navigation.submitterValue;
      });
      var target = submitter || (form && focusables(form)[0]);
      if (target) target.focus();
    } else if (navigation && !navigation.isForm) {
      activePanel = findActivePanel();
      var initial = activePanel && focusables(activePanel)[0];
      if (initial) initial.focus();
    }
  }

  document.addEventListener("click", function (event) {
    var editorLink = event.target.closest("[data-editor-target]");
    if (editorLink) {
      event.preventDefault();
      var target = editorLink.getAttribute("data-editor-target");
      var bundle = editorLink.closest("[data-access-bundle-form]") || document.querySelector("[data-access-bundle-form]");
      if (bundle && target) setActiveEditor(bundle, target);
      return;
    }
    var editorTab = event.target.closest("[data-editor-tab]");
    if (editorTab) {
      event.preventDefault();
      var tabBundle = editorTab.closest("[data-access-bundle-form]");
      if (tabBundle) setActiveEditor(tabBundle, editorTab.getAttribute("data-editor-tab"));
      return;
    }
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

  function setActiveEditor(bundle, target) {
    var allowed = ["department", "ad", "roles", "memory-groups"];
    if (!bundle || allowed.indexOf(target) === -1) return;
    var active = bundle.querySelector("input[name='active_editor']");
    if (active) active.value = target;
    bundle.querySelectorAll("[data-editor-group]").forEach(function (group) {
      var selected = group.getAttribute("data-editor-group") === target;
      group.hidden = !selected;
      group.setAttribute("aria-hidden", String(!selected));
    });
    bundle.querySelectorAll("[data-editor-tab]").forEach(function (tab) {
      var selected = tab.getAttribute("data-editor-tab") === target;
      tab.setAttribute("aria-selected", String(selected));
      tab.tabIndex = selected ? 0 : -1;
    });
  }

  document.addEventListener("click", function (event) {
    var launcher = event.target.closest("[data-access-ai-launcher]");
    var collapse = event.target.closest("[data-access-ai-collapse]");
    if (!launcher && !collapse) return;
    var fieldHost = document.getElementById("access-field-sidebar-host");
    var chatHost = document.getElementById("access-ai-chat-host");
    if (!fieldHost || !chatHost || !fieldHost.querySelector("[data-access-panel='field']")) return;
    var expanded = Boolean(launcher);
    fieldHost.classList.toggle("is-collapsed", expanded);
    chatHost.classList.toggle("is-expanded", expanded);
    chatHost.classList.toggle("is-collapsed", !expanded);
    chatHost.setAttribute("aria-hidden", String(!expanded));
    launcher = document.querySelector("[data-access-ai-launcher]");
    launcher?.toggleAttribute("hidden", expanded);
    launcher?.setAttribute("aria-expanded", String(expanded));
    if (expanded) chatHost.querySelector("textarea, input, button")?.focus();
    else fieldHost.querySelector("input, select, textarea, button")?.focus();
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
  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var detail = event.detail || {};
    var element = detail.elt;
    var isForm = Boolean(element && element.matches(".access-context-form"));
    var isClose = Boolean(element && element.closest(".access-panel-close, .access-inspector-overlay"));
    var triggeringEvent = detail.triggeringEvent;
    var submitter = triggeringEvent && triggeringEvent.submitter;
    if (!submitter && isForm && document.activeElement && element.contains(document.activeElement) && document.activeElement.matches("button, input[type='submit']")) {
      submitter = document.activeElement;
    }
    var wasDirty = Boolean(isForm && (element.dataset.accessDirty === "true" || element.dataset.accessSubmittedDirty === "true"));
    if (element && !isForm && !canLeave()) {
      event.preventDefault();
      return;
    }
    pendingNavigation = {
      isForm: isForm,
      isClose: isClose,
      form: isForm ? element : null,
      wasDirty: wasDirty,
      submitterName: submitter ? submitter.name || "" : element && element.dataset.accessSubmitterName || "",
      submitterValue: submitter ? submitter.value || "" : element && element.dataset.accessSubmitterValue || "",
    };
    var target = detail.target;
    if (target && target.id === "access-field-sidebar-host" && !isForm) {
      var chatHost = document.getElementById("access-ai-chat-host");
      var launcher = document.querySelector("[data-access-ai-launcher]");
      chatHost?.classList.remove("is-expanded");
      chatHost?.classList.add("is-collapsed");
      chatHost?.setAttribute("aria-hidden", "true");
      launcher?.setAttribute("aria-expanded", "false");
    }
    if (target) target.setAttribute("aria-busy", "true");
  });
  document.body.addEventListener("htmx:afterSwap", function (event) {
    var target = event.detail && event.detail.target;
    if (target) target.removeAttribute("aria-busy");
    refreshPanels();
  });
  function restoreFailedEditor() {
    var navigation = pendingNavigation;
    if (!navigation || !navigation.isForm || !navigation.wasDirty) return;
    var form = navigation.form && navigation.form.isConnected ? navigation.form : document.querySelector(".access-context-form");
    if (form) form.dataset.accessDirty = "true";
  }
  document.body.addEventListener("htmx:beforeSwap", function (event) {
    var xhr = event.detail && event.detail.xhr;
    if (xhr && xhr.status >= 400) {
      event.detail.shouldSwap = false;
      event.detail.isError = true;
      restoreFailedEditor();
    }
  });
  function clearHtmxBusy(event) {
    var target = event.detail && event.detail.target;
    if (target) target.removeAttribute("aria-busy");
    if (["htmx:responseError", "htmx:sendError", "htmx:timeout"].indexOf(event.type) !== -1) {
      restoreFailedEditor();
      pendingNavigation = null;
    }
  }
  document.body.addEventListener("htmx:afterRequest", clearHtmxBusy);
  document.body.addEventListener("htmx:responseError", clearHtmxBusy);
  document.body.addEventListener("htmx:sendError", clearHtmxBusy);
  document.body.addEventListener("htmx:timeout", clearHtmxBusy);
  document.body.addEventListener("htmx:afterSettle", refreshPanels);
  document.body.addEventListener("htmx:historyRestore", refreshPanels);
  window.addEventListener("beforeunload", function (event) {
    if (!dirtyForms().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
  compact.addEventListener?.("change", markBackground);
  revealFieldSidebar();
  markBackground();
  refreshPanels();
  if (!restoreFocus()) {
    window.requestAnimationFrame(restoreFocus);
    document.addEventListener("DOMContentLoaded", restoreFocus, { once: true });
  }
  if (isModalPanel(activePanel)) {
    var initial = focusables(activePanel)[0];
    if (initial) initial.focus();
  }
})();
