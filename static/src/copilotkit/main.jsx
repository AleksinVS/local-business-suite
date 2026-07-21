import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import { CopilotChat, CopilotKit, useAgent } from "@copilotkit/react-core/v2";
import "@copilotkit/react-core/v2/styles.css";

import "./copilotkit.css";

function runtimeCredentials(runtimeUrl) {
  if (!runtimeUrl || runtimeUrl.startsWith("/")) return "include";
  try {
    return new URL(runtimeUrl, window.location.origin).origin === window.location.origin
      ? "include"
      : "omit";
  } catch (error) {
    return "omit";
  }
}

function currentPageContext() {
  if (!window.LocalBusinessPageContext || typeof window.LocalBusinessPageContext.getCurrent !== "function") {
    return {};
  }
  const current = window.LocalBusinessPageContext.getCurrent();
  return current && current.envelope ? current : {};
}

function csrfToken() {
  return window.__pageContextConfig?.csrfToken || "";
}

function usePageContextSnapshot() {
  const [snapshot, setSnapshot] = useState(() => currentPageContext());

  useEffect(() => {
    const refresh = () => setSnapshot(currentPageContext());
    window.addEventListener("ai-context:update", refresh);
    refresh();
    return () => window.removeEventListener("ai-context:update", refresh);
  }, []);

  return snapshot;
}

function normalizeRightPanelCommand(command) {
  if (!command || command.type !== "open_right_panel") return null;
  const htmxUrl = String(command.htmx_url || command.url || "").trim();
  if (!htmxUrl || !htmxUrl.startsWith("/") || htmxUrl.startsWith("//")) return null;
  return {
    type: "open_right_panel",
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

function CommandBridge({ agentId }) {
  const { agent } = useAgent({ agentId });
  const executed = useRef(new Set());
  const commands = Array.isArray(agent.state?.localBusiness?.uiCommands)
    ? agent.state.localBusiness.uiCommands
    : Array.isArray(agent.state?.localBusinessUiCommands)
      ? agent.state.localBusinessUiCommands
      : [];
  const commandKey = JSON.stringify(commands);

  useEffect(() => {
    commands.forEach((command) => {
      const safe = normalizeRightPanelCommand(command);
      if (!safe || !window.LocalBusinessRightPanel) return;
      const key = JSON.stringify(safe);
      if (executed.current.has(key)) return;
      executed.current.add(key);
      window.LocalBusinessRightPanel.open(safe).catch(() => {});
    });
  }, [commandKey]);

  return null;
}

function CopilotKitIsland({ configUrl, newSessionUrl, fallbackRuntimeUrl, fallbackAgentId }) {
  const [config, setConfig] = useState(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pageContext = usePageContextSnapshot();

  const loadConfig = useMemo(() => {
    return () => fetch(configUrl, {
      method: "GET",
      credentials: "same-origin",
      headers: { "X-Requested-With": "XMLHttpRequest" },
    })
      .then((response) => {
        if (!response.ok) throw new Error("Не удалось получить настройки CopilotKit.");
        return response.json();
      })
      .then((payload) => {
        if (!payload.enabled) throw new Error(payload.error || "CopilotKit отключен.");
        setConfig(payload);
      })
      .catch((fetchError) => {
        setError(fetchError.message || "CopilotKit недоступен.");
      });
  }, [configUrl]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  function startNewChat() {
    if (!newSessionUrl || busy) return;
    setBusy(true);
    setError("");
    fetch(newSessionUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        "X-Requested-With": "XMLHttpRequest",
      },
      body: "{}",
    })
      .then((response) => {
        if (!response.ok) throw new Error("Не удалось начать новый чат.");
        return response.json();
      })
      .then((payload) => {
        if (!payload.enabled) throw new Error(payload.error || "AI UI отключен.");
        setConfig(payload);
      })
      .catch((fetchError) => {
        setError(fetchError.message || "Не удалось начать новый чат.");
      })
      .finally(() => setBusy(false));
  }

  const properties = useMemo(() => {
    if (!config) return {};
    return {
      ...(config.forwarded_props || {}),
      page_context: pageContext,
    };
  }, [config, pageContext]);

  if (error) return <div className="copilotkit-error">{error}</div>;
  if (!config) return <div className="sidebar-chat-loading">Загрузка чата...</div>;

  const runtimeUrl = config.runtime_url || fallbackRuntimeUrl;
  const agentId = config.agent_id || fallbackAgentId;
  const labels = config.labels || {};

  return (
    <div className="copilotkit-embed">
      <div className="copilotkit-toolbar">
        <button
          type="button"
          className="copilotkit-new-chat"
          onClick={startNewChat}
          disabled={busy}
          title="Новый чат"
          aria-label="Новый чат"
        >
          <span aria-hidden="true">+</span>
        </button>
        <span className="copilotkit-session-marker" aria-live="polite">
          {busy ? "Создание..." : ""}
        </span>
      </div>
      <CopilotKit
        key={config.thread_id}
        runtimeUrl={runtimeUrl}
        agent={agentId}
        threadId={config.thread_id}
        properties={properties}
        credentials={runtimeCredentials(runtimeUrl)}
        showDevConsole={false}
      >
        <CommandBridge agentId={agentId} />
        <CopilotChat
          labels={{
            title: labels.title || "ИИ-чат",
            initial: labels.initial || "Опишите задачу.",
            placeholder: labels.placeholder || "Сообщение...",
          }}
        />
      </CopilotKit>
    </div>
  );
}

function mount(rootNode) {
  const configUrl = rootNode.dataset.configUrl;
  if (!configUrl) {
    rootNode.replaceChildren();
    rootNode.append("Не задан URL настроек CopilotKit.");
    return;
  }

  createRoot(rootNode).render(
    <CopilotKitIsland
      configUrl={configUrl}
      newSessionUrl={rootNode.dataset.newSessionUrl || ""}
      fallbackRuntimeUrl={rootNode.dataset.runtimeUrl || "/copilotkit"}
      fallbackAgentId={rootNode.dataset.agentId || "local_business"}
    />,
  );
}

function boot() {
  const roots = [
    ...document.querySelectorAll('[data-copilotkit-root="true"]'),
    ...document.querySelectorAll("#copilotkit-sidebar-root"),
  ];
  const seen = new Set();
  roots.forEach((rootNode) => {
    if (!rootNode || seen.has(rootNode)) return;
    seen.add(rootNode);
    mount(rootNode);
  });
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", boot, { once: true });
} else {
  boot();
}
