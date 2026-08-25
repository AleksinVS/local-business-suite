(function () {
  "use strict";

  var allowedTarget = "#global-right-panel-content";
  var localTargetAliases = ["#detail-panel-content", "#entry-detail-panel-content", "#access-inspector-host", "#access-field-sidebar-host"];
  var moduleCloseCalls = ["closeKanbanDrawer()", "closeWaitingListDrawer()"];
  var opener = null;

  function panel() {
    return document.getElementById("global-right-panel");
  }

  function overlay() {
    return document.getElementById("globalRightPanelOverlay");
  }

  function contentTarget() {
    return document.getElementById("global-right-panel-content");
  }

  function safeCommand(command) {
    if (!command || typeof command !== "object") return null;
    if (command.type && command.type !== "open_right_panel" && command.type !== "access.open_editor") return null;
    var url = String(command.htmx_url || "").trim();
    if (!url || !url.startsWith("/") || url.startsWith("//")) return null;
    var target = String(command.target || allowedTarget).trim();
    if (target !== allowedTarget) return null;
    var drawerSize = String(command.drawer_size || "default").trim();
    if (["default", "large", "waiting_list"].indexOf(drawerSize) === -1) drawerSize = "default";
    return {
      htmx_url: url,
      target: target,
      swap: String(command.swap || "innerHTML"),
      drawer_size: drawerSize,
      title: String(command.title || "Загрузка...").slice(0, 200),
    };
  }

  function setDrawerSize(size) {
    var node = panel();
    if (!node) return;
    node.classList.remove("drawer-large", "drawer-waiting-list");
    if (size === "large") node.classList.add("drawer-large");
    if (size === "waiting_list") node.classList.add("drawer-waiting-list");
  }

  function showLoading(title) {
    var target = contentTarget();
    if (!target) return;
    target.innerHTML = '<div class="drawer-content"><div class="text-muted">'
      + escapeHtml(title || "Загрузка...")
      + "</div></div>";
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(String(value || "")));
    return div.innerHTML;
  }

  function openShell(size) {
    setDrawerSize(size);
    var panelNode = panel();
    var overlayNode = overlay();
    if (overlayNode) overlayNode.classList.add("active");
    if (panelNode) {
      panelNode.classList.add("active");
      panelNode.setAttribute("aria-hidden", "false");
      panelNode.setAttribute("role", "dialog");
      panelNode.setAttribute("aria-modal", "true");
    }
    document.querySelector(".app-layout")?.setAttribute("inert", "");
  }

  function close() {
    var target = contentTarget();
    if (target && window.SharedAccessEditor && !window.SharedAccessEditor.confirmDiscard(target)) return;
    var panelNode = panel();
    var overlayNode = overlay();
    if (overlayNode) overlayNode.classList.remove("active");
    if (panelNode) {
      panelNode.classList.remove("active");
      panelNode.setAttribute("aria-hidden", "true");
      panelNode.removeAttribute("role");
      panelNode.removeAttribute("aria-modal");
    }
    document.querySelector(".app-layout")?.removeAttribute("inert");
    refreshContext();
    if (opener?.isConnected) opener.focus();
    opener = null;
  }

  function rewriteModulePanelControls(root) {
    if (!root) return;
    root.querySelectorAll("[hx-target]").forEach(function (node) {
      var target = node.getAttribute("hx-target");
      if (localTargetAliases.indexOf(target) === -1) return;
      node.setAttribute("hx-target", allowedTarget);
    });
    root.querySelectorAll("[onclick]").forEach(function (node) {
      var onclickValue = node.getAttribute("onclick");
      if (moduleCloseCalls.indexOf(onclickValue) === -1) return;
      node.setAttribute("onclick", "closeGlobalRightPanel()");
    });
  }

  function refreshContext() {
    if (window.LocalBusinessPageContext && typeof window.LocalBusinessPageContext.refresh === "function") {
      window.LocalBusinessPageContext.refresh();
    }
  }

  function processDynamicContent(root) {
    rewriteModulePanelControls(root);
    root?.querySelectorAll("[hx-get], [hx-post], [hx-put], [hx-delete]").forEach(function (node) {
      if (!node.hasAttribute("hx-request")) node.setAttribute("hx-request", '{"timeout":15000}');
    });
    if (window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(root);
    }
    window.SharedAccessEditor?.init(root);
    if (window.LocalBusinessWaitingListCards && typeof window.LocalBusinessWaitingListCards.init === "function") {
      window.LocalBusinessWaitingListCards.init(root);
    }
    refreshContext();
    if (root?.matches("#global-right-panel-content")) {
      var first = root.querySelector("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])");
      first?.focus();
    }
  }

  function open(command) {
    var safe = safeCommand(command);
    var target = contentTarget();
    if (!safe || !target) return Promise.reject(new Error("Некорректная команда правой панели."));
    var previousHtml = target.innerHTML;
    var dirtyDraft = Boolean(target.querySelector(".access-context-form[data-access-dirty='true'], .role-definition-form[data-access-dirty='true']"));
    if (dirtyDraft && window.SharedAccessEditor && !window.SharedAccessEditor.confirmDiscard(target)) return Promise.resolve(false);
    opener = document.activeElement;
    showLoading(safe.title);
    openShell(safe.drawer_size);
    target.setAttribute("aria-busy", "true");
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    var timeout = window.setTimeout(function () { controller?.abort(); }, 15000);
    return fetch(safe.htmx_url, {
      method: "GET",
      credentials: "same-origin",
      headers: {
        "HX-Request": "true",
        "HX-Target": allowedTarget,
        "X-Requested-With": "XMLHttpRequest",
      },
      signal: controller?.signal,
    }).then(function (response) {
      if (!response.ok) throw new Error("Не удалось загрузить правую панель.");
      return response.text();
    }).then(function (html) {
      target.innerHTML = html;
      processDynamicContent(target);
      return true;
    }).catch(function () {
      if (dirtyDraft) {
        target.innerHTML = previousHtml;
        var form = target.querySelector(".access-context-form[data-access-dirty='true']");
        if (form) {
          var error = document.createElement("p");
          error.className = "form-error access-client-error";
          error.setAttribute("role", "alert");
          error.textContent = "Не удалось открыть редактор. Черновик сохранён; повторите попытку.";
          form.appendChild(error);
          form.dataset.accessDirty = "true";
        }
      } else {
        target.innerHTML = '<div class="drawer-content"><div class="flash error" role="alert">Не удалось открыть правую панель. Повторите попытку.</div></div>';
      }
      refreshContext();
      return false;
    }).finally(function () {
      window.clearTimeout(timeout);
      target.removeAttribute("aria-busy");
    });
  }

  window.LocalBusinessRightPanel = {
    open: open,
    close: close,
  };
  window.openGlobalRightPanel = open;
  window.closeGlobalRightPanel = close;
  if (!window.closeKanbanDrawer) window.closeKanbanDrawer = close;
  if (!window.closeWaitingListDrawer) window.closeWaitingListDrawer = close;

  document.addEventListener("keydown", function (event) {
    var panelNode = panel();
    if (!panelNode || !panelNode.classList.contains("active")) return;
    if (event.key === "Tab") {
      var items = [...panelNode.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")];
      if (!items.length) return;
      var first = items[0];
      var last = items[items.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.key === "Escape") {
      close();
    }
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target === contentTarget()) {
      processDynamicContent(event.detail.target);
    }
  });

  function clearFailedRequest(event) {
    var detail = event.detail || {};
    var element = detail.elt;
    var targetNode = detail.target || element?.closest("#global-right-panel-content");
    if (!element || !targetNode || targetNode !== contentTarget()) return;
    element.classList.remove("htmx-request");
    element.removeAttribute("aria-busy");
    element.querySelectorAll("[data-access-disabled-by-request='true']").forEach(function (control) {
      control.disabled = false;
      delete control.dataset.accessDisabledByRequest;
    });
    targetNode.removeAttribute("aria-busy");
    if (["htmx:timeout", "htmx:sendError", "htmx:responseError", "htmx:swapError"].indexOf(event.type) === -1) return;
    element.dataset.accessDirty = "true";
    var error = element.querySelector(".access-client-error");
    if (!error) {
      error = document.createElement("p");
      error.className = "form-error access-client-error";
      error.setAttribute("role", "alert");
      element.appendChild(error);
    }
    error.textContent = "Не удалось сохранить изменения. Черновик сохранён; повторите попытку.";
  }
  ["htmx:afterRequest", "htmx:timeout", "htmx:sendError", "htmx:responseError", "htmx:swapError"].forEach(function (name) {
    document.body.addEventListener(name, clearFailedRequest);
  });
})();
