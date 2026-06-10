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

  function randomSuffix() {
    if (window.crypto && typeof window.crypto.randomUUID === "function") {
      return window.crypto.randomUUID().replace(/-/g, "").slice(0, 12);
    }
    return Math.random().toString(36).slice(2, 14);
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

  function eventDataFromBlock(block) {
    var lines = block.split(/\r?\n/);
    var dataLines = [];
    lines.forEach(function (line) {
      if (line.indexOf("data:") !== 0) return;
      dataLines.push(line.slice(5).replace(/^ /, ""));
    });
    return dataLines.join("\n").trim();
  }

  function NativeAiSidebar(root, config) {
    this.root = root;
    this.config = config;
    this.labels = config.labels || {};
    this.newSessionUrl = root.dataset.newSessionUrl || "";
    this.messages = [];
    this.executedCommands = new Set();
    this.messageNodes = {};
    this.toolNodes = {};
    this.toolBuffers = {};
    this.pending = false;
    this.currentAssistant = null;
    this.activeRunId = "";
    this.runHadError = false;
    this.lastPageContext = currentPageContext();
    this.protocolMetadata = {};
    this.render();
  }

  NativeAiSidebar.prototype.label = function (key, fallback) {
    return this.labels[key] || fallback;
  };

  NativeAiSidebar.prototype.render = function () {
    this.root.innerHTML = [
      '<div class="native-ai-ui">',
      '  <div class="native-ai-ui-header">',
      '    <h2 class="native-ai-ui-title">' + escapeHtml(this.label("title", "ИИ-чат")) + "</h2>",
      '    <button type="button" class="native-ai-ui-icon-button" data-native-ai-new-chat aria-label="' + escapeHtml(this.label("new_chat", "Новый чат")) + '" title="' + escapeHtml(this.label("new_chat", "Новый чат")) + '">+</button>',
      "  </div>",
      '  <div class="native-ai-ui-status" data-native-ai-status aria-live="polite"></div>',
      '  <div class="native-ai-ui-messages" data-native-ai-messages>',
      '    <div class="sidebar-chat-empty">' + escapeHtml(this.label("initial", "Опишите задачу.")) + "</div>",
      "  </div>",
      '  <form class="native-ai-ui-form" data-native-ai-form>',
      '    <textarea rows="1" autocomplete="off" placeholder="' + escapeHtml(this.label("placeholder", "Сообщение...")) + '"></textarea>',
      '    <button type="submit" aria-label="' + escapeHtml(this.label("send", "Отправить")) + '" title="' + escapeHtml(this.label("send", "Отправить")) + '">&gt;</button>',
      "  </form>",
      "</div>",
    ].join("");
    this.list = this.root.querySelector("[data-native-ai-messages]");
    this.form = this.root.querySelector("[data-native-ai-form]");
    this.input = this.form.querySelector("textarea");
    this.send = this.form.querySelector('button[type="submit"]');
    this.newChatButton = this.root.querySelector("[data-native-ai-new-chat]");
    this.statusNode = this.root.querySelector("[data-native-ai-status]");
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
    this.newChatButton.addEventListener("click", function () {
      self.createNewChat();
    });
    window.addEventListener("ai-context:update", function (event) {
      if (event.detail) self.lastPageContext = event.detail;
    });
  };

  NativeAiSidebar.prototype.resizeInput = function () {
    this.input.style.height = "auto";
    this.input.style.height = Math.min(this.input.scrollHeight, 180) + "px";
  };

  NativeAiSidebar.prototype.scrollToBottom = function () {
    this.list.scrollTop = this.list.scrollHeight;
  };

  NativeAiSidebar.prototype.setStatus = function (text, tone) {
    this.statusNode.textContent = text || "";
    this.statusNode.dataset.tone = tone || "";
  };

  NativeAiSidebar.prototype.clearMessages = function () {
    this.messages = [];
    this.executedCommands.clear();
    this.messageNodes = {};
    this.toolNodes = {};
    this.toolBuffers = {};
    this.currentAssistant = null;
    this.list.innerHTML = '<div class="sidebar-chat-empty">' + escapeHtml(this.label("initial", "Опишите задачу.")) + "</div>";
    this.setStatus("");
  };

  NativeAiSidebar.prototype.appendMessage = function (role, content, pending, id) {
    var empty = this.list.querySelector(".sidebar-chat-empty");
    if (empty) empty.remove();
    var item = document.createElement("div");
    item.className = "native-ai-ui-message is-" + role;
    if (pending) item.classList.add("is-pending");
    var label = role === "user"
      ? this.label("user", "Вы")
      : role === "tool"
        ? this.label("tool", "Инструмент")
        : this.label("assistant", "Ассистент");
    item.innerHTML = [
      '<div class="native-ai-ui-meta">' + escapeHtml(label) + "</div>",
      '<div class="native-ai-ui-bubble">' + escapeHtml(content || "") + "</div>",
    ].join("");
    this.list.appendChild(item);
    this.scrollToBottom();
    if (id) this.messageNodes[id] = item;
    return item;
  };

  NativeAiSidebar.prototype.setPending = function (value) {
    this.pending = value;
    this.input.disabled = value;
    this.send.disabled = value;
    this.newChatButton.disabled = value;
  };

  NativeAiSidebar.prototype.createNewChat = function () {
    var self = this;
    if (this.pending || !this.newSessionUrl) return;
    this.setPending(true);
    this.setStatus("Создание нового чата...");
    fetch(this.newSessionUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: "{}",
    })
      .then(function (response) {
        if (!response.ok) throw new Error("new session failed");
        return response.json();
      })
      .then(function (config) {
        self.config = config;
        self.labels = config.labels || self.labels;
        self.clearMessages();
        self.setPending(false);
        self.input.focus();
      })
      .catch(function () {
        self.setStatus("Не удалось создать новый чат.", "error");
        self.setPending(false);
      });
  };

  NativeAiSidebar.prototype.submit = function () {
    if (this.pending) return;
    var prompt = this.input.value.trim();
    if (!prompt) return;
    this.setPending(true);
    this.setStatus("Отправка...");
    this.input.value = "";
    this.resizeInput();
    var userMessage = { id: "user_" + Date.now() + "_" + randomSuffix(), role: "user", content: prompt };
    this.messages.push(userMessage);
    this.appendMessage("user", prompt, false, userMessage.id);
    var assistantId = "assistant_" + Date.now() + "_" + randomSuffix();
    var assistantNode = this.appendMessage("assistant", this.label("assistant_typing", "Печатает..."), true, assistantId);
    this.currentAssistant = { id: assistantId, node: assistantNode, text: "" };
    this.runAgent(assistantNode, assistantId);
  };

  NativeAiSidebar.prototype.runAgent = function (assistantNode, assistantId) {
    var self = this;
    this.runHadError = false;
    this.activeRunId = "native_" + Date.now().toString(36) + "_" + randomSuffix();
    var forwardedProps = Object.assign({}, this.config.forwarded_props || {}, {
      page_context: this.lastPageContext && this.lastPageContext.envelope ? this.lastPageContext : currentPageContext(),
    });
    var payload = {
      threadId: this.config.thread_id,
      runId: this.activeRunId,
      state: {
        localBusiness: {
          protocol: this.protocolMetadata || {},
        },
      },
      messages: this.messages.slice(-16),
      tools: [],
      context: [],
      forwardedProps: forwardedProps,
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
    })
      .then(function (response) {
        if (!response.ok || !response.body) throw new Error("stream failed");
        return self.readStream(response.body, assistantNode, assistantId);
      })
      .then(function (result) {
        assistantNode.classList.remove("is-pending");
        if (!result.hadError && result.text) {
          self.messages.push({ id: assistantId, role: "assistant", content: result.text });
          self.setStatus("");
        } else if (!result.hadError && !result.text) {
          self.showRunError(assistantNode, "ИИ-сервис не вернул ответ.");
        }
        self.finishRun();
      })
      .catch(function () {
        assistantNode.classList.remove("is-pending");
        self.showRunError(assistantNode, self.label("error", "Не удалось получить ответ от ИИ-сервиса."));
        self.finishRun();
      });
  };

  NativeAiSidebar.prototype.finishRun = function () {
    this.activeRunId = "";
    this.currentAssistant = null;
    this.setPending(false);
    this.input.focus();
  };

  NativeAiSidebar.prototype.readStream = function (body, assistantNode, assistantId) {
    var self = this;
    var reader = body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var result = { text: "", hadError: false };

    function processBlock(block) {
      if (!block.trim()) return;
      var data = eventDataFromBlock(block);
      if (!data || data === "[DONE]") return;
      try {
        self.handleEvent(JSON.parse(data), assistantNode, assistantId, result);
      } catch (error) {
        // Unknown or malformed stream chunks are ignored; transport errors still fail the run.
      }
    }

    function read() {
      return reader.read().then(function (chunk) {
        if (chunk.done) {
          buffer += decoder.decode();
          if (buffer) processBlock(buffer);
          return result;
        }
        buffer += decoder.decode(chunk.value, { stream: true });
        var blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        blocks.forEach(processBlock);
        return read();
      });
    }

    return read();
  };

  NativeAiSidebar.prototype.handleEvent = function (event, assistantNode, assistantId, result) {
    if (!event || !event.type) return;
    switch (event.type) {
      case "RUN_STARTED":
        this.setStatus("ИИ обрабатывает запрос...");
        return;
      case "RUN_FINISHED":
        if (!this.runHadError) this.setStatus("");
        return;
      case "RUN_ERROR":
        result.hadError = true;
        this.runHadError = true;
        this.showRunError(assistantNode, event.message || "ИИ-сервис вернул ошибку.");
        return;
      case "TEXT_MESSAGE_START":
        this.startAssistantMessage(event.messageId || assistantId, assistantNode);
        return;
      case "TEXT_MESSAGE_CONTENT":
        this.appendAssistantDelta(event.messageId || assistantId, assistantNode, String(event.delta || ""), result);
        return;
      case "TEXT_MESSAGE_END":
        this.endAssistantMessage(event.messageId || assistantId);
        return;
      case "TOOL_CALL_START":
        this.startToolTrace(event);
        return;
      case "TOOL_CALL_ARGS":
        this.updateToolTrace(event, "args");
        return;
      case "TOOL_CALL_END":
        this.updateToolTrace(event, "done");
        return;
      case "TOOL_CALL_RESULT":
        this.updateToolTrace(event, "result");
        return;
      case "STATE_SNAPSHOT":
        this.applyStateSnapshot(event.snapshot);
        return;
      case "STATE_DELTA":
        this.applyStateDelta(event.delta);
        return;
      case "CUSTOM":
        this.handleCustomEvent(event);
        return;
      default:
        return;
    }
  };

  NativeAiSidebar.prototype.startAssistantMessage = function (messageId, fallbackNode) {
    var node = this.messageNodes[messageId] || fallbackNode;
    var bubble = node.querySelector(".native-ai-ui-bubble");
    node.classList.add("is-pending");
    bubble.textContent = "";
    this.currentAssistant = { id: messageId, node: node, text: "" };
    this.messageNodes[messageId] = node;
  };

  NativeAiSidebar.prototype.appendAssistantDelta = function (messageId, fallbackNode, delta, result) {
    if (!delta) return;
    if (!this.currentAssistant || this.currentAssistant.id !== messageId) {
      this.startAssistantMessage(messageId, fallbackNode);
    }
    this.currentAssistant.text += delta;
    result.text += delta;
    this.currentAssistant.node.querySelector(".native-ai-ui-bubble").textContent = this.currentAssistant.text;
    this.scrollToBottom();
  };

  NativeAiSidebar.prototype.endAssistantMessage = function (messageId) {
    var node = this.messageNodes[messageId] || (this.currentAssistant && this.currentAssistant.node);
    if (node) node.classList.remove("is-pending");
  };

  NativeAiSidebar.prototype.showRunError = function (assistantNode, message) {
    assistantNode.classList.remove("is-pending");
    assistantNode.classList.add("is-error");
    assistantNode.querySelector(".native-ai-ui-bubble").textContent = message || "ИИ-сервис вернул ошибку.";
    this.setStatus(message || "ИИ-сервис вернул ошибку.", "error");
  };

  NativeAiSidebar.prototype.startToolTrace = function (event) {
    var toolCallId = String(event.toolCallId || "tool_" + randomSuffix());
    var toolName = String(event.toolCallName || "tool");
    var node = this.appendMessage("tool", toolName + " - " + this.label("tool_running", "Выполняется"), false, toolCallId);
    node.dataset.toolCallId = toolCallId;
    this.toolNodes[toolCallId] = node;
    this.toolBuffers[toolCallId] = "";
  };

  NativeAiSidebar.prototype.updateToolTrace = function (event, phase) {
    var toolCallId = String(event.toolCallId || "");
    if (!toolCallId) return;
    var node = this.toolNodes[toolCallId];
    if (!node) {
      this.startToolTrace({ toolCallId: toolCallId, toolCallName: event.toolCallName || "tool" });
      node = this.toolNodes[toolCallId];
    }
    if (phase === "args") {
      this.toolBuffers[toolCallId] = (this.toolBuffers[toolCallId] || "") + String(event.delta || "");
      node.querySelector(".native-ai-ui-bubble").textContent = "Аргументы получены";
      return;
    }
    if (phase === "done") {
      node.querySelector(".native-ai-ui-bubble").textContent = this.label("tool_done", "Готово");
      return;
    }
    if (phase === "result") {
      node.querySelector(".native-ai-ui-bubble").textContent = "Результат получен";
    }
  };

  NativeAiSidebar.prototype.applyStateSnapshot = function (snapshot) {
    if (!snapshot || typeof snapshot !== "object") return;
    var commands = snapshot.localBusiness && Array.isArray(snapshot.localBusiness.uiCommands)
      ? snapshot.localBusiness.uiCommands
      : Array.isArray(snapshot.localBusinessUiCommands)
        ? snapshot.localBusinessUiCommands
        : [];
    this.executeUiCommands(commands);
  };

  NativeAiSidebar.prototype.applyStateDelta = function (delta) {
    var self = this;
    if (!Array.isArray(delta)) return;
    delta.forEach(function (operation) {
      if (!operation || ["replace", "add"].indexOf(operation.op) === -1) return;
      if (operation.path !== "/localBusiness/uiCommands" && operation.path !== "/localBusinessUiCommands") return;
      self.executeUiCommands(Array.isArray(operation.value) ? operation.value : []);
    });
  };

  NativeAiSidebar.prototype.handleCustomEvent = function (event) {
    if (event.name === "local_business.protocol" && event.value && typeof event.value === "object") {
      this.protocolMetadata = event.value;
      return;
    }
    if (event.name === "local_business.ui_command") {
      this.executeUiCommands([event.value]);
    }
  };

  NativeAiSidebar.prototype.executeUiCommands = function (commands) {
    var self = this;
    if (!Array.isArray(commands)) return;
    commands.forEach(function (command) {
      self.executeUiCommand(command);
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
    })
      .then(function (response) {
        if (!response.ok) throw new Error("config failed");
        return response.json();
      })
      .then(function (config) {
        new NativeAiSidebar(root, config);
      })
      .catch(function () {
        root.innerHTML = '<div class="native-ai-ui-error">ИИ-чат недоступен.</div>';
      });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
