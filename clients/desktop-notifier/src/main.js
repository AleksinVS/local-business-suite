import { appDataDir } from "@tauri-apps/api/path";
import { enable, disable, isEnabled } from "@tauri-apps/plugin-autostart";
import {
  isPermissionGranted,
  onAction,
  registerActionTypes,
  requestPermission,
  sendNotification
} from "@tauri-apps/plugin-notification";
import { openUrl } from "@tauri-apps/plugin-opener";
import { Stronghold } from "@tauri-apps/plugin-stronghold";
import "./styles.css";

const POLL_INTERVAL_MS = 30000;
const RETRY_MAX_MS = 120000;
const NOTIFICATION_ACTION_TYPE = "local-business-open-notification";
const STRONGHOLD_CLIENT = "desktop-notifier";
const STORE_KEYS = {
  portalUrl: "portal_url",
  deviceToken: "device_token",
  cursor: "cursor"
};

const els = {
  statusText: document.getElementById("status-text"),
  statusDot: document.getElementById("status-dot"),
  connectForm: document.getElementById("connect-form"),
  portalUrl: document.getElementById("portal-url"),
  linkCode: document.getElementById("link-code"),
  connectedActions: document.getElementById("connected-actions"),
  openPortal: document.getElementById("open-portal"),
  toggleAutostart: document.getElementById("toggle-autostart"),
  disconnect: document.getElementById("disconnect"),
  list: document.getElementById("notification-list")
};

const state = {
  stronghold: null,
  store: null,
  portalUrl: "",
  deviceToken: "",
  cursor: 0,
  retryMs: POLL_INTERVAL_MS,
  timer: null,
  items: new Map(),
  notificationPermissionChecked: false,
  notificationPermissionGranted: false
};

function setStatus(text, kind = "idle") {
  els.statusText.textContent = text;
  els.statusDot.dataset.status = kind;
}

function normalizePortalUrl(value) {
  const url = new URL(value);
  url.hash = "";
  url.search = "";
  return url.origin;
}

function portalUrl(path = "/") {
  const safePath = typeof path === "string" && path.startsWith("/") && !path.startsWith("//") ? path : "/";
  return `${state.portalUrl}${safePath}`;
}

function encode(value) {
  return Array.from(new TextEncoder().encode(value));
}

function decode(value) {
  if (!value) return "";
  return new TextDecoder().decode(new Uint8Array(value));
}

async function initStronghold() {
  const vaultPath = `${await appDataDir()}/notification-vault.hold`;
  const vaultPassword = "local-business-desktop-notifier-v1";
  state.stronghold = await Stronghold.load(vaultPath, vaultPassword);
  let client;
  try {
    client = await state.stronghold.loadClient(STRONGHOLD_CLIENT);
  } catch {
    client = await state.stronghold.createClient(STRONGHOLD_CLIENT);
  }
  state.store = client.getStore();
}

async function saveRecord(key, value) {
  await state.store.insert(key, encode(String(value || "")));
  await state.stronghold.save();
}

async function readRecord(key) {
  try {
    return decode(await state.store.get(key));
  } catch {
    return "";
  }
}

async function removeRecord(key) {
  try {
    await state.store.remove(key);
    await state.stronghold.save();
  } catch {
    return undefined;
  }
}

async function fetchJson(path, options = {}) {
  const response = await fetch(portalUrl(path), {
    ...options,
    headers: {
      Accept: "application/json",
      "Content-Type": "application/json",
      ...(state.deviceToken ? { Authorization: `Bearer ${state.deviceToken}` } : {}),
      ...(options.headers || {})
    }
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || `HTTP ${response.status}`);
  }
  return response.json();
}

async function exchangeCode(portal, code) {
  state.portalUrl = normalizePortalUrl(portal);
  const platform = navigator.userAgent.includes("Windows") ? "windows" : "linux";
  const payload = await fetchJson("/notifications/api/devices/exchange-code/", {
    method: "POST",
    body: JSON.stringify({
      code,
      device_name: navigator.userAgent.includes("Windows") ? "Windows tray client" : "Linux tray client",
      platform
    })
  });
  state.deviceToken = payload.device_token;
  state.cursor = 0;
  await saveRecord(STORE_KEYS.portalUrl, state.portalUrl);
  await saveRecord(STORE_KEYS.deviceToken, state.deviceToken);
  await saveRecord(STORE_KEYS.cursor, "0");
}

async function loadSavedConnection() {
  state.portalUrl = await readRecord(STORE_KEYS.portalUrl);
  state.deviceToken = await readRecord(STORE_KEYS.deviceToken);
  state.cursor = Number(await readRecord(STORE_KEYS.cursor)) || 0;
  els.portalUrl.value = state.portalUrl;
  updateConnectionUi();
}

function updateConnectionUi() {
  const connected = Boolean(state.portalUrl && state.deviceToken);
  els.connectForm.hidden = connected;
  els.connectedActions.hidden = !connected;
  setStatus(connected ? "Подключено. Ожидание уведомлений." : "Подключите приложение к порталу.", connected ? "ok" : "idle");
}

function renderList() {
  const items = Array.from(state.items.values()).sort((a, b) => Number(b.id) - Number(a.id)).slice(0, 20);
  els.list.replaceChildren();
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty";
    empty.textContent = "Уведомлений пока нет.";
    els.list.appendChild(empty);
    return;
  }
  for (const item of items) {
    const row = document.createElement("button");
    row.type = "button";
    row.className = "notification-row";
    row.dataset.id = String(item.id);
    row.innerHTML = `<strong></strong><span></span><small></small>`;
    row.querySelector("strong").textContent = item.title || "Уведомление";
    row.querySelector("span").textContent = item.body || "Открыть в портале";
    row.querySelector("small").textContent = new Date(item.created_at).toLocaleString("ru-RU");
    row.addEventListener("click", () => openNotification(item));
    els.list.appendChild(row);
  }
}

async function openNotification(item) {
  const id = Number(item.id);
  if (Number.isFinite(id) && id > 0) {
    await acknowledge([id], "read").catch(() => undefined);
  }
  await openUrl(portalUrl(item.target_url));
}

async function acknowledge(ids, action = "read") {
  if (!ids.length) return;
  await fetchJson("/notifications/api/devices/ack/", {
    method: "POST",
    body: JSON.stringify({ ids, action })
  });
}

function notificationIdFor(item) {
  const sourceId = Number(item.id);
  if (!Number.isFinite(sourceId) || sourceId <= 0) return 1;
  return (sourceId % 2147483646) + 1;
}

async function ensureNotificationPermission() {
  if (state.notificationPermissionChecked) return state.notificationPermissionGranted;
  let granted = await isPermissionGranted().catch(() => false);
  if (!granted) {
    const permission = await requestPermission().catch(() => "denied");
    granted = permission === "granted";
  }
  state.notificationPermissionChecked = true;
  state.notificationPermissionGranted = granted;
  return granted;
}

async function showSystemNotification(item) {
  const granted = await ensureNotificationPermission();
  if (!granted) return;
  sendNotification({
    id: notificationIdFor(item),
    title: item.title || "Уведомление",
    body: item.body || "Открыть в портале",
    actionTypeId: NOTIFICATION_ACTION_TYPE,
    autoCancel: true,
    extra: {
      notification_id: String(item.id),
      target_url: item.target_url || "/"
    }
  });
}

async function setupNotificationActions() {
  await registerActionTypes([
    {
      id: NOTIFICATION_ACTION_TYPE,
      actions: [
        {
          id: "open",
          title: "Открыть",
          foreground: true
        }
      ]
    }
  ]).catch(() => undefined);

  await onAction(async (notification) => {
    const extra = notification?.extra || {};
    const rawId = extra.notification_id || extra.notificationId || notification?.id;
    const id = Number(rawId);
    const targetUrl = extra.target_url || extra.targetUrl || "/";
    const item = Number.isFinite(id) && state.items.has(id)
      ? state.items.get(id)
      : { id, target_url: targetUrl, title: notification?.title, body: notification?.body };
    await openNotification(item).catch(() => undefined);
  }).catch(() => undefined);
}

async function poll() {
  if (!state.deviceToken || !state.portalUrl) return;
  const path = `/notifications/api/devices/feed/?cursor=${encodeURIComponent(String(state.cursor || 0))}`;
  try {
    const payload = await fetchJson(path);
    const items = Array.isArray(payload.items) ? payload.items : [];
    for (const item of items) {
      state.items.set(Number(item.id), item);
      if (Number(item.id) > Number(state.cursor || 0)) {
        await showSystemNotification(item).catch(() => undefined);
      }
    }
    if (Number(payload.cursor || 0) > state.cursor) {
      state.cursor = Number(payload.cursor);
      await saveRecord(STORE_KEYS.cursor, String(state.cursor));
    }
    renderList();
    setStatus("Подключено. Ожидание уведомлений.", "ok");
    state.retryMs = POLL_INTERVAL_MS;
  } catch (error) {
    setStatus("Нет связи с порталом или токен отозван.", "error");
    state.retryMs = Math.min(Math.max(state.retryMs * 2, POLL_INTERVAL_MS), RETRY_MAX_MS);
  } finally {
    window.clearTimeout(state.timer);
    state.timer = window.setTimeout(poll, state.retryMs);
  }
}

async function disconnect() {
  if (state.deviceToken && state.portalUrl) {
    await fetchJson("/notifications/api/devices/revoke/", { method: "POST", body: "{}" }).catch(() => undefined);
  }
  state.deviceToken = "";
  state.cursor = 0;
  await removeRecord(STORE_KEYS.deviceToken);
  await saveRecord(STORE_KEYS.cursor, "0");
  updateConnectionUi();
  window.clearTimeout(state.timer);
}

async function updateAutostartButton() {
  const enabled = await isEnabled().catch(() => false);
  els.toggleAutostart.textContent = enabled ? "Выключить автозапуск" : "Включить автозапуск";
}

els.connectForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("Подключение...", "idle");
  try {
    await exchangeCode(els.portalUrl.value, els.linkCode.value);
    els.linkCode.value = "";
    updateConnectionUi();
    await poll();
  } catch (error) {
    setStatus("Не удалось подключить устройство. Проверьте адрес портала и код.", "error");
  }
});

els.openPortal.addEventListener("click", () => {
  if (state.portalUrl) openUrl(portalUrl("/")).catch(() => undefined);
});

els.toggleAutostart.addEventListener("click", async () => {
  const enabled = await isEnabled().catch(() => false);
  if (enabled) await disable();
  else await enable();
  await updateAutostartButton();
});

els.disconnect.addEventListener("click", () => disconnect());

await initStronghold();
await setupNotificationActions();
await loadSavedConnection();
await updateAutostartButton();
if (state.deviceToken) poll();
