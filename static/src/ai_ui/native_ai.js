(function () {
  "use strict";

  var AI_CHAT_UNAVAILABLE_MESSAGE = "В данный момент, ИИ-чат недоступен, обратитесь к администратору портала";

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
    var hasCommandId = Object.prototype.hasOwnProperty.call(command, "command_id");
    var commandId = hasCommandId ? String(command.command_id || "").trim() : "";
    if (hasCommandId && !/^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/.test(commandId)) return null;
    var normalized = {
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
    if (hasCommandId) normalized.command_id = commandId;
    return normalized;
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

  function isAllowedLink(value) {
    var href = String(value || "").trim();
    if (!href || /^(?:javascript|data):/i.test(href)) return false;
    if (/^(?:https?|mailto):/i.test(href)) return true;
    if (href.charAt(0) !== "/" || href.indexOf("//") === 0) return false;
    return true;
  }

  function appendInlineMarkdown(container, value) {
    var text = String(value || "");
    var pattern = /(\*\*[^*\n]+\*\*|`[^`\n]+`|\[[^\]\n]+\]\([^)]{1,2048}\))/g;
    var cursor = 0;
    var match;
    while ((match = pattern.exec(text))) {
      if (match.index > cursor) container.appendChild(document.createTextNode(text.slice(cursor, match.index)));
      var token = match[0];
      if (token.indexOf("**") === 0) {
        var strong = document.createElement("strong");
        strong.textContent = token.slice(2, -2);
        container.appendChild(strong);
      } else if (token.charAt(0) === "`") {
        var code = document.createElement("code");
        code.textContent = token.slice(1, -1);
        container.appendChild(code);
      } else {
        var linkMatch = /^\[([^\]]+)\]\(([^)]+)\)$/.exec(token);
        if (!linkMatch || !isAllowedLink(linkMatch[2])) {
          container.appendChild(document.createTextNode(token));
        } else {
          var link = document.createElement("a");
          link.textContent = linkMatch[1];
          link.href = linkMatch[2];
          if (/^https?:/i.test(link.href)) {
            link.target = "_blank";
            link.rel = "noopener noreferrer";
          }
          container.appendChild(link);
        }
      }
      cursor = match.index + token.length;
    }
    if (cursor < text.length) container.appendChild(document.createTextNode(text.slice(cursor)));
  }

  function renderSafeMarkdown(container, value) {
    if (!container) return;
    container.replaceChildren();
    var lines = String(value || "").replace(/\r\n?/g, "\n").split("\n");
    var inCode = false;
    var codeLines = [];
    var list = null;
    function closeList() {
      if (list) container.appendChild(list);
      list = null;
    }
    function closeCode() {
      var pre = document.createElement("pre");
      var code = document.createElement("code");
      code.textContent = codeLines.join("\n");
      pre.appendChild(code);
      container.appendChild(pre);
      codeLines = [];
    }
    lines.forEach(function (line) {
      if (/^\s*```/.test(line)) {
        if (inCode) { closeCode(); inCode = false; }
        else { closeList(); inCode = true; }
        return;
      }
      if (inCode) { codeLines.push(line); return; }
      var listMatch = /^\s*(?:[-*]|\d+\.)\s+(.+)$/.exec(line);
      if (listMatch) {
        var ordered = /^\s*\d+\./.test(line);
        if (!list || list.tagName.toLowerCase() !== (ordered ? "ol" : "ul")) {
          closeList();
          list = document.createElement(ordered ? "ol" : "ul");
        }
        var item = document.createElement("li");
        appendInlineMarkdown(item, listMatch[1]);
        list.appendChild(item);
        return;
      }
      closeList();
      if (!line) return;
      var paragraph = document.createElement("p");
      appendInlineMarkdown(paragraph, line);
      container.appendChild(paragraph);
    });
    if (inCode) closeCode();
    closeList();
  }

  function NativeAiSidebar(root, config) {
    this.root = root;
    this.surface = String(root.dataset.surface || (config && config.surface) || "sidebar");
    this.isFullPage = this.surface === "full_page";
    this.labels = {};
    this.urls = {};
    this.models = [];
    this.currentModelId = "";
    this.newSessionUrl = root.dataset.newSessionUrl || "";
    this.applyConfig(config || {});
    this.messages = this.messagesFromConfig(this.config);
    this.executedCommands = this.loadExecutedCommands();
    this.messageNodes = {};
    this.toolNodes = {};
    this.toolBuffers = {};
    this.pending = false;
    this.currentAssistant = null;
    this.activeRunId = "";
    this.runHadError = false;
    this.lastPageContext = currentPageContext();
    this.protocolMetadata = {};
    this.abortController = null;
    this.generation = 0;
    this.activeThreadId = "";
    this.runState = null;
    this.boundHandlers = null;
    this.pendingFiles = [];
    this.previewUrls = [];
    this.commandItems = [];
    this.commandIndex = -1;
    this.recoveryAttempted = false;
    this.render();
    var self = this;
    window.setTimeout(function () { self.resumePreparedRun(); }, 0);
  }

  NativeAiSidebar.prototype.applyConfig = function (config) {
    var previousThreadId = String((this.config && (this.config.thread_id || this.config.threadId)) || "");
    this.config = config || {};
    this.surface = String(this.root.dataset.surface || this.config.surface || this.surface || "sidebar");
    this.isFullPage = this.surface === "full_page";
    this.labels = this.config.labels || this.labels || {};
    this.urls = this.config.urls || {};
    this.models = Array.isArray(this.config.models) ? this.config.models : [];
    this.currentModelId = String(this.config.current_model_id || "");
    this.newSessionUrl = this.root.dataset.newSessionUrl || this.urls.new_session_url || this.newSessionUrl || "";
    var nextThreadId = String(this.config.thread_id || this.config.threadId || "");
    if (this.executedCommands && previousThreadId !== nextThreadId) {
      this.executedCommands = this.loadExecutedCommands();
    }
  };

  NativeAiSidebar.prototype.commandStorageKey = function () {
    var threadId = String((this.config && (this.config.thread_id || this.config.threadId)) || "");
    return threadId ? "local-business-native-ai-ui-commands:" + threadId : "";
  };

  NativeAiSidebar.prototype.loadExecutedCommands = function () {
    var key = this.commandStorageKey();
    if (!key || !window.sessionStorage) return new Set();
    try {
      var values = JSON.parse(window.sessionStorage.getItem(key) || "[]");
      return new Set(Array.isArray(values) ? values.slice(-100).map(String) : []);
    } catch (error) {
      return new Set();
    }
  };

  NativeAiSidebar.prototype.rememberExecutedCommand = function (key) {
    this.executedCommands.add(key);
    var storageKey = this.commandStorageKey();
    if (!storageKey || !window.sessionStorage) return;
    try {
      window.sessionStorage.setItem(storageKey, JSON.stringify(Array.from(this.executedCommands).slice(-100)));
    } catch (error) {
      // sessionStorage can be unavailable in restricted browser contexts.
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
          attachments: Array.isArray(message.attachments) ? message.attachments : [],
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
    this.unbind();
    if (this.isFullPage) this.root.classList.add("native-ai-rich");
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
    var existingForm = this.root.querySelector("[data-native-ai-form]");
    var existingList = this.root.querySelector("[data-native-ai-messages]");
    var preserveMarkup = !this.ownsMarkup && existingForm && existingList;
    if (!preserveMarkup) this.root.innerHTML = [
      '<div class="native-ai-ui">',
      '  <div class="native-ai-ui-header">',
      '    <div class="native-ai-ui-title-row">',
      '      <h2 class="native-ai-ui-title">' + escapeHtml(this.label("title", "ИИ-чат")) + "</h2>",
      '      <div class="native-ai-ui-actions">',
      fullChatLink,
      '        <button type="button" class="native-ai-ui-icon-button" data-native-ai-clear-chat aria-label="' + escapeHtml(this.label("clear_chat", "Очистить чат")) + '" title="' + escapeHtml(this.label("clear_chat", "Очистить чат")) + '">×</button>',
      '        <button type="button" class="native-ai-ui-icon-button" data-native-ai-new-chat aria-label="' + escapeHtml(this.label("new_chat", "Новый чат")) + '" title="' + escapeHtml(this.label("new_chat", "Новый чат")) + '">+</button>',
      this.root.closest("[data-workorders-sidebar-shell]")
        ? '        <button type="button" class="workorders-ai-collapse" data-workorders-ai-collapse aria-label="Свернуть ИИ-чат">Свернуть</button>'
        : "",
      "      </div>",
      "    </div>",
      modelSelect,
      "  </div>",
      '  <div class="native-ai-ui-status" data-native-ai-status aria-live="polite"></div>',
      '  <div class="native-ai-ui-messages" data-native-ai-messages></div>',
      '  <form class="native-ai-ui-form" data-native-ai-form enctype="multipart/form-data">',
      this.isFullPage ? '    <div data-native-ai-attachment-preview></div>' : "",
      this.isFullPage ? '    <input type="file" data-native-ai-files multiple hidden>' : "",
      this.isFullPage ? '    <button type="button" data-native-ai-attach aria-label="Прикрепить файл">📎</button>' : "",
      '    <textarea rows="1" autocomplete="off" placeholder="' + escapeHtml(this.label("placeholder", "Сообщение...")) + '"></textarea>',
      '    <button type="submit" aria-label="' + escapeHtml(this.label("send", "Отправить")) + '" title="' + escapeHtml(this.label("send", "Отправить")) + '">&gt;</button>',
      "  </form>",
      "</div>",
    ].join("");
    if (!preserveMarkup) this.ownsMarkup = true;
    if (this.isFullPage) {
      this.root.classList.add("native-ai-rich");
      this.fileInput = this.root.querySelector("[data-native-ai-files]");
    }
    this.list = this.root.querySelector("[data-native-ai-messages]");
    this.form = this.root.querySelector("[data-native-ai-form]");
    this.input = this.form.querySelector("textarea");
    this.send = this.form.querySelector('button[type="submit"]');
    this.newChatButton = this.root.querySelector("[data-native-ai-new-chat]");
    this.clearChatButton = this.root.querySelector("[data-native-ai-clear-chat]");
    this.modelSelect = this.root.querySelector("[data-native-ai-model]");
    this.statusNode = this.root.querySelector("[data-native-ai-status]");
    this.fileInput = this.root.querySelector("[data-native-ai-files]") || this.fileInput || null;
    this.fileInput = this.fileInput || this.root.querySelector("[data-native-ai-file-input]") || this.root.querySelector('input[type="file"]');
    this.attachButton = this.root.querySelector("[data-native-ai-attach]");
    this.commandButton = this.root.querySelector("[data-native-ai-command-button], [data-native-ai-command]");
    this.commandMenu = this.root.querySelector("[data-native-ai-command-menu]");
    this.commandSearch = this.root.querySelector("[data-native-ai-command-search]");
    this.commandList = this.root.querySelector("[data-native-ai-command-list]");
    this.commandAutocomplete = this.root.querySelector("[data-native-ai-command-autocomplete]");
    this.autocomplete = this.root.querySelector("[data-native-ai-autocomplete]");
    this.autocompleteList = this.root.querySelector("[data-native-ai-autocomplete-list]");
    this.prompt = this.root.querySelector("[data-native-ai-prompt]") || this.input;
    this.attachmentPreview = this.root.querySelector("[data-native-ai-attachment-preview]");
    this.dropZone = this.root.querySelector("[data-native-ai-drop-zone]");
    this.titleDisplay = this.root.querySelector("[data-native-ai-title-display]");
    this.titleNode = this.root.querySelector("[data-native-ai-title]");
    this.titleEditButton = this.root.querySelector("[data-native-ai-title-edit]");
    this.titleEditor = this.root.querySelector("[data-native-ai-title-editor]");
    this.titleInput = this.root.querySelector("[data-native-ai-title-input]");
    this.titleSaveButton = this.root.querySelector("[data-native-ai-title-save]");
    this.titleCancelButton = this.root.querySelector("[data-native-ai-title-cancel]");
    this.sessionStatus = this.root.querySelector("[data-native-ai-session-status]");
    this.renderMessages();
    this.bind();
    this.focusComposerWhenExpanded();
  };

  NativeAiSidebar.prototype.isWorkordersChatExpanded = function () {
    var shell = this.root.closest("[data-workorders-sidebar-shell]");
    return !shell || shell.dataset.aiSidebarMode === "chat";
  };

  NativeAiSidebar.prototype.focusComposerWhenExpanded = function () {
    var self = this;
    if (!this.root.closest("[data-workorders-sidebar-shell]")) return;
    window.setTimeout(function () {
      if (self.input && self.isWorkordersChatExpanded()) self.input.focus();
    }, 0);
  };

  NativeAiSidebar.prototype.resumePreparedRun = function () {
    if (this.recoveryAttempted) return;
    this.recoveryAttempted = true;
    var recoverable = this.config && this.config.recoverable_run;
    if (!recoverable || recoverable.status !== "prepared") return;
    var runId = String(recoverable.run_id || "");
    var messageId = String(recoverable.message_id || "");
    var threadId = String(this.config.thread_id || this.config.threadId || "");
    if (!runId || !messageId || !threadId) return;
    var generation = ++this.generation;
    var assistantId = String(recoverable.assistant_message_id || "assistant_" + runId);
    var assistantTime = currentTimeLabel();
    this.setPending(true);
    this.setStatus("Восстановление запуска...");
    this.activeRunId = runId;
    this.activeThreadId = threadId;
    this.runState = { runId: runId, threadId: threadId, generation: generation, started: false, terminal: "", terminalCount: 0, aborted: false };
    var assistantNode = this.appendMessage("assistant", this.label("assistant_typing", "Печатает..."), true, assistantId, { time: assistantTime });
    this.currentAssistant = { id: assistantId, node: assistantNode, text: "", time: assistantTime };
    // The user message is already in the server-backed history.  Resume only
    // the exact prepared run; never submit/duplicate its prompt here.
    this.runAgent(assistantNode, assistantId, runId, generation, threadId);
  };

  NativeAiSidebar.prototype.bind = function () {
    var self = this;
    this.unbind();
    this.boundHandlers = {
      workordersOpen: function () {
      self.focusComposerWhenExpanded();
      },
      context: function (event) {
        if (event.detail) self.lastPageContext = event.detail;
      },
      input: function () {
        self.resizeInput();
        self.updateCommandAutocomplete();
      },
      keydown: function (event) {
      if (self.handleCommandKey(event)) return;
      if (event.key !== "Enter" || event.shiftKey || event.isComposing) return;
      event.preventDefault();
      self.form.requestSubmit();
      },
      submit: function (event) {
      event.preventDefault();
      self.submit();
      },
      newChat: function () {
      self.createNewChat();
      },
      clearChat: function () {
        self.clearChat();
      },
      model: function () {
        self.updateModel(self.modelSelect.value);
      },
      attach: function () {
        if (self.fileInput) self.fileInput.click();
      },
      files: function () {
        self.setPendingFiles(self.fileInput ? Array.prototype.slice.call(self.fileInput.files || []) : []);
      },
      command: function () {
        self.toggleCommandMenu();
      },
      commandSearch: function () {
        self.renderCommandCatalog(self.commandSearch.value);
      },
      titleEdit: function () {
        self.beginTitleEdit();
      },
      titleSave: function () {
        self.saveTitle();
      },
      titleCancel: function () {
        self.cancelTitleEdit();
      },
      titleKeydown: function (event) {
        if (event.key === "Enter") self.saveTitle();
        if (event.key === "Escape") self.cancelTitleEdit();
      },
      deleteSubmit: function (event) {
        if (!window.confirm("Удалить этот чат?")) event.preventDefault();
      },
      dragenter: function (event) {
        event.preventDefault();
        if (self.dropZone) { self.dropZone.hidden = false; self.dropZone.setAttribute("aria-hidden", "false"); }
      },
      dragover: function (event) {
        event.preventDefault();
      },
      dragleave: function (event) {
        if (event.target === self.list && self.dropZone) { self.dropZone.hidden = true; self.dropZone.setAttribute("aria-hidden", "true"); }
      },
      drop: function (event) {
        event.preventDefault();
        if (self.dropZone) { self.dropZone.hidden = true; self.dropZone.setAttribute("aria-hidden", "true"); }
        self.setPendingFiles(Array.prototype.slice.call((event.dataTransfer && event.dataTransfer.files) || []));
      },
    };
    document.addEventListener("workorders:ai-sidebar-open", this.boundHandlers.workordersOpen);
    window.addEventListener("ai-context:update", this.boundHandlers.context);
    if (this.input) {
      this.input.addEventListener("input", this.boundHandlers.input);
      this.input.addEventListener("keydown", this.boundHandlers.keydown);
    }
    if (this.form) this.form.addEventListener("submit", this.boundHandlers.submit);
    if (this.newChatButton) this.newChatButton.addEventListener("click", this.boundHandlers.newChat);
    if (this.clearChatButton) this.clearChatButton.addEventListener("click", this.boundHandlers.clearChat);
    if (this.modelSelect) this.modelSelect.addEventListener("change", this.boundHandlers.model);
    if (this.attachButton) this.attachButton.addEventListener("click", this.boundHandlers.attach);
    if (this.fileInput) this.fileInput.addEventListener("change", this.boundHandlers.files);
    if (this.commandButton) this.commandButton.addEventListener("click", this.boundHandlers.command);
    if (this.commandSearch) this.commandSearch.addEventListener("input", this.boundHandlers.commandSearch);
    if (this.titleEditButton) this.titleEditButton.addEventListener("click", this.boundHandlers.titleEdit);
    if (this.titleSaveButton) this.titleSaveButton.addEventListener("click", this.boundHandlers.titleSave);
    if (this.titleCancelButton) this.titleCancelButton.addEventListener("click", this.boundHandlers.titleCancel);
    if (this.titleInput) this.titleInput.addEventListener("keydown", this.boundHandlers.titleKeydown);
    // Full-page session navigation renders its delete forms outside the mount;
    // they are still chat mutations and must be locked during a run.
    this.deleteForms = Array.prototype.slice.call(document.querySelectorAll("[data-native-ai-delete-form]"));
    this.deleteForms.forEach(function (form) { form.addEventListener("submit", self.boundHandlers.deleteSubmit); });
    if (this.isFullPage && this.list && this.dropZone) {
      this.list.addEventListener("dragenter", this.boundHandlers.dragenter);
      this.list.addEventListener("dragover", this.boundHandlers.dragover);
      this.list.addEventListener("dragleave", this.boundHandlers.dragleave);
      this.list.addEventListener("drop", this.boundHandlers.drop);
    }
  };

  NativeAiSidebar.prototype.unbind = function () {
    var h = this.boundHandlers;
    if (!h) return;
    document.removeEventListener("workorders:ai-sidebar-open", h.workordersOpen);
    window.removeEventListener("ai-context:update", h.context);
    if (this.input) {
      this.input.removeEventListener("input", h.input);
      this.input.removeEventListener("keydown", h.keydown);
    }
    if (this.form) this.form.removeEventListener("submit", h.submit);
    if (this.newChatButton) this.newChatButton.removeEventListener("click", h.newChat);
    if (this.clearChatButton) this.clearChatButton.removeEventListener("click", h.clearChat);
    if (this.modelSelect) this.modelSelect.removeEventListener("change", h.model);
    if (this.attachButton) this.attachButton.removeEventListener("click", h.attach);
    if (this.fileInput) this.fileInput.removeEventListener("change", h.files);
    if (this.commandButton) this.commandButton.removeEventListener("click", h.command);
    if (this.commandSearch) this.commandSearch.removeEventListener("input", h.commandSearch);
    if (this.titleEditButton) this.titleEditButton.removeEventListener("click", h.titleEdit);
    if (this.titleSaveButton) this.titleSaveButton.removeEventListener("click", h.titleSave);
    if (this.titleCancelButton) this.titleCancelButton.removeEventListener("click", h.titleCancel);
    if (this.titleInput) this.titleInput.removeEventListener("keydown", h.titleKeydown);
    (this.deleteForms || []).forEach(function (form) { form.removeEventListener("submit", h.deleteSubmit); });
    if (this.isFullPage && this.list && this.dropZone) {
      this.list.removeEventListener("dragenter", h.dragenter);
      this.list.removeEventListener("dragover", h.dragover);
      this.list.removeEventListener("dragleave", h.dragleave);
      this.list.removeEventListener("drop", h.drop);
    }
    this.boundHandlers = null;
  };

  NativeAiSidebar.prototype.resizeInput = function () {
    if (!this.input) return;
    this.input.style.height = "auto";
    this.input.style.height = Math.min(this.input.scrollHeight, 180) + "px";
  };

  NativeAiSidebar.prototype.setPendingFiles = function (files) {
    this.revokePreviewUrls();
    this.pendingFiles = (files || []).filter(function (file) { return file && typeof file.name === "string"; });
    if (this.fileInput && typeof DataTransfer === "function") {
      try {
        var transfer = new DataTransfer();
        this.pendingFiles.forEach(function (file) { transfer.items.add(file); });
        this.fileInput.files = transfer.files;
      } catch (error) { /* FileList may be read-only in older browsers. */ }
    }
    this.renderPendingAttachments();
  };

  NativeAiSidebar.prototype.revokePreviewUrls = function () {
    this.previewUrls.forEach(function (url) {
      if (window.URL && typeof window.URL.revokeObjectURL === "function") window.URL.revokeObjectURL(url);
    });
    this.previewUrls = [];
  };

  NativeAiSidebar.prototype.renderPendingAttachments = function () {
    if (!this.attachmentPreview) return;
    this.revokePreviewUrls();
    this.attachmentPreview.replaceChildren();
    this.attachmentPreview.hidden = this.pendingFiles.length === 0;
    this.pendingFiles.forEach(function (file, index) {
      var item = document.createElement("span");
      item.className = "native-ai-ui-attachment";
      item.dataset.fileIndex = String(index);
      if (/^image\//i.test(file.type) && window.URL && typeof window.URL.createObjectURL === "function") {
        var image = document.createElement("img");
        var url = window.URL.createObjectURL(file);
        this.previewUrls.push(url);
        image.src = url;
        image.alt = file.name;
        item.appendChild(image);
      }
      var name = document.createElement("span");
      name.textContent = file.name;
      item.appendChild(name);
      var remove = document.createElement("button");
      remove.type = "button";
      remove.setAttribute("aria-label", "Удалить вложение " + file.name);
      remove.textContent = "×";
      remove.addEventListener("click", function () {
        var next = this.pendingFiles.filter(function (_, fileIndex) { return fileIndex !== index; });
        this.setPendingFiles(next);
      }.bind(this));
      item.appendChild(remove);
      this.attachmentPreview.appendChild(item);
    }, this);
  };

  NativeAiSidebar.prototype.commandCatalog = function () {
    var commands = this.config.commands || {};
    return (Array.isArray(commands.predefined) ? commands.predefined : [])
      .concat(Array.isArray(commands.custom) ? commands.custom : [])
      .filter(function (command) { return command && String(command.name || command.shortcut || "").trim(); });
  };

  NativeAiSidebar.prototype.commandName = function (command) {
    return String(command && (command.name || command.shortcut) || "").replace(/^\/+/, "");
  };

  NativeAiSidebar.prototype.toggleCommandMenu = function () {
    if (!this.commandMenu) return;
    var hidden = !this.commandMenu.hidden;
    this.commandMenu.hidden = hidden;
    if (this.commandButton) this.commandButton.setAttribute("aria-expanded", String(!hidden));
    if (!hidden) {
      this.renderCommandCatalog(this.commandSearch ? this.commandSearch.value : "");
      if (this.commandSearch) this.commandSearch.focus();
    }
  };

  NativeAiSidebar.prototype.renderCommandCatalog = function (query) {
    if (!this.commandList) return;
    var normalized = String(query || "").replace(/^\/+/, "").toLowerCase();
    this.commandList.replaceChildren();
    this.commandItems = this.commandCatalog().filter(function (command) {
      return this.commandName(command).toLowerCase().indexOf(normalized) !== -1;
    }, this);
    if (!this.commandItems.length) {
      var empty = document.createElement("div");
      empty.textContent = "Команды не найдены";
      this.commandList.appendChild(empty);
      return;
    }
    this.commandItems.forEach(function (command) {
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.textContent = "/" + this.commandName(command) + (command.description ? " — " + command.description : "");
      button.addEventListener("click", function () {
        this.insertCommand(this.commandName(command));
        this.toggleCommandMenu();
      }.bind(this));
      this.commandList.appendChild(button);
    }, this);
  };

  NativeAiSidebar.prototype.insertCommand = function (name) {
    if (!this.prompt) return;
    if (String(name || "").replace(/^\/+/, "") === "команды") {
      this.prompt.value = "";
      this.toggleCommandMenu();
      return;
    }
    var token = "/" + String(name || "").replace(/^\/+/, "") + " ";
    this.prompt.value = token;
    this.prompt.focus();
    this.prompt.setSelectionRange(token.length, token.length);
    this.updateCommandAutocomplete();
  };

  NativeAiSidebar.prototype.updateCommandAutocomplete = function () {
    if (!this.autocomplete || !this.autocompleteList || !this.prompt) return;
    var value = this.prompt.value;
    var match = /^\/([^\s]*)$/.exec(value);
    if (!match) {
      this.autocomplete.hidden = true;
      this.commandIndex = -1;
      return;
    }
    var query = match[1].toLowerCase();
    var commands = this.commandCatalog().filter(function (command) {
      return this.commandName(command).toLowerCase().indexOf(query) !== -1;
    }, this);
    this.autocompleteList.replaceChildren();
    this.commandItems = commands;
    this.commandIndex = -1;
    commands.forEach(function (command, index) {
      var button = document.createElement("button");
      button.type = "button";
      button.setAttribute("role", "option");
      button.textContent = "/" + this.commandName(command);
      button.addEventListener("click", function () { this.insertCommand(this.commandName(command)); }.bind(this));
      button.dataset.commandIndex = String(index);
      this.autocompleteList.appendChild(button);
    }, this);
    this.autocomplete.hidden = commands.length === 0;
  };

  NativeAiSidebar.prototype.handleCommandKey = function (event) {
    if (!this.autocomplete || this.autocomplete.hidden || !this.commandItems.length) return false;
    if (["ArrowDown", "ArrowUp", "Enter", "Escape"].indexOf(event.key) === -1) return false;
    event.preventDefault();
    if (event.key === "Escape") { this.autocomplete.hidden = true; return true; }
    if (event.key === "Enter") {
      var command = this.commandItems[this.commandIndex < 0 ? 0 : this.commandIndex];
      if (command) this.insertCommand(this.commandName(command));
      return true;
    }
    this.commandIndex = (this.commandIndex + (event.key === "ArrowDown" ? 1 : -1) + this.commandItems.length) % this.commandItems.length;
    var options = this.autocompleteList.querySelectorAll("[role=option]");
    Array.prototype.forEach.call(options, function (option, index) {
      option.setAttribute("aria-selected", String(index === this.commandIndex));
    }, this);
    return true;
  };

  NativeAiSidebar.prototype.scrollToBottom = function () {
    this.list.scrollTop = this.list.scrollHeight;
  };

  NativeAiSidebar.prototype.setStatus = function (text, tone) {
    if (!this.statusNode) return;
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
    this.revokePreviewUrls();
    this.list.innerHTML = '<div class="sidebar-chat-empty">' + escapeHtml(this.label("initial", "Опишите задачу.")) + "</div>";
    this.setStatus("");
  };

  NativeAiSidebar.prototype.renderMessages = function () {
    var self = this;
    var dropZone = this.list.querySelector("[data-native-ai-drop-zone]");
    this.messageNodes = {};
    this.toolNodes = {};
    this.toolBuffers = {};
    this.list.replaceChildren();
    if (!this.messages.length) {
      this.list.innerHTML = '<div class="sidebar-chat-empty">' + escapeHtml(this.label("initial", "Опишите задачу.")) + "</div>";
      if (dropZone) this.list.appendChild(dropZone);
      return;
    }
    this.messages.forEach(function (message) {
      self.appendMessage(message.role, message.content, false, message.id, {
        time: message.created_at_display,
        error: message.error,
        toolName: message.tool_name,
        attachments: message.attachments,
        markdown: message.role === "assistant",
      });
    });
    if (dropZone) this.list.appendChild(dropZone);
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
    if (options.markdown && role === "assistant") renderSafeMarkdown(item.querySelector(".native-ai-ui-bubble"), content || "");
    if (Array.isArray(options.attachments) && options.attachments.length) {
      var attachments = document.createElement("div");
      attachments.className = "native-ai-ui-attachments";
      options.attachments.forEach(function (attachment) {
        var link = document.createElement("a");
        var href = String(attachment.url || "");
        link.textContent = String(attachment.name || "Вложение");
        if (isAllowedLink(href)) {
          link.href = href;
          link.target = "_blank";
          link.rel = "noopener noreferrer";
        }
        attachments.appendChild(link);
      });
      item.appendChild(attachments);
    }
    this.list.appendChild(item);
    this.scrollToBottom();
    if (id) this.messageNodes[id] = item;
    return item;
  };

  NativeAiSidebar.prototype.setPending = function (value) {
    this.pending = value;
    var controls = [
      this.input, this.prompt, this.send, this.newChatButton,
      this.clearChatButton, this.modelSelect, this.fileInput, this.attachButton,
      this.commandButton, this.commandSearch, this.titleEditButton,
      this.titleSaveButton, this.titleCancelButton, this.titleInput,
    ];
    controls.forEach(function (control) {
      if (control && "disabled" in control) control.disabled = value;
    });
    (this.deleteForms || []).forEach(function (form) {
      form.querySelectorAll("button, input, select, textarea").forEach(function (control) {
        if ("disabled" in control) control.disabled = value;
      });
    });
    [this.commandList, this.autocompleteList].forEach(function (list) {
      if (!list) return;
      list.querySelectorAll("button, input, select, textarea").forEach(function (control) {
        if ("disabled" in control) control.disabled = value;
      });
    });
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
    var updateUrl = this.urls.model_url || this.urls.model_update_url || "";
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
        var modelValue = self.root.querySelector("[data-native-ai-model-value]");
        if (modelValue) modelValue.value = self.currentModelId;
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

  NativeAiSidebar.prototype.beginTitleEdit = function () {
    if (!this.titleEditor || !this.titleDisplay || !this.titleInput) return;
    this.titleInput.value = this.titleNode ? this.titleNode.textContent : this.titleInput.value;
    this.titleDisplay.hidden = true;
    this.titleEditor.hidden = false;
    this.titleInput.focus();
    this.titleInput.select();
  };

  NativeAiSidebar.prototype.cancelTitleEdit = function () {
    if (!this.titleEditor || !this.titleDisplay) return;
    this.titleEditor.hidden = true;
    this.titleDisplay.hidden = false;
  };

  NativeAiSidebar.prototype.saveTitle = function () {
    var self = this;
    var titleUrl = this.urls.title_url || "";
    var title = this.titleInput ? this.titleInput.value.trim() : "";
    if (!titleUrl || !title || this.pending) return;
    this.setStatus("Сохранение названия...");
    fetch(titleUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      body: JSON.stringify({ title: title }),
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) throw new Error(payload.error || "title update failed");
          return payload;
        });
      })
      .then(function (payload) {
        var saved = String(payload.title || title);
        if (self.titleNode) self.titleNode.textContent = saved;
        if (self.titleInput) self.titleInput.value = saved;
        var active = document.querySelector(".ai-session-row.is-active .ai-session-title");
        if (active) active.textContent = saved;
        self.cancelTitleEdit();
        self.setStatus("");
      })
      .catch(function () { self.setStatus("Не удалось сохранить название.", "error"); });
  };

  NativeAiSidebar.prototype.submit = function () {
    if (this.pending) return;
    var prompt = this.input.value.trim();
    var files = this.fileInput ? Array.prototype.slice.call(this.fileInput.files || []) : [];
    if (!prompt) return;
    if (prompt === "/команды") {
      this.input.value = "";
      this.toggleCommandMenu();
      return;
    }
    var self = this;
    var runId = "native_" + Date.now().toString(36) + "_" + randomSuffix();
    var generation = ++this.generation;
    var threadId = String(this.config.thread_id || this.config.threadId || "");
    var pageContext = this.lastPageContext && this.lastPageContext.envelope ? this.lastPageContext : currentPageContext();
    var prepareUrl = this.config.prepare_url || this.urls.prepare_turn_url || "";
    var modelId = this.selectedModelId();
    if (!prepareUrl || !threadId) {
      this.setStatus(this.label("error", AI_CHAT_UNAVAILABLE_MESSAGE), "error");
      return;
    }
    this.setPending(true);
    this.setStatus("Отправка...");
    this.input.value = "";
    this.resizeInput();
    this.pendingFiles = files;
    this.activeRunId = runId;
    this.activeThreadId = threadId;
    this.runState = { runId: runId, threadId: threadId, generation: generation, started: false, terminal: "", terminalCount: 0, aborted: false };
    this.abortController = typeof AbortController === "function" ? new AbortController() : null;
    var formData = new FormData();
    formData.append("run_id", runId);
    formData.append("prompt", prompt);
    formData.append("surface", this.surface);
    formData.append("model_id", modelId);
    formData.append("page_context", JSON.stringify(pageContext || {}));
    files.forEach(function (file) { formData.append("files", file); });
    fetch(prepareUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrfToken(), "X-Requested-With": "XMLHttpRequest" },
      body: formData,
      signal: this.abortController ? this.abortController.signal : undefined,
    })
      .then(function (response) {
        return response.json().catch(function () { return {}; }).then(function (payload) {
          if (!response.ok) throw new Error(payload.error || "prepare failed");
          return payload;
        });
      })
      .then(function (prepared) {
        if (!self.isActiveRun(runId, generation)) return null;
        var messageId = String(prepared.message_id || "");
        if (!messageId) throw new Error("prepare response missing message_id");
        var userMessage = {
          id: messageId,
          role: "user",
          content: prompt,
          created_at_display: currentTimeLabel(),
          attachments: files.map(function (file) { return { name: file.name, size: file.size, type: file.type }; }),
        };
        if (!self.messages.some(function (message) { return String(message.id) === messageId; })) {
          self.messages.push(userMessage);
          self.appendMessage("user", prompt, false, messageId, { time: userMessage.created_at_display, attachments: userMessage.attachments });
        }
        var assistantId = String(prepared.assistant_message_id || "assistant_" + Date.now() + "_" + randomSuffix());
        var assistantTime = currentTimeLabel();
        var assistantNode = self.appendMessage("assistant", self.label("assistant_typing", "Печатает..."), true, assistantId, { time: assistantTime });
        self.currentAssistant = { id: assistantId, node: assistantNode, text: "", time: assistantTime };
        self.activeThreadId = threadId;
        return self.runAgent(assistantNode, assistantId, runId, generation, threadId);
      })
      .catch(function (error) {
        if (!self.isActiveRun(runId, generation)) return;
        if (error && error.name === "AbortError") {
          if (self.runState) self.runState.aborted = true;
          if (self.currentAssistant && self.currentAssistant.node) self.currentAssistant.node.classList.remove("is-pending");
          self.finishRun(generation);
          return;
        }
        self.showRunError(self.currentAssistant && self.currentAssistant.node);
        self.finishRun(generation);
      });
  };

  NativeAiSidebar.prototype.isActiveRun = function (runId, generation) {
    return this.activeRunId === runId && this.generation === generation && this.runState && !this.runState.aborted;
  };

  NativeAiSidebar.prototype.runAgent = function (assistantNode, assistantId, runId, generation, threadId) {
    var self = this;
    this.runHadError = false;
    this.activeRunId = runId;
    this.runState = this.runState || { runId: runId, threadId: threadId, generation: generation, started: false, terminal: "", terminalCount: 0, aborted: false };
    var payload = { threadId: threadId, runId: runId };

    return fetch(this.config.runtime_url || this.urls.run_url, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: JSON.stringify(payload),
      signal: this.abortController ? this.abortController.signal : undefined,
    })
      .then(function (response) {
        if (!response.ok || !response.body) throw new Error("stream failed");
        return self.readStream(response.body, assistantNode, assistantId, runId, generation, threadId);
      })
      .then(function (result) {
        if (!self.isActiveRun(runId, generation)) return;
        assistantNode.classList.remove("is-pending");
        if (!result.started || result.terminalCount !== 1 || !result.terminal) {
          result.hadError = true;
          self.showRunError(assistantNode);
        } else if (!result.hadError && result.text) {
          renderSafeMarkdown(assistantNode.querySelector(".native-ai-ui-bubble"), result.text);
          self.messages.push({
            id: assistantId,
            role: "assistant",
            content: result.text,
            created_at_display: self.currentAssistant && self.currentAssistant.time ? self.currentAssistant.time : currentTimeLabel(),
          });
          self.setStatus("");
        } else if (!result.hadError && !result.text) {
          self.showRunError(assistantNode);
        }
        self.finishRun(generation);
      })
      .catch(function (error) {
        if (!self.isActiveRun(runId, generation)) return;
        if (error && error.name === "AbortError") {
          if (self.runState) self.runState.aborted = true;
          assistantNode.classList.remove("is-pending");
          self.finishRun(generation);
          return;
        }
        assistantNode.classList.remove("is-pending");
        self.showRunError(assistantNode);
        self.finishRun(generation);
      });
  };

  NativeAiSidebar.prototype.finishRun = function (generation) {
    if (generation && generation !== this.generation) return;
    this.activeRunId = "";
    this.activeThreadId = "";
    this.runState = null;
    this.currentAssistant = null;
    this.pendingFiles = [];
    this.revokePreviewUrls();
    this.setPending(false);
    if (this.fileInput) this.fileInput.value = "";
    if (this.isWorkordersChatExpanded() && this.input) {
      this.input.focus();
    } else {
      document.dispatchEvent(new CustomEvent("workorders:ai-run-finished", {
        detail: { error: this.runHadError },
      }));
    }
  };

  NativeAiSidebar.prototype.readStream = function (body, assistantNode, assistantId, runId, generation, threadId) {
    var self = this;
    var reader = body.getReader();
    var decoder = new TextDecoder();
    var buffer = "";
    var result = { text: "", hadError: false, started: false, terminal: "", terminalCount: 0 };

    function processBlock(block) {
      if (!block.trim()) return;
      var data = eventDataFromBlock(block);
      if (!data || data === "[DONE]") return;
      try {
        self.handleEvent(JSON.parse(data), assistantNode, assistantId, result, runId, generation, threadId);
      } catch (error) {
        // Unknown or malformed stream chunks are ignored; transport errors still fail the run.
      }
    }

    function read() {
      return reader.read().then(function (chunk) {
        if (chunk.done) {
          buffer += decoder.decode();
          if (buffer) processBlock(buffer);
          if (!result.terminal) result.hadError = true;
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

  NativeAiSidebar.prototype.handleEvent = function (event, assistantNode, assistantId, result, runId, generation, threadId) {
    if (!event || !event.type) return;
    if (!this.isActiveRun(runId, generation)) return;
    var eventRunId = Object.prototype.hasOwnProperty.call(event, "runId") ? event.runId :
      (Object.prototype.hasOwnProperty.call(event, "run_id") ? event.run_id : null);
    var eventThreadId = Object.prototype.hasOwnProperty.call(event, "threadId") ? event.threadId :
      (Object.prototype.hasOwnProperty.call(event, "thread_id") ? event.thread_id : null);
    if ((eventRunId != null && String(eventRunId) !== String(runId)) ||
        (eventThreadId != null && String(eventThreadId) !== String(threadId))) return;
    if (event.type === "RUN_STARTED") {
      if (this.runState.started) return;
      this.runState.started = true;
      result.started = true;
      this.setStatus("ИИ обрабатывает запрос...");
      return;
    }
    if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR") {
      if (!this.runState.started) return;
      if (this.runState.terminal) {
        this.runState.terminalCount += 1;
        result.terminalCount = this.runState.terminalCount;
        result.hadError = true;
        return;
      }
      this.runState.terminal = event.type;
      this.runState.terminalCount += 1;
      result.terminal = event.type;
      result.terminalCount = this.runState.terminalCount;
      if (event.type === "RUN_ERROR") {
        result.hadError = true;
        this.runHadError = true;
        this.showRunError(assistantNode);
      } else if (!this.runHadError) this.setStatus("");
      return;
    }
    switch (event.type) {
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
    if (node) {
      node.classList.remove("is-pending");
      if (this.currentAssistant && this.currentAssistant.id === messageId) {
        var bubble = node.querySelector(".native-ai-ui-bubble");
        if (bubble) renderSafeMarkdown(bubble, this.currentAssistant.text);
      }
    }
  };

  NativeAiSidebar.prototype.showRunError = function (assistantNode) {
    this.runHadError = true;
    var message = AI_CHAT_UNAVAILABLE_MESSAGE;
    if (assistantNode) {
      assistantNode.classList.remove("is-pending");
      assistantNode.classList.add("is-error");
      var bubble = assistantNode.querySelector(".native-ai-ui-bubble");
      if (bubble) bubble.textContent = message;
    }
    this.setStatus(message, "error");
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
    var commandId = safe.command_id;
    var key = String(this.activeRunId || "no-run") + ":" + (commandId ? String(commandId) : JSON.stringify(safe));
    if (this.executedCommands.has(key)) return;
    this.rememberExecutedCommand(key);
    window.LocalBusinessRightPanel.open(safe).catch(function () {});
  };

  function boot() {
    var roots = Array.prototype.slice.call(document.querySelectorAll("[data-native-ai-root]"));
    var legacyRoot = document.getElementById("native-ai-sidebar-root");
    if (legacyRoot && roots.indexOf(legacyRoot) === -1) roots.push(legacyRoot);
    roots.forEach(function (root) {
      if (root.dataset.nativeAiReady === "1") return;
      root.dataset.nativeAiReady = "1";
      var configUrl = root.dataset.configUrl;
      var initialConfig = {};
      if (root.dataset.config) {
        try { initialConfig = JSON.parse(root.dataset.config); } catch (error) { initialConfig = {}; }
      }
      var configPromise = configUrl
        ? fetch(configUrl, {
          method: "GET",
          credentials: "same-origin",
          headers: { "X-Requested-With": "XMLHttpRequest" },
        }).then(function (response) {
          if (!response.ok) throw new Error("config failed");
          return response.json();
        })
        : Promise.resolve(initialConfig);
      configPromise
      .then(function (response) {
        var config = response || {};
        if (!config.surface) config.surface = root.dataset.surface || "sidebar";
        try {
          new NativeAiSidebar(root, config);
        } catch (err) {
          root.innerHTML = '<div class="native-ai-ui-error">' + escapeHtml(AI_CHAT_UNAVAILABLE_MESSAGE) + '</div>';
          if (window.console && console.error) console.error("NativeAiSidebar init failed", err);
        }
      })
      .catch(function (err) {
        root.innerHTML = '<div class="native-ai-ui-error">' + escapeHtml(AI_CHAT_UNAVAILABLE_MESSAGE) + '</div>';
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot, { once: true });
  } else {
    boot();
  }
})();
