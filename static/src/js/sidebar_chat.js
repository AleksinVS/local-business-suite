(function () {
  "use strict";

  function escapeHtml(value) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(String(value || "")));
    return div.innerHTML;
  }

  function currentContext() {
    if (window.LocalBusinessPageContext && typeof window.LocalBusinessPageContext.getCurrent === "function") {
      return window.LocalBusinessPageContext.getCurrent();
    }
    return { window_id: "", context_version: 0, context_hint: "" };
  }

  function initSidebarChat(root) {
    if (!root || root.dataset.sidebarChatReady === "1") return;
    root.dataset.sidebarChatReady = "1";

    var form = root.querySelector("#sidebar-ai-chat-form");
    var list = root.querySelector("#sidebar-ai-message-list");
    var input = root.querySelector("#sidebar-ai-prompt-input");
    var send = root.querySelector("#sidebar-ai-send-button");
    var modelSelect = root.querySelector("#sidebar-ai-model-select");
    var modelInput = root.querySelector("#sidebar-ai-model-id-input");
    var windowInput = root.querySelector("#sidebar-ai-window-id");
    var versionInput = root.querySelector("#sidebar-ai-context-version");
    var hintInput = root.querySelector("#sidebar-ai-context-hint");
    var label = root.querySelector("#sidebar-context-label");
    var submitting = false;

    function applyContext() {
      var ctx = currentContext();
      if (windowInput) windowInput.value = ctx.window_id || "";
      if (versionInput) versionInput.value = ctx.context_version || "";
      if (hintInput) hintInput.value = ctx.context_hint || "";
      if (label) label.textContent = ctx.context_hint || "Контекст окна";
    }

    function scrollMessagesToBottom() {
      if (!list) return;
      list.scrollTop = list.scrollHeight;
    }

    function resizeInput() {
      if (!input) return;
      var maxHeight = parseInt(window.getComputedStyle(input).maxHeight, 10);
      if (!maxHeight || Number.isNaN(maxHeight)) maxHeight = 180;
      input.style.height = "auto";
      var nextHeight = Math.min(input.scrollHeight, maxHeight);
      input.style.height = nextHeight + "px";
      input.style.overflowY = input.scrollHeight > maxHeight ? "auto" : "hidden";
    }

    function appendMessage(role, content, pending) {
      var empty = list.querySelector(".sidebar-chat-empty");
      if (empty) empty.remove();
      var item = document.createElement("div");
      item.className = "sidebar-chat-message " + (role === "user" ? "is-user" : "is-assistant");
      if (pending) item.classList.add("is-pending");
      item.innerHTML = '<div class="sidebar-chat-message-meta"><span>'
        + (role === "user" ? "Вы" : "Ассистент")
        + '</span><time>только что</time></div><div class="sidebar-chat-bubble">'
        + escapeHtml(content).replace(/\n/g, "<br>")
        + "</div>";
      list.appendChild(item);
      scrollMessagesToBottom();
      return item;
    }

    function reset() {
      submitting = false;
      input.disabled = false;
      send.disabled = false;
      input.value = "";
      resizeInput();
      input.focus();
    }

    function startStream(prompt, messageId, pendingAssistant) {
      var buffer = "";
      fetch(form.dataset.streamUrl, {
        method: "POST",
        credentials: "same-origin",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": form.dataset.csrfToken || "",
          "X-Requested-With": "XMLHttpRequest",
        },
        body: JSON.stringify({
          msg_id: messageId,
          prompt: prompt,
          model_id: modelInput ? modelInput.value : "",
          surface: "sidebar",
          window_id: windowInput ? windowInput.value : "",
          context_version: versionInput ? versionInput.value : "",
          context_hint: hintInput ? hintInput.value : "",
        }),
      }).then(function (response) {
        if (!response.ok || !response.body) throw new Error("stream failed");
        var reader = response.body.getReader();
        var decoder = new TextDecoder();
        var sse = "";
        function read() {
          reader.read().then(function (result) {
            if (result.done) {
              finish();
              return;
            }
            sse += decoder.decode(result.value, { stream: true });
            var lines = sse.split("\n");
            sse = lines.pop() || "";
            lines.forEach(function (line) {
              if (!line.startsWith("data: ")) return;
              var raw = line.slice(6);
              if (raw === "[DONE]") {
                finish();
                return;
              }
              try {
                var payload = JSON.parse(raw);
                if (payload.content) {
                  buffer += payload.content;
                  pendingAssistant.querySelector(".sidebar-chat-bubble").textContent = buffer;
                  scrollMessagesToBottom();
                }
                if (payload.error) {
                  pendingAssistant.querySelector(".sidebar-chat-bubble").textContent = payload.message || "AI-сервис вернул ошибку.";
                }
              } catch (error) {}
            });
            read();
          }).catch(function () {
            pendingAssistant.querySelector(".sidebar-chat-bubble").textContent = "Не удалось получить ответ от AI-сервиса.";
            finish();
          });
        }
        read();
      }).catch(function () {
        pendingAssistant.querySelector(".sidebar-chat-bubble").textContent = "Не удалось отправить сообщение.";
        finish();
      });

      function finish() {
        pendingAssistant.classList.remove("is-pending");
        reset();
      }
    }

    if (modelSelect) {
      modelSelect.addEventListener("change", function () {
        var value = modelSelect.value;
        if (modelInput) modelInput.value = value;
        fetch(modelSelect.dataset.modelUpdateUrl, {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": form.dataset.csrfToken || "",
            "X-Requested-With": "XMLHttpRequest",
          },
          body: JSON.stringify({ model_id: value }),
        }).catch(function () {});
      });
    }

    input.addEventListener("input", resizeInput);
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      if (submitting) return;
      applyContext();
      var prompt = input.value.trim();
      if (!prompt) return;
      submitting = true;
      input.disabled = true;
      send.disabled = true;
      appendMessage("user", prompt, true).classList.remove("is-pending");
      var assistant = appendMessage("assistant", "Печатает...", true);

      var formData = new FormData(form);
      fetch(form.action, {
        method: "POST",
        credentials: "same-origin",
        body: formData,
        headers: { "X-Requested-With": "XMLHttpRequest" },
      }).then(function (response) {
        if (!response.ok) throw new Error("send failed");
        return response.json();
      }).then(function (payload) {
        if (payload.status !== "ok") throw new Error(payload.error || "send failed");
        startStream(prompt, payload.message_id, assistant);
      }).catch(function () {
        assistant.querySelector(".sidebar-chat-bubble").textContent = "Не удалось отправить сообщение.";
        reset();
      });
    });

    window.addEventListener("ai-context:update", applyContext);
    applyContext();
    resizeInput();
    scrollMessagesToBottom();
  }

  function initAll() {
    document.querySelectorAll("[data-sidebar-chat]").forEach(initSidebarChat);
  }

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
})();
