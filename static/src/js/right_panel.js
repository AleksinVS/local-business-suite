(function () {
  "use strict";

  var allowedTarget = "#global-right-panel-content";
  var localTargetAliases = ["#detail-panel-content", "#entry-detail-panel-content"];
  var moduleCloseCalls = ["closeKanbanDrawer()", "closeWaitingListDrawer()"];

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
    if (command.type && command.type !== "open_right_panel") return null;
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
    }
  }

  function close() {
    var panelNode = panel();
    var overlayNode = overlay();
    if (overlayNode) overlayNode.classList.remove("active");
    if (panelNode) {
      panelNode.classList.remove("active");
      panelNode.setAttribute("aria-hidden", "true");
    }
    refreshContext();
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
    if (window.htmx && typeof window.htmx.process === "function") {
      window.htmx.process(root);
    }
    refreshContext();
  }

  function open(command) {
    var safe = safeCommand(command);
    var target = contentTarget();
    if (!safe || !target) return Promise.reject(new Error("Некорректная команда правой панели."));
    showLoading(safe.title);
    openShell(safe.drawer_size);
    return fetch(safe.htmx_url, {
      method: "GET",
      credentials: "same-origin",
      headers: {
        "HX-Request": "true",
        "X-Requested-With": "XMLHttpRequest",
      },
    }).then(function (response) {
      if (!response.ok) throw new Error("Не удалось загрузить правую панель.");
      return response.text();
    }).then(function (html) {
      target.innerHTML = html;
      processDynamicContent(target);
      return true;
    }).catch(function () {
      target.innerHTML = '<div class="drawer-content"><div class="flash error">Не удалось открыть правую панель.</div></div>';
      refreshContext();
      return false;
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
    if (event.key === "Escape" && panel() && panel().classList.contains("active")) {
      close();
    }
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail && event.detail.target === contentTarget()) {
      processDynamicContent(event.detail.target);
    }
  });
})();
