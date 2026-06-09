(function () {
  "use strict";

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(String(value || "")));
    return div.innerHTML;
  }

  function csrfToken() {
    var match = document.cookie.match(/(?:^|; )csrftoken=([^;]+)/);
    return match ? decodeURIComponent(match[1]) : "";
  }

  function currentPageContext() {
    if (!window.LocalBusinessPageContext || typeof window.LocalBusinessPageContext.getCurrent !== "function") {
      return {};
    }
    var current = window.LocalBusinessPageContext.getCurrent();
    return current && current.envelope ? current : {};
  }

  function normalizeRightPanelCommand(command) {
    if (!command || command.type !== "open_right_panel") return null;
    var htmxUrl = String(command.htmx_url || command.url || "").trim();
    if (!htmxUrl || !htmxUrl.startsWith("/") || htmxUrl.startsWith("//")) return null;
    return {
      type: "open_right_panel",
      version: String(command.version || "1.0"),
      source_code: String(command.source_code || ""),
      object_type: String(command.object_type || ""),
      object_id: String(command.object_id || ""),
      mode: String(command.mode || "view"),
      title: String(command.title || "Загрузка..."),
      htmx_url: htmxUrl,
      target: "#global-right-panel-content",
      swap: "innerHTML",
      drawer_size: String(command.drawer_size || "default"),
    };
  }

  function NativeAiSidebar(root, config) {
    this.root = root;
    this.config = config;
    this.messages = [];
    this.executedCommands = new Set();
    this.pending = false;
    this.render();
  }

  NativeAiSidebar.prototype.render = function () {
    var labels = this.config.labels || {};
    this.root.innerHTML = [
      '<div class="native-ai-ui">',
      '  <div class="native-ai-ui-header">',
      '    <h2 class="native-ai-ui-title">' + escapeHtml(labels.title || "ИИ-чат") + "</h2>",
      "  </div>",
      '  <div class="native-ai-ui-messages" data-native-ai-messages>',
      '    <div class="sidebar-chat-empty">' + escapeHtml(labels.initial || "Опишите задачу.") + "</div>",
      "  </div>",
      '  <form class="native-ai-ui-form" data-native-ai-form>',
      '    <textarea rows="1" autocomplete="off" placeholder="' + escapeHtml(labels.placeholder || "Сообщение...") + '"></textarea>',
      '    <button type="submit" aria-label="Отправить">↑</button>',
      "  </form>",
      "</div>",
    ].join("");
    this.list = this.root.querySelector("[data-native-ai-messages]");
    this.form = this.root.querySelector("[data-native-ai-form]");
    this.input = this.form.querySelector("textarea");
    this.send = this.form.querySelector("button");
    this.bind();
  };

  NativeAiSidebar.prototype.bind = function () {
    var self = this;
    this.input.addEventListener("input", function () {
      self.resizeInput();
    });
    this.input.addEventListener("keydown", function (event) {
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      self.form.requestSubmit();
    });
    this.form.addEventListener("submit", function (event) {
      event.preventDefault();
      self.submit();
    });
  };

  NativeAiSidebar.prototype.resizeInput = function () {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(this.input.scrollHeight, 180) + "px";
  };

  NativeAiSidebar.prototype.scrollToBottom = function () {
    this.list.scrollTop = this.list.scrollHeight;
  };

  NativeAiSidebar.prototype.appendMessage = function (role, content, pending) {
    var empty = this.list.querySelector(".sidebar-chat-empty");
    if (empty) empty.remove();
    var item = document.createElement("div");
    item.className = "native-ai-ui-message is-" + role;
    if (pending) item.classList.add("is-pending");
    item.innerHTML = [
      '<div class="native-ai-ui-meta">',
      role === "user" ? "Вы" : role === "tool" ? "Инструмент" : "Ассистент",
      "</div>",
      '<div class="native-ai-ui-bubble">',
      escapeHtml(content || ""),
      "</div>",
    ].join("");
    this.list.appendChild(item);
    this.scrollToBottom();
    return item;
  };

  NativeAiSidebar.prototype.setPending = function (value) {
    this.pending = value;
    this.input.disabled = value;
    this.send.disabled = value;
  };

  NativeAiSidebar.prototype.submit = function () {
    if (this.pending) return;
    var prompt = this.input.value.trim();
    if (!prompt) return;
    this.setPending(true);
    this.input.value = "";
    this.resizeInput();
    this.messages.push({ id: "user_" + Date.now(), role: "user", content: prompt });
    this.appendMessage("user", prompt, false);
    var assistantNode = this.appendMessage("assistant", "Печатает...", true);
    this.runAgent(assistantNode);
  };

  NativeAiSidebar.prototype.runAgent = function (assistantNode) {
    var self = this;
    var assistantBuffer = "";
    var payload = {
      threadId: this.config.thread_id,
      runId: "native_" + Date.now().toString(36),
      state: {},
      messages: this.messages.slice(-16),
      tools: [],
      context: [],
      forwardedProps: Object.assign({}, this.config.forwarded_props || {}, {
        page_context: currentPageContext(),
      }),
      resume: [],
    };

    fetch(this.config.runtime_url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(payload),
    }).then(function (response) {
      if (!response.ok || !response.body) throw new Error("stream failed");
      return self.readStream(response.body, assistantNode, function (text) {
        assistantBuffer = text;
      });
    }).then(function () {
      assistantNode.classList.remove("is-pending");
      if (assistantBuffer) {
        self.messages.push({ id: "assistant_" + Date.now(), role: "assistant", content: assistantBuffer });
      }
      self.setPending(false);
      self.input.focus();
    }).catch(function () {
      assistantNode.classList.remove("is-pending");
      assistantNode.querySelector(".native-ai-ui-bubble").textContent = "Не удалось получить ответ от ИИ-сервиса.";
      self.setPending(false);
    });
  };

  NativeAiSidebar.prototype.readStream = function (body, assistantNode, onText) {
    var self = this;
    var reader = body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var text = "";

    function processBlock(block) {
      if (!block.trim()) return;
      var line = block.split("\n").find(function (item) {
        return item.indexOf("data: ") === 0;
      });
      if (!line) return;
      try {
        self.handleEvent(JSON.parse(line.slice(6)), assistantNode, function (delta) {
          text += delta;
          onText(text);
        });
      } catch (error) {}
    }

    function read() {
      return reader.read().then(function (result) {
        if (result.done) {
          if (buffer) processBlock(buffer);
          return true;
        }
        buffer += decoder.decode(result.value, { stream: true });
        var blocks = buffer.split("\n\n");
        buffer = blocks.pop() || "";
        blocks.forEach(processBlock);
        return read();
      });
    }

    return read();
  };

  NativeAiSidebar.prototype.handleEvent = function (event, assistantNode, appendText) {
    if (!event || !event.type) return;
    if (event.type === "TEXT_MESSAGE_CONTENT") {
      appendText(String(event.delta || ""));
      assistantNode.querySelector(".native-ai-ui-bubble").textContent += String(event.delta || "");
      this.scrollToBottom();
      return;
    }
    if (event.type === "TEXT_MESSAGE_START") {
      assistantNode.querySelector(".native-ai-ui-bubble").textContent = "";
      return;
    }
    if (event.type === "TOOL_CALL_START") {
      this.appendMessage("tool", String(event.toolCallName || "tool"), false);
      return;
    }
    if (event.type === "STATE_DELTA") {
      this.applyStateDelta(event.delta);
      return;
    }
    if (event.type === "CUSTOM" && event.name === "local_business.ui_command") {
      this.executeUiCommand(event.value);
      return;
    }
    if (event.type === "RUN_ERROR") {
      assistantNode.querySelector(".native-ai-ui-bubble").textContent = event.message || "ИИ-сервис вернул ошибку.";
    }
  };

  NativeAiSidebar.prototype.applyStateDelta = function (delta) {
    var self = this;
    if (!Array.isArray(delta)) return;
    delta.forEach(function (operation) {
      if (!operation || operation.op !== "replace") return;
      if (operation.path !== "/localBusiness/uiCommands" && operation.path !== "/localBusinessUiCommands") return;
      if (!Array.isArray(operation.value)) return;
      operation.value.forEach(function (command) {
        self.executeUiCommand(command);
      });
    });
  };

  NativeAiSidebar.prototype.executeUiCommand = function (command) {
    var safe = normalizeRightPanelCommand(command);
    if (!safe || !window.LocalBusinessRightPanel || typeof window.LocalBusinessRightPanel.open !== "function") return;
    var key = JSON.stringify(safe);
    if (this.executedCommands.has(key)) return;
    this.executedCommands.add(key);
    window.LocalBusinessRightPanel.open(safe).catch(function () {});
  };

  function boot() {
    var root = document.getElementById("native-ai-sidebar-root");
    if (!root || root.dataset.nativeAiReady === "1") return;
    root.dataset.nativeAiReady = "1";
    var configUrl = root.dataset.configUrl;
    fetch(configUrl, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    }).then(function (response) {
      if (!response.ok) throw new Error("config failed");
      return response.json();
    }).then(function (config) {
      new NativeAiSidebar(root, config);
    }).catch(function () {
      root.innerHTML = '<div class="native-ai-ui-error">ИИ-чат недоступен.</div>';
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
