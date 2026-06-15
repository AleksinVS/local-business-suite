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

  function currentTimeLabel() {
    var now = new Date();
    return now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
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
    this.labels = {};
    this.urls = {};
    this.models = [];
    this.currentModelId = "";
    this.newSessionUrl = root.dataset.newSessionUrl || "";
    this.applyConfig(config || {});
    this.messages = this.messagesFromConfig(this.config);
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
    this.contextListenerBound = false;
    this.render();
  }

  NativeAiSidebar.prototype.applyConfig = function (config) {
    this.config = config || {};
    this.labels = this.config.labels || this.labels || {};
    this.urls = this.config.urls || {};
    this.models = Array.isArray(this.config.models) ? this.config.models : [];
    this.currentModelId = String(this.config.current_model_id || "");
    this.newSessionUrl = this.root.dataset.newSessionUrl || this.urls.new_session_url || this.newSessionUrl || "";
    if (this.config.forwarded_props && this.currentModelId) {
      this.config.forwarded_props.model_id = this.currentModelId;
    }
  };

  NativeAiSidebar.prototype.messagesFromConfig = function (config) {
    var messages = Array.isArray(config.messages) ? config.messages : [];
    return messages
      .filter(function (message) {
        return message && ["user", "assistant", "tool", "system"].indexOf(String(message.role || "")) !== -1;
      })
      .map(function (message) {
        return {
          id: String(message.id || "history_" + randomSuffix()),
          role: String(message.role || "assistant"),
          content: String(message.content || ""),
          tool_name: String(message.tool_name || ""),
          created_at_display: String(message.created_at_display || ""),
          error: Boolean(message.error),
        };
      });
  };

  NativeAiSidebar.prototype.selectedModelId = function () {
    if (this.currentModelId) return this.currentModelId;
    for (var i = 0; i < this.models.length; i += 1) {
      if (this.models[i] && this.models[i].selected) return String(this.models[i].id || "");
    }
    for (var j = 0; j < this.models.length; j += 1) {
      if (this.models[j] && this.models[j].default) return String(this.models[j].id || "");
    }
    return this.models[0] ? String(this.models[0].id || "") : "";
  };

  NativeAiSidebar.prototype.modelOptionsHtml = function () {
    var selectedId = this.selectedModelId();
    return this.models.map(function (model) {
      var id = String(model.id || "");
      if (!id) return "";
      return '<option value="' + escapeHtml(id) + '"' + (id === selectedId ? " selected" : "") + ">" + escapeHtml(model.name || id) + "</option>";
    }).join("");
  };

  NativeAiSidebar.prototype.label = function (key, fallback) {
    return this.labels[key] || fallback;
  };

  NativeAiSidebar.prototype.render = function () {
    var fullChatUrl = this.urls.full_chat_url || "";
    var modelSelect = this.models.length
      ? [
        '    <label class="native-ai-ui-model">',
        '      <span>' + escapeHtml(this.label("model", "Модель")) + "</span>",
        '      <select data-native-ai-model aria-label="' + escapeHtml(this.label("model", "Модель")) + '">',
        this.modelOptionsHtml(),
        "      </select>",
        "    </label>",
      ].join("")
      : "";
    var fullChatLink = fullChatUrl
      ? '<a class="native-ai-ui-icon-link" href="' + escapeHtml(fullChatUrl) + '" aria-label="' + escapeHtml(this.label("full_chat", "Открыть полный чат")) + '" title="' + escapeHtml(this.label("full_chat", "Открыть полный чат")) + '">↗</a>'
      : "";
    this.root.innerHTML = [
      '<div class="native-ai-ui">',
      '  <div class="native-ai-ui-header">',
      '    <div class="native-ai-ui-title-row">',
      '      <h2 class="native-ai-ui-title">' + escapeHtml(this.label("title", "ИИ-чат")) + "</h2>",
      '      <div class="native-ai-ui-actions">',
      fullChatLink,
      '        <button type="button" class="native-ai-ui-icon-button" data-native-ai-clear-chat aria-label="' + escapeHtml(this.label("clear_chat", "Очистить чат")) + '" title="' + escapeHtml(this.label("clear_chat", "Очистить чат")) + '">×</button>',
      '        <button type="button" class="native-ai-ui-icon-button" data-native-ai-new-chat aria-label="' + escapeHtml(this.label("new_chat", "Новый чат")) + '" title="' + escapeHtml(this.label("new_chat", "Новый чат")) + '">+</button>',
      "      </div>",
      "    </div>",
      modelSelect,
      "  </div>",
      '  <div class="native-ai-ui-status" data-native-ai-status aria-live="polite"></div>',
      '  <div class="native-ai-ui-messages" data-native-ai-messages></div>',
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
    this.clearChatButton = this.root.querySelector("[data-native-ai-clear-chat]");
    this.modelSelect = this.root.querySelector("[data-native-ai-model]");
    this.statusNode = this.root.querySelector("[data-native-ai-status]");
    this.renderMessages();
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
    if (this.clearChatButton) {
      this.clearChatButton.addEventListener("click", function () {
        self.clearChat();
      });
    }
    if (this.modelSelect) {
      this.modelSelect.addEventListener("change", function () {
        self.updateModel(self.modelSelect.value);
      });
    }
    if (!this.contextListenerBound) {
      window.addEventListener("ai-context:update", function (event) {
        if (event.detail) self.lastPageContext = event.detail;
      });
      this.contextListenerBound = true;
    }
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

  NativeAiSidebar.prototype.renderMessages = function () {
    var self = this;
    this.messageNodes = {};
    this.toolNodes = {};
    this.toolBuffers = {};
    this.list.innerHTML = "";
    if (!this.messages.length) {
      this.list.innerHTML = '<div class="sidebar-chat-empty">' + escapeHtml(this.label("initial", "Опишите задачу.")) + "</div>";
      return;
    }
    this.messages.forEach(function (message) {
      self.appendMessage(message.role, message.content, false, message.id, {
        time: message.created_at_display,
        error: message.error,
        toolName: message.tool_name,
      });
    });
  };

  NativeAiSidebar.prototype.appendMessage = function (role, content, pending, id, options) {
    options = options || {};
    var empty = this.list.querySelector(".sidebar-chat-empty");
    if (empty) empty.remove();
    var item = document.createElement("div");
    item.className = "native-ai-ui-message is-" + role;
    if (pending) item.classList.add("is-pending");
    if (options.error) item.classList.add("is-error");
    var label = role === "user"
      ? this.label("user", "Вы")
      : role === "tool"
        ? this.label("tool", "Инструмент")
        : this.label("assistant", "Ассистент");
    var time = options.time ? '<time>' + escapeHtml(options.time) + "</time>" : "";
    var toolName = options.toolName ? '<span class="native-ai-ui-tool-name">' + escapeHtml(options.toolName) + "</span>" : "";
    item.innerHTML = [
      '<div class="native-ai-ui-meta"><span>' + escapeHtml(label) + "</span>" + time + toolName + "</div>",
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
    if (this.clearChatButton) this.clearChatButton.disabled = value;
    if (this.modelSelect) this.modelSelect.disabled = value;
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
        self.applyConfig(config);
        self.messages = self.messagesFromConfig(self.config);
        self.pending = false;
        self.render();
        self.input.focus();
      })
      .catch(function () {
        self.setStatus("Не удалось создать новый чат.", "error");
        self.setPending(false);
      });
  };

  NativeAiSidebar.prototype.clearChat = function () {
    var self = this;
    var clearUrl = this.urls.clear_session_url || "";
    if (this.pending || !clearUrl) return;
    if (!window.confirm("Очистить историю бокового чата?")) return;
    this.setPending(true);
    this.setStatus("Очистка чата...");
    fetch(clearUrl, {
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
        if (!response.ok) throw new Error("clear session failed");
        return response.json();
      })
      .then(function (config) {
        self.applyConfig(config);
        self.messages = self.messagesFromConfig(self.config);
        self.executedCommands.clear();
        self.pending = false;
        self.render();
        self.input.focus();
      })
      .catch(function () {
        self.setStatus("Не удалось очистить чат.", "error");
        self.setPending(false);
      });
  };

  NativeAiSidebar.prototype.updateModel = function (modelId) {
    var self = this;
    var updateUrl = this.urls.model_update_url || "";
    var previousModelId = this.currentModelId;
    if (this.pending || !updateUrl) return;
    this.currentModelId = String(modelId || "");
    this.setStatus("Обновление модели...");
    fetch(updateUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify({ model_id: this.currentModelId }),
    })
      .then(function (response) {
        if (!response.ok) throw new Error("model update failed");
        return response.json();
      })
      .then(function (payload) {
        self.currentModelId = String(payload.model_id || self.currentModelId || "");
        self.config.current_model_id = self.currentModelId;
        if (self.config.forwarded_props) self.config.forwarded_props.model_id = self.currentModelId;
        self.setStatus("Модель обновлена.");
        window.setTimeout(function () {
          if (self.statusNode && self.statusNode.textContent === "Модель обновлена.") self.setStatus("");
        }, 1800);
      })
      .catch(function () {
        self.currentModelId = previousModelId;
        if (self.modelSelect) self.modelSelect.value = self.selectedModelId();
        self.setStatus("Не удалось обновить модель.", "error");
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
    var userMessage = {
      id: "user_" + Date.now() + "_" + randomSuffix(),
      role: "user",
      content: prompt,
      created_at_display: currentTimeLabel(),
    };
    this.messages.push(userMessage);
    this.appendMessage("user", prompt, false, userMessage.id, { time: userMessage.created_at_display });
    var assistantId = "assistant_" + Date.now() + "_" + randomSuffix();
    var assistantTime = currentTimeLabel();
    var assistantNode = this.appendMessage("assistant", this.label("assistant_typing", "Печатает..."), true, assistantId, { time: assistantTime });
    this.currentAssistant = { id: assistantId, node: assistantNode, text: "", time: assistantTime };
    this.runAgent(assistantNode, assistantId);
  };

  NativeAiSidebar.prototype.runAgent = function (assistantNode, assistantId) {
    var self = this;
    this.runHadError = false;
    this.activeRunId = "native_" + Date.now().toString(36) + "_" + randomSuffix();
    var forwardedProps = Object.assign({}, this.config.forwarded_props || {}, {
      page_context: this.lastPageContext && this.lastPageContext.envelope ? this.lastPageContext : currentPageContext(),
    });
    if (this.currentModelId) forwardedProps.model_id = this.currentModelId;
    var payload = {
      threadId: this.config.thread_id,
      runId: this.activeRunId,
      state: {
        localBusiness: {
          protocol: this.protocolMetadata || {},
        },
      },
      messages: this.messages.slice(-16).map(function (message) {
        return { id: message.id, role: message.role, content: message.content };
      }),
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
          self.messages.push({
            id: assistantId,
            role: "assistant",
            content: result.text,
            created_at_display: self.currentAssistant && self.currentAssistant.time ? self.currentAssistant.time : currentTimeLabel(),
          });
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
    var existingTime = this.currentAssistant && this.currentAssistant.time ? this.currentAssistant.time : currentTimeLabel();
    this.currentAssistant = { id: messageId, node: node, text: "", time: existingTime };
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
    var node = this.appendMessage("tool", toolName + " - " + this.label("tool_running", "Выполняется"), false, toolCallId, {
      time: currentTimeLabel(),
      toolName: toolName,
    });
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
