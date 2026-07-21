(function () {
  "use strict";

  var config = window.__pageContextConfig || {};
  var state = {
    windowId: "",
    contextVersion: 0,
    contextHash: "",
    contextHint: "",
    envelope: null,
    lastLocalHash: "",
    timer: null,
  };

  function randomId() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID();
    }
    return "window-" + Date.now() + "-" + Math.random().toString(16).slice(2);
  }

  function getWindowId() {
    if (!state.windowId) {
      state.windowId = sessionStorage.getItem("ai_window_id") || randomId();
      sessionStorage.setItem("ai_window_id", state.windowId);
    }
    return state.windowId;
  }

  function safeString(value, maxLength) {
    return String(value || "").replace(/[\u0000-\u001f]/g, "").trim().slice(0, maxLength);
  }

  function parseContext(node) {
    if (!node) return {};
    var raw = node.getAttribute("data-ai-context");
    if (!raw) return {};
    try {
      var parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (error) {
      return {};
    }
  }

  function mergeContext(base, next) {
    var merged = {
      schema_version: "1",
      page: Object.assign({}, base.page || {}, next.page || {}),
      selection: Object.assign({}, base.selection || {}, next.selection || {}),
      filters: Object.assign({}, base.filters || {}, next.filters || {}),
      ui_state: Object.assign({}, base.ui_state || {}, next.ui_state || {}),
      capabilities: {},
    };
    if (next.selection === null || next.selection === false) merged.selection = {};
    return merged;
  }

  function collectContext() {
    var envelope = {
      schema_version: "1",
      window_id: getWindowId(),
      page: {
        path: safeString(window.location.pathname, 200),
        title: safeString(document.title, 200),
        module: "",
        view: "",
      },
      selection: {},
      filters: {},
      ui_state: {},
      capabilities: {},
    };
    document.querySelectorAll("[data-ai-context]").forEach(function (node) {
      var drawer = node.closest(".drawer");
      if (drawer && !drawer.classList.contains("active")) return;
      envelope = mergeContext(envelope, parseContext(node));
    });
    var filtersForm = document.querySelector("form.filters");
    if (filtersForm) {
      var formData = new FormData(filtersForm);
      formData.forEach(function (value, key) {
        envelope.filters[key] = value;
      });
    }
    envelope.window_id = getWindowId();
    return sanitizeEnvelope(envelope);
  }

  function sanitizeEnvelope(envelope) {
    var page = envelope.page || {};
    var selection = envelope.selection || {};
    return {
      schema_version: "1",
      window_id: getWindowId(),
      page: {
        path: safeString(page.path || window.location.pathname, 200),
        title: safeString(page.title || document.title, 200),
        module: safeString(page.module, 64),
        view: safeString(page.view, 64),
      },
      selection: selection && selection.object_id ? {
        object_type: safeString(selection.object_type, 80),
        object_id: safeString(selection.object_id, 80),
        source_code: safeString(selection.source_code, 80),
        display: safeString(selection.display, 160),
      } : {},
      filters: sanitizeFlatMap(envelope.filters || {}, 120),
      ui_state: sanitizeFlatMap(envelope.ui_state || {}, 80),
      capabilities: {},
    };
  }

  function sanitizeFlatMap(value, maxLength) {
    var clean = {};
    if (!value || typeof value !== "object") return clean;
    Object.keys(value).forEach(function (key) {
      var item = value[key];
      if (["string", "number", "boolean"].indexOf(typeof item) === -1) return;
      clean[safeString(key, 80)] = typeof item === "boolean" ? item : safeString(item, maxLength);
    });
    return clean;
  }

  function localHash(envelope) {
    return JSON.stringify(envelope);
  }

  function contextHint(envelope) {
    if (envelope.selection && envelope.selection.object_id) {
      return envelope.selection.source_code + " / " + envelope.selection.object_type + "#" + envelope.selection.object_id;
    }
    return [envelope.page.module, envelope.page.view || envelope.page.title].filter(Boolean).join(" / ");
  }

  function emitUpdate() {
    window.dispatchEvent(new CustomEvent("ai-context:update", {
      detail: getCurrent(),
    }));
  }

  function publishNow() {
    var envelope = collectContext();
    var hash = localHash(envelope);
    state.envelope = envelope;
    state.contextHint = contextHint(envelope);
    emitUpdate();
    if (!config.authenticated || !config.updateUrl || hash === state.lastLocalHash) return;
    state.lastLocalHash = hash;
    fetch(config.updateUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": config.csrfToken || "",
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(envelope),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("Не удалось обновить контекст.");
        return response.json();
      })
      .then(function (payload) {
        if (payload.status !== "ok") return;
        state.contextVersion = payload.context_version || 0;
        state.contextHash = payload.context_hash || "";
        state.contextHint = payload.context_hint || state.contextHint;
        emitUpdate();
      })
      .catch(function () {
        // Контекст необязателен; чат продолжает работать без него.
      });
  }

  function schedulePublish(delay) {
    clearTimeout(state.timer);
    state.timer = setTimeout(publishNow, delay == null ? 350 : delay);
  }

  function getCurrent() {
    return {
      window_id: getWindowId(),
      context_version: state.contextVersion || 0,
      context_hash: state.contextHash || "",
      context_hint: state.contextHint || "",
      envelope: state.envelope || collectContext(),
    };
  }

  window.LocalBusinessPageContext = {
    getCurrent: getCurrent,
    refresh: function () { schedulePublish(0); },
  };

  document.addEventListener("DOMContentLoaded", function () { schedulePublish(0); });
  document.addEventListener("htmx:afterSwap", function () { schedulePublish(100); });
  document.addEventListener("htmx:afterSettle", function () { schedulePublish(150); });
  document.addEventListener("change", function (event) {
    if (event.target.closest("[data-ai-context], form.filters")) schedulePublish(350);
  });
  document.addEventListener("input", function (event) {
    if (event.target.closest("form.filters")) schedulePublish(450);
  });
})();
