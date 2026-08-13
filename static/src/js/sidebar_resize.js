(() => {
  "use strict";

  const NEW_KEY = "left_sidebar_width_v1";
  const LEGACY_KEY = "workorders_sidebar_width";
  const MIN_WIDTH = 280;
  const MAX_WIDTH = 560;

  function readWidth() {
    try {
      const value = localStorage.getItem(NEW_KEY) || localStorage.getItem(LEGACY_KEY);
      const parsed = Number.parseInt(value, 10);
      return Number.isFinite(parsed) ? parsed : 320;
    } catch (_error) {
      return 320;
    }
  }

  function init(options = {}) {
    const handle = options.handle || document.querySelector(options.handleSelector);
    const sidebar = options.sidebar || document.querySelector(options.sidebarSelector || "#sidebar");
    if (!handle || !sidebar || handle.dataset.sidebarResizeReady === "true") return;
    handle.dataset.sidebarResizeReady = "true";
    const mobileBreakpoint = options.mobileBreakpoint || 960;
    const clamp = (width) => Math.max(MIN_WIDTH, Math.min(MAX_WIDTH, width));
    let syncFrame = 0;
    const sync = () => {
      if (syncFrame) return;
      syncFrame = window.requestAnimationFrame(() => {
        syncFrame = 0;
        const occupied = window.innerWidth <= mobileBreakpoint ? 0 : Math.round(sidebar.getBoundingClientRect().width);
        if (options.layoutClass) document.body.classList.add(options.layoutClass);
        if (options.occupiedVar) document.body.style.setProperty(options.occupiedVar, `${occupied}px`);
        options.onSync?.(occupied);
      });
    };
    const setWidth = (width, persist = true) => {
      if (window.innerWidth <= mobileBreakpoint) return;
      const value = clamp(width);
      sidebar.style.setProperty(options.widthVariable || "--workorders-sidebar-width", `${value}px`);
      handle.setAttribute("aria-valuenow", String(value));
      if (persist) {
        try { localStorage.setItem(NEW_KEY, String(value)); } catch (_error) {}
      }
      sync();
    };

    setWidth(readWidth(), false);
    sync();
    new MutationObserver(sync).observe(sidebar, { attributes: true, attributeFilter: ["class"] });
    window.addEventListener("resize", sync);
    handle.addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= mobileBreakpoint || sidebar.classList.contains("collapsed") || event.button !== 0) return;
      event.preventDefault();
      document.body.classList.add("is-resizing-sidebar");
      const sidebarLeft = sidebar.getBoundingClientRect().left;
      const move = (moveEvent) => {
        if (moveEvent.pointerId !== event.pointerId) return;
        setWidth(moveEvent.clientX - sidebarLeft);
      };
      const end = () => {
        document.body.classList.remove("is-resizing-sidebar");
        window.removeEventListener("pointermove", move);
        window.removeEventListener("pointerup", end);
        window.removeEventListener("pointercancel", end);
        window.removeEventListener("blur", end);
      };
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", end);
      window.addEventListener("pointercancel", end);
      window.addEventListener("blur", end);
    });
    handle.addEventListener("keydown", (event) => {
      if (window.innerWidth <= mobileBreakpoint) return;
      const current = Number.parseInt(handle.getAttribute("aria-valuenow"), 10) || MIN_WIDTH;
      if (event.key === "ArrowLeft") setWidth(current - 16);
      else if (event.key === "ArrowRight") setWidth(current + 16);
      else if (event.key === "Home") setWidth(MIN_WIDTH);
      else if (event.key === "End") setWidth(MAX_WIDTH);
      else return;
      event.preventDefault();
    });
  }

  window.SharedSidebarResize = { init };
})();
