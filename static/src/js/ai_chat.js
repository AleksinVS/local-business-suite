/* AI Chat — extracted from chat_detail.html */
(function() {
  'use strict';

  var config = window.__chatConfig;
  if (!config) return;

  // DOMPurify configuration
  DOMPurify.setConfig({
    ALLOWED_TAGS: [
      'p', 'br', 'b', 'strong', 'i', 'em', 'u', 's', 'a', 'span', 'sub', 'sup',
      'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
      'ul', 'ol', 'li', 'dl', 'dt', 'dd',
      'table', 'thead', 'tbody', 'tfoot', 'tr', 'th', 'td', 'caption', 'colgroup', 'col',
      'pre', 'code', 'blockquote', 'hr',
      'details', 'summary', 'button', 'input', 'select', 'option', 'label',
      'img', 'div', 'section', 'article', 'aside', 'header', 'footer', 'nav',
      'figure', 'figcaption', 'mark', 'abbr', 'kbd', 'var', 'samp',
    ],
    ALLOWED_ATTR: [
      'href', 'target', 'rel', 'class', 'id', 'title', 'alt',
      'src', 'width', 'height', 'colspan', 'rowspan',
      'type', 'value', 'name', 'disabled', 'placeholder', 'checked', 'selected',
      'data-*',
    ],
    ALLOW_DATA_ATTR: true,
    FORBID_TAGS: ['script', 'style', 'iframe', 'object', 'embed', 'form', 'math', 'svg'],
    FORBID_ATTR: ['onerror', 'onload', 'onclick', 'onmouseover', 'onfocus', 'onblur'],
  });

  // Marked config
  marked.setOptions({ breaks: true, gfm: true });

  function renderAssistantContent(rawContent) {
    if (!rawContent) return '';
    var hasHtmlTags = /<[a-zA-Z][^>]*>/.test(rawContent);
    if (hasHtmlTags) {
      return DOMPurify.sanitize(rawContent);
    }
    var hasMarkdown = /^#{1,6}\s|^\*\s|^\-\s|^\d+\.\s|\*\*[^*]+\*\*|`[^`]+`|^\>|^\|/m.test(rawContent);
    if (hasMarkdown) {
      return DOMPurify.sanitize(marked.parse(rawContent));
    }
    return rawContent.replace(/\n/g, '<br>');
  }

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
  }

  // Don't abort streams on visibility change — Django saves to DB
  document.addEventListener('visibilitychange', function() {
    // intentionally empty — stream continues in background
  });

  document.addEventListener('DOMContentLoaded', function() {
    var chatForm = document.getElementById('ai-chat-form');
    var messageList = document.getElementById('ai-message-list');
    var promptInput = document.getElementById('ai-prompt-input');
    var sendButton = document.getElementById('ai-send-button');
    var fileInput = document.getElementById('chat-file-upload');
    var previewContainer = document.getElementById('attachment-preview-container');
    var dropOverlay = document.getElementById('drop-overlay');

    var isSubmitting = false;
    var currentModelId = config.currentModelId;
    var modelUpdateUrl = config.modelUpdateUrl;
    var streamUrl = config.streamUrl;
    var chatDeleteUrl = config.chatDeleteUrl;
    var chatDeleteByIdPrefix = config.chatDeleteByIdPrefix;
    var chatDeleteByIdSuffix = config.chatDeleteByIdSuffix;
    var chatIndexUrl = config.chatIndexUrl;
    var csrfToken = config.csrfToken;
    var predefinedCommands = JSON.parse(document.getElementById('predefined-commands-data')?.textContent || '[]');
    var customCommands = JSON.parse(document.getElementById('custom-commands-data')?.textContent || '[]');

    function commandName(command) {
      return String(command.name || command.shortcut || '').replace(/^\/+/, '');
    }

    function commandDescription(command) {
      return String(command.description || command.template || '');
    }

    function allCommands() {
      return predefinedCommands.concat(customCommands).filter(function(command) {
        return commandName(command);
      });
    }

    function appendCommandItem(container, command) {
      var item = document.createElement('button');
      item.type = 'button';
      item.className = 'w-full flex gap-3 px-3 py-2 rounded-lg text-left hover:bg-blue-50 transition-colors';
      item.addEventListener('click', function() {
        window.insertCommand(commandName(command));
        var menu = document.getElementById('command-menu-dropdown');
        var autocomplete = document.getElementById('command-autocomplete');
        if (menu) menu.classList.add('hidden');
        if (autocomplete) autocomplete.classList.add('hidden');
      });

      var name = document.createElement('span');
      name.className = 'font-mono text-blue-600 font-semibold text-sm whitespace-nowrap';
      name.textContent = '/' + commandName(command);

      var description = document.createElement('span');
      description.className = 'text-sm text-gray-600 truncate';
      description.textContent = commandDescription(command);

      item.append(name, description);
      container.appendChild(item);
    }

    function renderCommandList(container, query) {
      if (!container) return;
      container.replaceChildren();
      var normalized = String(query || '').replace(/^\/+/, '').toLowerCase();
      var matches = allCommands().filter(function(command) {
        return commandName(command).toLowerCase().includes(normalized);
      });
      if (!matches.length) {
        var empty = document.createElement('div');
        empty.className = 'px-3 py-2 text-sm text-gray-400';
        empty.textContent = 'Команды не найдены';
        container.appendChild(empty);
        return;
      }
      matches.forEach(function(command) { appendCommandItem(container, command); });
    }

    var commandMenuBtn = document.getElementById('command-menu-btn');
    var commandMenu = document.getElementById('command-menu-dropdown');
    var commandMenuList = document.getElementById('command-menu-list');
    var commandSearchInput = document.getElementById('command-search-input');
    var autocomplete = document.getElementById('command-autocomplete');
    var autocompleteList = document.getElementById('autocomplete-list');

    if (commandMenuBtn && commandMenu) {
      commandMenuBtn.addEventListener('click', function() {
        commandMenu.classList.toggle('hidden');
        renderCommandList(commandMenuList, commandSearchInput ? commandSearchInput.value : '');
        if (commandSearchInput) commandSearchInput.focus();
      });
    }
    if (commandSearchInput) {
      commandSearchInput.addEventListener('input', function() {
        renderCommandList(commandMenuList, commandSearchInput.value);
      });
    }

    // Model selector
    var modelSelect = document.getElementById('ai-model-select');
    var modelIdInput = document.getElementById('ai-model-id-input');

    if (modelSelect) {
      modelSelect.addEventListener('change', function() {
        var newModelId = this.value;
        fetch(modelUpdateUrl, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
          body: JSON.stringify({ model_id: newModelId }),
        })
        .then(function(response) { return response.json(); })
        .then(function(data) {
          if (data.status === 'ok') {
            currentModelId = newModelId;
            if (modelIdInput) modelIdInput.value = newModelId;
          } else {
            alert('Ошибка смены модели: ' + data.error);
            modelSelect.value = currentModelId;
          }
        })
        .catch(function() {
          alert('Ошибка соединения при смене модели.');
          modelSelect.value = currentModelId;
        });
      });
    }

    // Render server-rendered assistant messages
    document.querySelectorAll('.assistant-content').forEach(function(el) {
      var scriptEl = el.nextElementSibling;
      if (scriptEl && scriptEl.classList.contains('assistant-raw-content')) {
        var raw = JSON.parse(scriptEl.textContent);
        el.innerHTML = renderAssistantContent(raw);
        scriptEl.remove();
      }
    });

    // Auto-resize textarea
    promptInput.addEventListener('input', function() {
      this.style.height = 'auto';
      this.style.height = (this.scrollHeight) + 'px';
      if (this.value === '') this.style.height = '44px';
      if (autocomplete && autocompleteList && this.value.startsWith('/')) {
        autocomplete.classList.remove('hidden');
        renderCommandList(autocompleteList, this.value);
      } else if (autocomplete) {
        autocomplete.classList.add('hidden');
      }
    });

    // Enter to submit
    promptInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        if (isSubmitting) return;
        if (this.value.trim() || fileInput.files.length > 0) {
          if (typeof chatForm.requestSubmit === 'function') {
            chatForm.requestSubmit(sendButton);
          } else {
            sendButton.click();
          }
        }
      }
    });

    // Drag-and-drop
    var dragCounter = 0;

    messageList.addEventListener('dragenter', function(e) {
      e.preventDefault();
      dragCounter++;
      dropOverlay.classList.remove('hidden');
      dropOverlay.classList.add('flex');
    });

    messageList.addEventListener('dragover', function(e) {
      e.preventDefault();
    });

    messageList.addEventListener('dragleave', function() {
      dragCounter--;
      if (dragCounter === 0) {
        dropOverlay.classList.add('hidden');
        dropOverlay.classList.remove('flex');
      }
    });

    messageList.addEventListener('drop', function(e) {
      e.preventDefault();
      dragCounter = 0;
      dropOverlay.classList.add('hidden');
      dropOverlay.classList.remove('flex');

      var files = Array.from(e.dataTransfer.files);
      if (files.length === 0) return;

      selectedFiles = selectedFiles.concat(files);
      var dt = new DataTransfer();
      selectedFiles.forEach(function(f) { dt.items.add(f); });
      fileInput.files = dt.files;
      renderPreviews();
    });

    // File Preview Logic
    var selectedFiles = [];

    fileInput.addEventListener('change', function(e) {
      selectedFiles = Array.from(e.target.files);
      renderPreviews();
    });

    function renderPreviews() {
      previewContainer.innerHTML = '';
      if (selectedFiles.length > 0) {
        previewContainer.classList.remove('hidden');
        selectedFiles.forEach(function(file, index) {
          var isImage = file.type.startsWith('image/');
          var card = document.createElement('div');
          card.className = "flex items-center gap-2 bg-white border border-gray-200 rounded-lg p-2 shadow-sm min-w-[150px] max-w-[200px] relative group";

          var removeBtn = document.createElement('button');
          removeBtn.type = 'button';
          removeBtn.className = "absolute -top-2 -right-2 bg-red-500 text-white rounded-full p-0.5 opacity-0 group-hover:opacity-100 transition-opacity shadow-md";
          removeBtn.innerHTML = '<svg class="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"></path></svg>';
          removeBtn.onclick = (function(idx) {
            return function() {
              selectedFiles.splice(idx, 1);
              var dt = new DataTransfer();
              selectedFiles.forEach(function(f) { dt.items.add(f); });
              fileInput.files = dt.files;
              renderPreviews();
            };
          })(index);

          if (isImage) {
            var img = document.createElement('img');
            img.src = URL.createObjectURL(file);
            img.className = "w-8 h-8 object-cover rounded";
            card.appendChild(img);
          } else {
            var icon = document.createElement('div');
            icon.className = "bg-blue-100 text-blue-600 rounded p-1.5";
            icon.innerHTML = '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>';
            card.appendChild(icon);
          }

          var textDiv = document.createElement('div');
          textDiv.className = "overflow-hidden";
          textDiv.innerHTML = '<div class="text-xs font-medium text-gray-700 truncate">' + escapeHtml(file.name) + '</div>'
            + '<div class="text-[10px] text-gray-400">' + (file.size / 1024 / 1024).toFixed(2) + ' MB</div>';

          card.appendChild(textDiv);
          card.appendChild(removeBtn);
          previewContainer.appendChild(card);
        });
      } else {
        previewContainer.classList.add('hidden');
      }
    }

    // Typing indicator (shown while message is being saved)
    var typingIndicatorId = 'typing-indicator';

    function showTypingIndicator() {
      var existing = document.getElementById(typingIndicatorId);
      if (existing) return;
      var html = '<div class="flex justify-start" id="' + typingIndicatorId + '">'
        + '<div class="flex flex-col items-start gap-1 max-w-[85%] md:max-w-[70%]">'
        + '<div class="flex items-center space-x-2 mb-1">'
        + '<span class="text-sm font-semibold text-gray-900">Ассистент</span>'
        + '</div>'
        + '<div class="bg-white border border-gray-200 text-gray-400 rounded-r-2xl rounded-bl-2xl px-5 py-3 shadow-md text-[15px] leading-relaxed">'
        + '<span class="flex gap-1 items-center h-4">'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"></span>'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay:0.1s"></span>'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay:0.2s"></span>'
        + '</span></div></div></div>';
      messageList.insertAdjacentHTML('beforeend', html);
      messageList.scrollTop = messageList.scrollHeight;
    }

    function removeTypingIndicator() {
      var el = document.getElementById(typingIndicatorId);
      if (el) el.remove();
    }

    // Form Submission
    chatForm.addEventListener('submit', function(e) {
      e.preventDefault();
      if (isSubmitting) return;

      var prompt = promptInput.value.trim();
      if (!prompt && selectedFiles.length === 0) return;

      isSubmitting = true;
      var formData = new FormData(chatForm);

      promptInput.disabled = true;
      sendButton.disabled = true;
      fileInput.disabled = true;
      promptInput.value = '';
      promptInput.style.height = '44px';

      var userMsgId = 'user-msg-' + Date.now();
      var attachmentsHtml = '';

      if (selectedFiles.length > 0) {
        attachmentsHtml = '<div class="grid gap-2 grid-cols-1 sm:grid-cols-2 mb-2 w-full">';
        selectedFiles.forEach(function(file) {
          var isImage = file.type.startsWith('image/');
          if (isImage) {
            var tempUrl = URL.createObjectURL(file);
            attachmentsHtml += '<div class="block rounded-lg overflow-hidden border border-gray-200 shadow-sm opacity-70">'
              + '<img src="' + escapeHtml(tempUrl) + '" class="w-full h-32 object-cover">'
              + '</div>';
          } else {
            attachmentsHtml += '<div class="flex items-center p-3 bg-white rounded-lg border border-gray-200 shadow-sm opacity-70">'
              + '<div class="bg-blue-100 p-2 rounded-full mr-3 text-blue-600">'
              + '<svg class="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"></path></svg>'
              + '</div>'
              + '<div class="overflow-hidden">'
              + '<div class="text-sm font-medium text-gray-900 truncate">' + escapeHtml(file.name) + '</div>'
              + '<div class="text-xs text-gray-500">Загрузка...</div>'
              + '</div></div>';
          }
        });
        attachmentsHtml += '</div>';
      }

      var userMsgHtml = '<div class="flex justify-end" id="' + userMsgId + '">'
        + '<div class="flex flex-col items-end gap-1 max-w-[85%] md:max-w-[70%]">'
        + '<div class="flex items-center space-x-2 rtl:space-x-reverse mb-1">'
        + '<span class="text-sm font-semibold text-gray-900">Вы</span>'
        + '<span class="text-xs font-normal text-gray-500">только что</span>'
        + '</div>'
        + attachmentsHtml
        + (prompt ? '<div class="bg-blue-600 text-white rounded-l-2xl rounded-br-2xl px-5 py-3 shadow-md text-[15px] leading-relaxed opacity-70 msg-pending">' + escapeHtml(prompt).replace(/\n/g, '<br>') + '</div>' : '')
        + '</div></div>';

      var emptyState = document.querySelector('#ai-message-list > .flex-col.items-center');
      if (emptyState) emptyState.remove();

      messageList.insertAdjacentHTML('beforeend', userMsgHtml);
      messageList.scrollTop = messageList.scrollHeight;

      selectedFiles = [];
      renderPreviews();

      // Show typing indicator immediately
      showTypingIndicator();

      fetch(chatForm.action, {
        method: 'POST',
        body: formData,
        headers: { 'X-Requested-With': 'XMLHttpRequest' }
      })
      .then(function(response) { return response.json(); })
      .then(function(data) {
        removeTypingIndicator();
        if (data.status === 'ok') {
          startSSE(prompt, data.message_id, userMsgId);
        } else {
          alert('Ошибка загрузки: ' + escapeHtml(data.error));
          resetInput();
        }
      })
      .catch(function(error) {
        removeTypingIndicator();
        console.error('Error:', error);
        alert('Ошибка соединения при отправке.');
        resetInput();
      });
    });

    function resetInput() {
      isSubmitting = false;
      promptInput.value = "";
      promptInput.style.height = '44px';
      fileInput.value = '';
      promptInput.disabled = false;
      sendButton.disabled = false;
      fileInput.disabled = false;
      promptInput.focus();
    }

    function startSSE(promptText, messageId, pendingUserMsgId) {
      var assistantMsgId = 'assistant-msg-' + Date.now();
      var assistantMsgHtml = '<div class="flex justify-start" id="' + assistantMsgId + '">'
        + '<div class="flex flex-col items-start gap-1 max-w-[85%] md:max-w-[70%]">'
        + '<div class="flex items-center space-x-2 mb-1">'
        + '<span class="text-sm font-semibold text-gray-900">Ассистент</span>'
        + '<span class="text-xs font-normal text-gray-500">печатает...</span>'
        + '</div>'
        + '<div class="bg-white border border-gray-200 text-gray-800 rounded-r-2xl rounded-bl-2xl px-5 py-3 shadow-md text-[15px] leading-relaxed prose max-w-none ai-streaming-content">'
        + '<span class="flex gap-1 items-center h-4">'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce"></span>'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.1s"></span>'
        + '<span class="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" style="animation-delay: 0.2s"></span>'
        + '</span></div></div></div>';

      messageList.insertAdjacentHTML('beforeend', assistantMsgHtml);
      var assistantContentDiv = document.querySelector('#' + assistantMsgId + ' .ai-streaming-content');
      messageList.scrollTop = messageList.scrollHeight;

      var accumulatedContent = "";
      var controller = new AbortController();
      var sseBuffer = "";
      var streamFinished = false;

      window._activeChatStream = {
        abort: function() { controller.abort(); },
        accumulatedContent: accumulatedContent,
        div: assistantContentDiv,
        msgId: assistantMsgId,
      };

      fetch(streamUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'X-CSRFToken': csrfToken,
          'X-Requested-With': 'XMLHttpRequest',
        },
        body: JSON.stringify({
          msg_id: messageId,
          prompt: promptText,
          model_id: currentModelId,
        }),
        signal: controller.signal,
      })
        .then(function(response) {
          if (!response.ok) {
            throw new Error('HTTP ' + response.status);
          }
          if (!response.body) {
            throw new Error('Потоковый ответ недоступен.');
          }
          var reader = response.body.getReader();
          var decoder = new TextDecoder();

          function read() {
            if (streamFinished) return;
            reader.read().then(function(result) {
              if (result.done) { finishStream(); return; }
              sseBuffer += decoder.decode(result.value, { stream: true });
              var lines = sseBuffer.split('\n');
              sseBuffer = lines.pop() || "";
              lines.forEach(function(line) {
                if (!line.startsWith('data: ')) return;
                var dataStr = line.slice(6);
                if (dataStr === '[DONE]') { finishStream(); return; }
                try {
                  var data = JSON.parse(dataStr);
                  if (data.content) {
                    accumulatedContent += data.content;
                    if (window._activeChatStream) window._activeChatStream.accumulatedContent = accumulatedContent;
                    assistantContentDiv.textContent = accumulatedContent;
                    messageList.scrollTop = messageList.scrollHeight;
                  }
                  if (data.error) {
                    finishWithError(data.message || data.error || 'AI-сервис вернул ошибку.', data);
                  }
                } catch (err) {
                  // Ignore non-JSON lines
                }
              });
              read();
            }).catch(function(err) {
              if (err.name !== 'AbortError') console.error('Stream read error:', err);
              if (err.name === 'AbortError') return;
              finishWithError('Соединение с AI-сервисом было прервано.', {});
            });
          }
          read();
        }).catch(function(err) {
          if (err.name !== 'AbortError') console.error('Fetch error:', err);
          if (err.name === 'AbortError') return;
          finishWithError('Не удалось получить ответ от AI-сервиса. Причина: ошибка соединения с сервером чата.', {});
        });

      function finishWithError(message, payload) {
        var details = payload && payload.request_id ? '<div class="mt-1 text-xs text-red-500">ID: ' + escapeHtml(payload.request_id) + '</div>' : '';
        accumulatedContent = "";
        assistantContentDiv.innerHTML = '<div class="rounded border border-red-200 bg-red-50 p-3 text-sm text-red-700">'
          + escapeHtml(message) + details + '</div>';
        try { controller.abort(); } catch (err) {}
        finishStream({ hasError: true });
      }

      function finishStream(options) {
        if (streamFinished) return;
        streamFinished = true;
        options = options || {};
        window._activeChatStream = null;
        if (accumulatedContent && !options.hasError) {
          assistantContentDiv.innerHTML = renderAssistantContent(accumulatedContent);
        }
        // Remove pending opacity from user message
        var pendingBubble = document.querySelector('#' + pendingUserMsgId + ' .msg-pending');
        if (pendingBubble) pendingBubble.classList.remove('opacity-70', 'msg-pending');
        resetInput();
        var timeEl = document.querySelector('#' + assistantMsgId + ' .text-gray-500');
        if (timeEl) timeEl.textContent = 'только что';
      }
    }
  });

  // Global functions for template onclick handlers
  window.insertCommand = function(command) {
    var input = document.getElementById('ai-prompt-input');
    if (!input) return;
    var normalized = String(command || '').replace(/^\/+/, '');
    input.value = '/' + normalized + ' ';
    input.focus();
    input.dispatchEvent(new Event('input', { bubbles: true }));
  };

  window.startEditTitle = function() {
    var display = document.getElementById('chat-title-display');
    var editRow = document.getElementById('chat-title-edit-row');
    var input = document.getElementById('chat-title-input');
    if (!display || !editRow || !input) return;
    display.classList.add('hidden');
    editRow.classList.remove('hidden');
    editRow.classList.add('flex');
    input.focus();
    input.select();
  };

  function updateTitleUI(title) {
    var titleText = document.getElementById('chat-title-text');
    var titleInput = document.getElementById('chat-title-input');
    if (titleText) titleText.textContent = title || 'Новый чат';
    if (titleInput) titleInput.value = title || 'Новый чат';
  }

  window.saveEditTitle = function() {
    var input = document.getElementById('chat-title-input');
    if (!input) return;
    var newTitle = input.value.trim();
    if (!newTitle) {
      input.classList.add('border-red-400');
      setTimeout(function() { input.classList.remove('border-red-400'); }, 1500);
      return;
    }
    fetch(window.__chatConfig.titleUpdateUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-CSRFToken': window.__chatConfig.csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
      },
      body: JSON.stringify({ title: newTitle }),
    }).then(function(response) { return response.json(); }).then(function(data) {
      if (data.status === 'ok') {
        updateTitleUI(data.title);
        window.cancelEditTitle();
      } else {
        alert('Ошибка: ' + (data.error || 'Не удалось переименовать'));
      }
    }).catch(function() { alert('Ошибка соединения.'); });
  };

  window.cancelEditTitle = function() {
    var display = document.getElementById('chat-title-display');
    var editRow = document.getElementById('chat-title-edit-row');
    if (!display || !editRow) return;
    editRow.classList.add('hidden');
    editRow.classList.remove('flex');
    display.classList.remove('hidden');
  };

  var titleInput = document.getElementById('chat-title-input');
  if (titleInput) {
    titleInput.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        e.preventDefault();
        window.saveEditTitle();
      }
      if (e.key === 'Escape') {
        e.preventDefault();
        window.cancelEditTitle();
      }
    });
  }

  window.deleteCurrentChat = function() {
    if (!confirm('Удалить этот чат? Это действие нельзя отменить.')) return;
    fetch(window.__chatConfig.chatDeleteUrl, {
      method: 'POST',
      headers: {
        'X-CSRFToken': window.__chatConfig.csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
      },
    }).then(function(response) { return response.json(); }).then(function(data) {
      if (data.status === 'ok') {
        window.location.href = window.__chatConfig.chatIndexUrl + '?new=1';
      } else {
        alert('Ошибка удаления чата.');
      }
    }).catch(function() { alert('Ошибка соединения.'); });
  };

  window.deleteChat = function(externalId, btn) {
    if (!confirm('Удалить этот чат?')) return;
    fetch(window.__chatConfig.chatDeleteByIdPrefix + externalId + window.__chatConfig.chatDeleteByIdSuffix, {
      method: 'POST',
      headers: {
        'X-CSRFToken': window.__chatConfig.csrfToken,
        'X-Requested-With': 'XMLHttpRequest',
      },
    }).then(function(response) { return response.json(); }).then(function(data) {
      if (data.status === 'ok') {
        var row = btn.closest('.group');
        if (row) row.remove();
        if (externalId === window.__chatConfig.currentSessionId) {
          window.location.href = window.__chatConfig.chatIndexUrl + '?new=1';
        }
      } else {
        alert('Ошибка удаления чата.');
      }
    }).catch(function() { alert('Ошибка соединения.'); });
  };
})();
