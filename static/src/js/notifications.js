(function () {
  const config = window.__notificationsConfig || {};
  if (!config.authenticated) return;

  const root = document.getElementById("notification-center");
  const toggle = document.getElementById("notification-toggle");
  const dropdown = document.getElementById("notification-dropdown");
  const list = document.getElementById("notification-list");
  const count = document.getElementById("notification-count");
  const statusText = document.getElementById("notification-status-text");
  const enableButton = document.getElementById("notification-enable-button");
  const disableButton = document.getElementById("notification-disable-button");
  const permissionText = document.getElementById("notification-permission-text");
  const pageList = document.getElementById("notifications-page-list");
  const pageEnableButton = document.getElementById("notifications-page-enable-button");
  if (!root || !toggle || !dropdown || !list) return;

  const storagePrefix = `localBusiness.notifications.${config.userId || "anonymous"}`;
  const cursorKey = `${storagePrefix}.cursor`;
  const clientKey = `${storagePrefix}.browserClient`;
  const shownPrefix = `${storagePrefix}.shown.`;
  const channel = "BroadcastChannel" in window ? new BroadcastChannel("local-business-notifications") : null;
  const state = {
    cursor: Number(localStorage.getItem(cursorKey) || 0),
    items: new Map(),
    browserEnabled: false,
    initialSync: true,
    retryMs: Number(config.pollIntervalMs || 30000),
    timer: null
  };

  function csrfToken() {
    return config.csrfToken || "";
  }

  function safeUrl(url) {
    if (typeof url !== "string" || !url.startsWith("/") || url.startsWith("//")) return "/";
    return url;
  }

  function clientFingerprint() {
    let value = localStorage.getItem(clientKey);
    if (!value) {
      value = crypto.randomUUID ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
      localStorage.setItem(clientKey, value);
    }
    return value;
  }

  async function fetchJson(url, options) {
    const requestOptions = options || {};
    const response = await fetch(url, {
      credentials: "same-origin",
      ...requestOptions,
      headers: {
        "Accept": "application/json",
        "Content-Type": "application/json",
        "X-CSRFToken": csrfToken(),
        ...(requestOptions.headers || {})
      }
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  }

  function updateCounts(unreadCount, newCount) {
    const unread = Number(unreadCount || 0);
    count.textContent = String(unread > 99 ? "99+" : unread);
    count.hidden = unread === 0;
    if (statusText) {
      statusText.textContent = unread === 0 ? "Новых уведомлений нет." : `Непрочитанных: ${unread}`;
    }
    toggle.classList.toggle("has-notifications", unread > 0 || Number(newCount || 0) > 0);
  }

  function itemHtml(item) {
    const row = document.createElement("article");
    row.className = `notification-item notification-item-${item.state || "new"}`;
    row.dataset.notificationId = String(item.id);

    const link = document.createElement("a");
    link.className = "notification-item-main";
    link.href = safeUrl(item.target_url);
    link.dataset.notificationOpen = String(item.id);

    const title = document.createElement("strong");
    title.textContent = item.title || "Уведомление";
    const body = document.createElement("span");
    body.textContent = item.body || "Открыть в портале";
    const meta = document.createElement("small");
    meta.textContent = formatDate(item.created_at);
    link.append(title, body, meta);

    const actions = document.createElement("div");
    actions.className = "notification-item-actions";
    const read = document.createElement("button");
    read.type = "button";
    read.className = "notification-action-button";
    read.textContent = "Прочитано";
    read.dataset.notificationRead = String(item.id);
    const close = document.createElement("button");
    close.type = "button";
    close.className = "notification-action-button";
    close.textContent = "Скрыть";
    close.dataset.notificationDismiss = String(item.id);
    actions.append(read, close);

    row.append(link, actions);
    return row;
  }

  function formatDate(value) {
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleString("ru-RU", {
      day: "2-digit",
      month: "2-digit",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function render() {
    const items = Array.from(state.items.values())
      .filter((item) => item.state !== "dismissed")
      .sort((a, b) => Number(b.id) - Number(a.id))
      .slice(0, 30);
    renderInto(list, items);
    if (pageList) renderInto(pageList, items);
  }

  function renderInto(container, items) {
    container.replaceChildren();
    if (!items.length) {
      const empty = document.createElement("div");
      empty.className = "notification-empty";
      empty.textContent = "Новых уведомлений нет.";
      container.appendChild(empty);
      return;
    }
    items.forEach((item) => container.appendChild(itemHtml(item)));
  }

  function syncPreferences(preferences) {
    state.browserEnabled = Boolean(preferences && preferences.browser && preferences.browser.enabled);
    updatePermissionUi();
  }

  function updatePermissionUi() {
    const supported = "Notification" in window;
    const permission = supported ? Notification.permission : "unsupported";
    const enabled = supported && state.browserEnabled && permission === "granted";
    if (permissionText) {
      if (!supported) {
        permissionText.textContent = "Этот браузер не поддерживает системные уведомления.";
      } else if (enabled) {
        permissionText.textContent = "Браузерные уведомления включены для этого устройства.";
      } else if (permission === "denied") {
        permissionText.textContent = "Браузер запретил уведомления. Изменить это можно в настройках браузера или системы.";
      } else {
        permissionText.textContent = "Браузерные уведомления приходят, пока портал открыт во вкладке или PWA-окне.";
      }
    }
    if (enableButton) enableButton.hidden = !supported || enabled || permission === "denied";
    if (disableButton) disableButton.hidden = !supported || !enabled;
    if (pageEnableButton) pageEnableButton.hidden = !supported || enabled || permission === "denied";
  }

  async function poll() {
    const url = new URL(config.feedUrl, window.location.origin);
    if (state.cursor > 0) url.searchParams.set("cursor", String(state.cursor));
    try {
      const payload = await fetchJson(url.toString(), { method: "GET", headers: { "Content-Type": "application/json" } });
      syncPreferences(payload.preferences);
      const items = Array.isArray(payload.items) ? payload.items : [];
      items.forEach((item) => state.items.set(Number(item.id), item));
      if (Number(payload.cursor || 0) > state.cursor) {
        state.cursor = Number(payload.cursor);
        localStorage.setItem(cursorKey, String(state.cursor));
      }
      updateCounts(payload.unread_count, payload.new_count);
      render();
      if (!state.initialSync) {
        items.forEach((item) => maybeShowBrowserNotification(item));
      }
      state.initialSync = false;
      state.retryMs = Number(config.pollIntervalMs || 30000);
    } catch (error) {
      state.retryMs = Math.min(Math.max(state.retryMs * 2, 30000), 120000);
    } finally {
      state.timer = window.setTimeout(poll, state.retryMs);
    }
  }

  function claimNotification(item) {
    const key = `${shownPrefix}${item.id}`;
    if (localStorage.getItem(key)) return false;
    localStorage.setItem(key, String(Date.now()));
    if (channel) channel.postMessage({ type: "shown", id: item.id });
    return true;
  }

  function maybeShowBrowserNotification(item) {
    if (!("Notification" in window)) return;
    if (!state.browserEnabled || Notification.permission !== "granted") return;
    if (!item || item.state === "dismissed" || !claimNotification(item)) return;
    const notification = new Notification(item.title || "Уведомление", {
      body: item.body || "Открыть в портале",
      tag: item.event_id || String(item.id),
      data: { url: safeUrl(item.target_url), id: item.id }
    });
    notification.onclick = () => {
      window.focus();
      markRead([item.id]).finally(() => {
        window.location.href = safeUrl(item.target_url);
      });
    };
  }

  async function markSeen(ids) {
    if (!ids.length) return;
    const payload = await fetchJson(config.markSeenUrl, {
      method: "POST",
      body: JSON.stringify({ ids })
    });
    ids.forEach((id) => {
      const item = state.items.get(Number(id));
      if (item && item.state === "new") item.state = "seen";
    });
    updateCounts(payload.unread_count, payload.new_count);
    render();
  }

  async function markRead(ids) {
    if (!ids.length) return;
    const payload = await fetchJson(config.markReadUrl, {
      method: "POST",
      body: JSON.stringify({ ids })
    });
    ids.forEach((id) => {
      const item = state.items.get(Number(id));
      if (item) item.state = "read";
    });
    updateCounts(payload.unread_count, payload.new_count);
    render();
  }

  async function dismissItems(ids) {
    if (!ids.length) return;
    const payload = await fetchJson(config.dismissUrl, {
      method: "POST",
      body: JSON.stringify({ ids })
    });
    ids.forEach((id) => {
      const item = state.items.get(Number(id));
      if (item) item.state = "dismissed";
    });
    updateCounts(payload.unread_count, payload.new_count);
    render();
  }

  async function registerBrowser(permission, enabled) {
    const payload = await fetchJson(config.browserClientUrl, {
      method: "POST",
      body: JSON.stringify({
        fingerprint: clientFingerprint(),
        permission,
        enabled
      })
    });
    state.browserEnabled = Boolean(payload.enabled);
    updatePermissionUi();
  }

  async function enableBrowserNotifications() {
    if (!("Notification" in window)) return;
    const permission = await Notification.requestPermission();
    await registerBrowser(permission, permission === "granted");
  }

  async function disableBrowserNotifications() {
    await fetchJson(config.preferencesUrl, {
      method: "POST",
      body: JSON.stringify({ browser: { enabled: false } })
    });
    await registerBrowser(Notification.permission || "default", false);
    state.browserEnabled = false;
    updatePermissionUi();
  }

  function openDropdown() {
    dropdown.hidden = false;
    toggle.setAttribute("aria-expanded", "true");
    const ids = Array.from(state.items.values())
      .filter((item) => item.state === "new")
      .map((item) => item.id);
    markSeen(ids).catch(() => undefined);
  }

  function closeDropdown() {
    dropdown.hidden = true;
    toggle.setAttribute("aria-expanded", "false");
  }

  toggle.addEventListener("click", (event) => {
    event.stopPropagation();
    if (dropdown.hidden) openDropdown();
    else closeDropdown();
  });
  document.addEventListener("click", (event) => {
    if (!dropdown.hidden && !event.target.closest("#notification-center")) closeDropdown();
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") closeDropdown();
  });
  document.addEventListener("click", (event) => {
    const readId = event.target.closest("[data-notification-read]")?.dataset.notificationRead;
    const dismissId = event.target.closest("[data-notification-dismiss]")?.dataset.notificationDismiss;
    const openId = event.target.closest("[data-notification-open]")?.dataset.notificationOpen;
    if (readId) {
      event.preventDefault();
      markRead([Number(readId)]).catch(() => undefined);
    } else if (dismissId) {
      event.preventDefault();
      dismissItems([Number(dismissId)]).catch(() => undefined);
    } else if (openId) {
      markRead([Number(openId)]).catch(() => undefined);
    }
  });
  if (enableButton) enableButton.addEventListener("click", () => enableBrowserNotifications().catch(() => undefined));
  if (pageEnableButton) pageEnableButton.addEventListener("click", () => enableBrowserNotifications().catch(() => undefined));
  if (disableButton) disableButton.addEventListener("click", () => disableBrowserNotifications().catch(() => undefined));
  if (channel) {
    channel.addEventListener("message", (event) => {
      if (event.data && event.data.type === "shown") {
        localStorage.setItem(`${shownPrefix}${event.data.id}`, String(Date.now()));
      }
    });
  }

  updatePermissionUi();
  poll();
})();
