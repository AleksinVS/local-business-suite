(function () {
  const config = window.__notificationsConfig || {};
  if (!config.authenticated || !("serviceWorker" in navigator)) return;

  window.addEventListener("load", () => {
    navigator.serviceWorker.register(config.serviceWorkerUrl || "/service-worker.js").catch(() => undefined);
  });
})();
