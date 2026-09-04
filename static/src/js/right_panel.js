(function () {
  "use strict";

  var allowedTarget = "#global-right-panel-content";
  var formCommandType = "open_right_panel_form";
  var successEventName = "rightPanelFormSucceeded";
  var localTargetAliases = ["#detail-panel-content", "#entry-detail-panel-content", "#access-inspector-host", "#access-field-sidebar-host"];
  var moduleCloseCalls = ["closeKanbanDrawer()", "closeWaitingListDrawer()"];
  var formSelector = "form[data-right-panel-form], .access-context-form, .role-definition-form";
  var opener = null;
  var activeLoadController = null;
  var loadGeneration = 0;

  function panel() {
    return document.getElementById("global-right-panel");
  }

  function overlay() {
    return document.getElementById("globalRightPanelOverlay");
  }

  function contentTarget() {
    return document.getElementById("global-right-panel-content");
  }

  function safeLocalPath(value) {
    var raw = String(value || "").trim();
    var candidate = raw;
    function isUnsafe(candidateValue) {
      if (!candidateValue.startsWith("/")
        || candidateValue.startsWith("//")
        || candidateValue.includes("\\")
        || [...candidateValue].some(function (character) {
          var code = character.charCodeAt(0);
          return code < 32 || code === 127;
        })) return true;
      try {
        var candidateUrl = new URL(candidateValue, window.location.origin);
        return candidateUrl.origin !== window.location.origin
          || Boolean(candidateUrl.username)
          || Boolean(candidateUrl.password)
          || Boolean(candidateUrl.hash);
      } catch (_error) {
        return true;
      }
    }
    for (var index = 0; index < 4; index += 1) {
      if (isUnsafe(candidate)) return null;
      try {
        var decoded = decodeURIComponent(candidate);
        if (decoded === candidate) break;
        candidate = decoded;
      } catch (_error) {
        return null;
      }
    }
    if (isUnsafe(candidate)) return null;
    try {
      var parsed = new URL(raw, window.location.origin);
      if (parsed.origin !== window.location.origin || parsed.username || parsed.password || parsed.hash) return null;
      return parsed.pathname + parsed.search;
    } catch (_error) {
      return null;
    }
  }

  function safeCommand(command) {
    if (!command || typeof command !== "object") return null;
    var type = String(command.type || "open_right_panel").trim();
    if (["open_right_panel", formCommandType, "access.open_editor"].indexOf(type) === -1) return null;
    var mode = String(command.mode || (type === formCommandType ? "" : "view")).trim();
    if (type === formCommandType && ["create", "edit"].indexOf(mode) === -1) return null;
    var url = safeLocalPath(command.htmx_url);
    if (!url) return null;
    var target = String(command.target || allowedTarget).trim();
    if (target !== allowedTarget) return null;
    var drawerSize = String(command.drawer_size || "default").trim();
    if (["default", "large", "waiting_list", "workspace"].indexOf(drawerSize) === -1) drawerSize = "default";
    var swap = String(command.swap || "innerHTML").trim();
    if (swap !== "innerHTML") return null;
    return {
      htmx_url: url,
      target: target,
      swap: swap,
      drawer_size: drawerSize,
      title: String(command.title || "Загрузка...").slice(0, 200),
      type: type,
      mode: mode,
    };
  }

  function setDrawerSize(size) {
    var node = panel();
    if (!node) return;
    node.classList.remove("drawer-large", "drawer-waiting-list", "drawer-workspace");
    if (size === "large") node.classList.add("drawer-large");
    if (size === "waiting_list") node.classList.add("drawer-waiting-list");
    if (size === "workspace") node.classList.add("drawer-workspace");
  }

  function showLoading(title) {
    var target = contentTarget();
    if (!target) return;
    target.innerHTML = '<div class="drawer-content"><div class="text-muted" role="status">'
      + escapeHtml(title || "Загрузка...")
      + "</div></div>";
  }

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(String(value || "")));
    return div.innerHTML;
  }

  function openShell(size, mode) {
    setDrawerSize(size);
    var panelNode = panel();
    var overlayNode = overlay();
    if (overlayNode) overlayNode.classList.add("active");
    if (panelNode) {
      panelNode.classList.add("active");
      panelNode.setAttribute("aria-hidden", "false");
      panelNode.setAttribute("role", "dialog");
      panelNode.setAttribute("aria-modal", "true");
      panelNode.dataset.rightPanelMode = mode || "view";
    }
    document.querySelector(".app-layout")?.setAttribute("inert", "");
  }

  function dirtyForms(root) {
    if (!root) return [];
    return [...root.querySelectorAll(formSelector)].filter(function (form) {
      return form.dataset.rightPanelDirty === "true" || form.dataset.accessDirty === "true";
    });
  }

  function confirmDiscard(root) {
    if (!dirtyForms(root).length) return true;
    if (window.SharedAccessEditor && typeof window.SharedAccessEditor.confirmDiscard === "function") {
      var accessDirty = root.querySelector(".access-context-form[data-access-dirty='true'], .role-definition-form[data-access-dirty='true']");
      if (accessDirty) return window.SharedAccessEditor.confirmDiscard(root);
    }
    return window.confirm("Закрыть панель и потерять несохранённые изменения?");
  }

  function cancelActiveLoad() {
    loadGeneration += 1;
    if (activeLoadController) activeLoadController.abort();
    activeLoadController = null;
  }

  function isCurrentLoad(generation, controller) {
    return generation === loadGeneration && (!controller || controller === activeLoadController);
  }

  function close(options) {
    var opts = options && typeof options === "object" ? options : {};
    var target = contentTarget();
    if (!opts.force && target && !confirmDiscard(target)) return false;
    cancelActiveLoad();
    target?.removeAttribute("aria-busy");
    var panelNode = panel();
    var overlayNode = overlay();
    if (overlayNode) overlayNode.classList.remove("active");
    if (panelNode) {
      panelNode.classList.remove("active");
      panelNode.setAttribute("aria-hidden", "true");
      panelNode.removeAttribute("role");
      panelNode.removeAttribute("aria-modal");
      delete panelNode.dataset.rightPanelMode;
    }
    document.querySelector(".app-layout")?.removeAttribute("inert");
    refreshContext();
    if (opener?.isConnected) opener.focus();
    opener = null;
    return true;
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

  function configurePanelForms(root) {
    root?.querySelectorAll(formSelector).forEach(function (form) {
      if (!form.matches("[data-right-panel-form]")) return;
      if (!form.hasAttribute("hx-sync")) form.setAttribute("hx-sync", "this:drop");
      if (!form.hasAttribute("hx-request")) form.setAttribute("hx-request", '{"timeout":15000}');
      if (!form.hasAttribute("hx-disabled-elt")) form.setAttribute("hx-disabled-elt", "find button[type='submit']");
      if (!form.dataset.rightPanelDirty) {
        var hasValidationErrors = Boolean(form.querySelector(".errorlist, .form-error, [aria-invalid='true']"));
        form.dataset.rightPanelDirty = hasValidationErrors ? "true" : "false";
      }
      if (form.dataset.rightPanelBound === "true") return;
      form.dataset.rightPanelBound = "true";
      ["input", "change"].forEach(function (eventName) {
        form.addEventListener(eventName, function (event) {
          if (event.target && event.target.matches("button, [type='submit']")) return;
          form.dataset.rightPanelDirty = "true";
        });
      });
    });
  }

  function focusPanel(root) {
    if (!root?.matches(allowedTarget)) return;
    var first = root.querySelector("[autofocus], [data-right-panel-initial-focus], a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled])");
    if (first) {
      first.focus();
      return;
    }
    var panelNode = panel();
    if (panelNode) {
      panelNode.setAttribute("tabindex", "-1");
      panelNode.focus();
    }
  }

  function processDynamicContent(root) {
    rewriteModulePanelControls(root);
    root?.querySelectorAll("[hx-get], [hx-post], [hx-put], [hx-delete]").forEach(function (node) {
      if (!node.hasAttribute("hx-request")) node.setAttribute("hx-request", '{"timeout":15000}');
    });
    configurePanelForms(root);
    if (window.htmx && typeof window.htmx.process === "function") window.htmx.process(root);
    window.SharedAccessEditor?.init(root);
    if (window.LocalBusinessWaitingListCards && typeof window.LocalBusinessWaitingListCards.init === "function") {
      window.LocalBusinessWaitingListCards.init(root);
    }
    refreshContext();
    focusPanel(root);
  }

  function open(command) {
    var safe = safeCommand(command);
    var target = contentTarget();
    if (!safe || !target) return Promise.reject(new Error("Некорректная команда правой панели."));
    var previousHtml = target.innerHTML;
    var hadDirtyDraft = dirtyForms(target).length > 0;
    if (hadDirtyDraft && !confirmDiscard(target)) return Promise.resolve(false);
    cancelActiveLoad();
    var generation = loadGeneration;
    var panelNode = panel();
    if (!panelNode?.classList.contains("active")) opener = document.activeElement;
    showLoading(safe.title);
    openShell(safe.drawer_size, safe.mode);
    target.setAttribute("aria-busy", "true");
    var controller = typeof AbortController === "function" ? new AbortController() : null;
    activeLoadController = controller;
    var timedOut = false;
    var timeout = window.setTimeout(function () {
      timedOut = true;
      controller?.abort();
    }, 15000);
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
      if (!isCurrentLoad(generation, controller)) throw new DOMException("Устаревшая загрузка.", "AbortError");
      if (!response.ok) throw new Error("Не удалось загрузить правую панель.");
      return response.text();
    }).then(function (html) {
      if (!isCurrentLoad(generation, controller)) throw new DOMException("Устаревшая загрузка.", "AbortError");
      target.innerHTML = html;
      processDynamicContent(target);
      return true;
    }).catch(function (error) {
      if (!isCurrentLoad(generation, controller) || (error?.name === "AbortError" && !timedOut)) return false;
      if (hadDirtyDraft) {
        target.innerHTML = previousHtml;
        processDynamicContent(target);
        showClientError(target, "Не удалось открыть редактор. Черновик сохранён; повторите попытку.");
      } else {
        target.innerHTML = '<div class="drawer-content"><div class="flash error" role="alert">Не удалось открыть правую панель. Повторите попытку.</div></div>';
      }
      refreshContext();
      return false;
    }).finally(function () {
      window.clearTimeout(timeout);
      if (isCurrentLoad(generation, controller)) {
        activeLoadController = null;
        target.removeAttribute("aria-busy");
      }
    });
  }

  function openForm(command) {
    if (!command || typeof command !== "object") return Promise.reject(new Error("Некорректная команда формы."));
    return open(Object.assign({}, command, {type: formCommandType}));
  }

  function formFromEvent(event) {
    var element = event.detail?.elt;
    if (!element) return null;
    var form = element.matches?.(formSelector) ? element : element.closest?.(formSelector);
    return form?.matches("[data-right-panel-form]") ? form : null;
  }

  function setSubmitting(form, submitting) {
    if (!form) return;
    form.dataset.rightPanelSubmitting = submitting ? "true" : "false";
    form.toggleAttribute("aria-busy", submitting);
    form.querySelectorAll("button[type='submit'], input[type='submit']").forEach(function (control) {
      if (submitting) {
        if (!control.disabled) control.dataset.rightPanelDisabledByRequest = "true";
        control.disabled = true;
      } else if (control.dataset.rightPanelDisabledByRequest === "true") {
        control.disabled = false;
        delete control.dataset.rightPanelDisabledByRequest;
      }
    });
  }

  function showClientError(root, message) {
    var accessHost = root.matches?.(".access-context-form, .role-definition-form")
      ? root
      : root.querySelector?.(".access-context-form, .role-definition-form");
    var host = root.querySelector?.("[data-right-panel-errors]") || accessHost || root.querySelector?.(formSelector) || root;
    var errorClass = accessHost ? "access-client-error" : "right-panel-client-error";
    var error = host.querySelector?.("." + errorClass);
    if (!error) {
      error = document.createElement("p");
      error.className = "form-error " + errorClass;
      error.setAttribute("role", "alert");
      host.appendChild(error);
    }
    error.textContent = message;
  }

  function isValidationResponse(event) {
    return Number(event.detail?.xhr?.status || 0) === 422;
  }

  window.LocalBusinessRightPanel = {
    open: open,
    openForm: openForm,
    close: close,
    successEvent: successEventName,
  };
  window.openGlobalRightPanel = open;
  window.openGlobalRightPanelForm = openForm;
  window.closeGlobalRightPanel = close;
  if (!window.closeKanbanDrawer) window.closeKanbanDrawer = close;
  if (!window.closeWaitingListDrawer) window.closeWaitingListDrawer = close;

  document.addEventListener("keydown", function (event) {
    var panelNode = panel();
    if (!panelNode || !panelNode.classList.contains("active")) return;
    if (event.key === "Tab") {
      var items = [...panelNode.querySelectorAll("a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex='-1'])")]
        .filter(function (item) { return item.getClientRects().length > 0; });
      if (!items.length) {
        event.preventDefault();
        panelNode.focus();
        return;
      }
      var first = items[0];
      var last = items[items.length - 1];
      if (!panelNode.contains(document.activeElement) || items.indexOf(document.activeElement) === -1) {
        event.preventDefault();
        (event.shiftKey ? last : first).focus();
        return;
      }
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      return;
    }
    if (event.key === "Escape") close();
  });

  document.addEventListener("htmx:beforeSwap", function (event) {
    if (event.detail?.target !== contentTarget() || !isValidationResponse(event)) return;
    event.detail.shouldSwap = true;
    event.detail.isError = false;
  });

  document.addEventListener("htmx:afterSwap", function (event) {
    if (event.detail?.target !== contentTarget()) return;
    processDynamicContent(event.detail.target);
    if (isValidationResponse(event)) {
      event.detail.target.querySelectorAll("form[data-right-panel-form]").forEach(function (form) {
        form.dataset.rightPanelDirty = "true";
      });
    }
  });

  document.body.addEventListener("htmx:beforeRequest", function (event) {
    var form = formFromEvent(event);
    if (!form) return;
    if (form.dataset.rightPanelSubmitting === "true") {
      event.preventDefault();
      return;
    }
    setSubmitting(form, true);
  });

  function clearFailedRequest(event) {
    var detail = event.detail || {};
    var element = detail.elt;
    var targetNode = detail.target || element?.closest(allowedTarget);
    if (!element || !targetNode || targetNode !== contentTarget()) return;
    var form = formFromEvent(event);
    setSubmitting(form, false);
    element.classList.remove("htmx-request");
    element.removeAttribute("aria-busy");
    element.querySelectorAll("[data-access-disabled-by-request='true']").forEach(function (control) {
      control.disabled = false;
      delete control.dataset.accessDisabledByRequest;
    });
    targetNode.removeAttribute("aria-busy");
    var transportFailure = ["htmx:timeout", "htmx:sendError", "htmx:swapError"].indexOf(event.type) !== -1;
    var responseFailure = event.type === "htmx:responseError" && !isValidationResponse(event);
    if (!transportFailure && !responseFailure) return;
    if (form) form.dataset.rightPanelDirty = "true";
    if (element.dataset) element.dataset.accessDirty = "true";
    showClientError(form || element, "Не удалось сохранить изменения. Черновик сохранён; повторите попытку.");
  }

  ["htmx:afterRequest", "htmx:timeout", "htmx:sendError", "htmx:responseError", "htmx:swapError"].forEach(function (name) {
    document.body.addEventListener(name, clearFailedRequest);
  });

  document.body.addEventListener(successEventName, function (event) {
    var panelNode = panel();
    if (!panelNode?.classList.contains("active")) return;
    dirtyForms(contentTarget()).forEach(function (form) {
      form.dataset.rightPanelDirty = "false";
      form.dataset.accessDirty = "false";
    });
    close({force: true});
    document.body.dispatchEvent(new CustomEvent("rightPanelFormSaved", {detail: event.detail || {}}));
  });
})();
