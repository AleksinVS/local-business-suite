(() => {
  "use strict";

  const MOBILE_BREAKPOINT = 960;
  const SIDEBAR_WIDTH_KEY = "workorders_sidebar_width";
  const SIDEBAR_MIN_WIDTH = 280;
  const SIDEBAR_MAX_WIDTH = 560;

  function filterForm() {
    return document.querySelector("[data-workorder-filter-form]");
  }

  function submitFilters() {
    const form = filterForm();
    if (!form) return;
    if (typeof form.requestSubmit === "function") form.requestSubmit();
    else form.submit();
  }

  function initDepartmentFilter(filter) {
    if (!filter || filter.dataset.ready === "true") return;
    filter.dataset.ready = "true";

    const tree = filter.querySelector("[data-department-filter-tree]");
    const search = filter.querySelector("[data-department-filter-search]");
    const reset = filter.querySelector("[data-department-filter-reset]");
    const summary = filter.querySelector("[data-department-filter-summary]");
    const noResults = filter.querySelector("[data-department-filter-no-results]");
    if (!tree) return;

    const nodes = Array.from(tree.querySelectorAll("[data-department-filter-node]"));
    const byKey = new Map(nodes.map((node) => [node.dataset.nodeKey, node]));
    const children = new Map(nodes.map((node) => [node, []]));
    const selectButton = (node) => node.querySelector("[data-department-filter-select]");
    const valueInput = (node) => node.querySelector("[data-department-filter-value]");

    nodes.forEach((node) => {
      const parent = byKey.get(node.dataset.parentKey);
      if (parent && parent !== node) children.get(parent).push(node);
    });
    nodes.forEach((node) => {
      const parent = byKey.get(node.dataset.parentKey);
      if (!parent || parent === node) return;
      let list = parent.querySelector(":scope > ul");
      if (!list) {
        list = document.createElement("ul");
        list.setAttribute("role", "group");
        parent.appendChild(list);
      }
      if (!list.id) {
        list.id = `department-filter-children-${parent.dataset.nodeKey.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
      }
      parent.querySelector(":scope > .department-filter-node-row > [data-department-filter-toggle]")
        ?.setAttribute("aria-controls", list.id);
      list.appendChild(node);
    });

    function childList(node) {
      return node.querySelector(":scope > ul");
    }

    function ancestors(node) {
      const found = [];
      let parent = byKey.get(node.dataset.parentKey);
      while (parent) {
        found.push(parent);
        parent = byKey.get(parent.dataset.parentKey);
      }
      return found;
    }

    function setExpanded(node, expanded) {
      const list = childList(node);
      const toggle = node.querySelector("[data-department-filter-toggle]");
      if (!list || !toggle) return;
      list.hidden = !expanded;
      toggle.hidden = false;
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", `${expanded ? "Свернуть" : "Развернуть"} ${selectButton(node).textContent.trim()}`);
      node.dataset.expanded = String(expanded);
    }

    function isSelected(node) {
      return !valueInput(node).disabled;
    }

    function setSelected(node, selected) {
      valueInput(node).disabled = !selected;
      selectButton(node).setAttribute("aria-selected", String(selected));
      node.classList.toggle("is-selected", selected);
      const createWorkorder = node.querySelector("[data-department-filter-create-workorder]");
      if (createWorkorder) createWorkorder.hidden = !selected;
    }

    nodes.forEach((node) => {
      const hasChildren = children.get(node).length > 0;
      if (!hasChildren) return;
      const toggle = node.querySelector("[data-department-filter-toggle]");
      const isRoot = !byKey.has(node.dataset.parentKey);
      const wasExpanded = toggle?.getAttribute("aria-expanded") === "true";
      const selectedPath = isSelected(node) || descendants(node).some(isSelected);
      setExpanded(node, isRoot || wasExpanded || selectedPath);
    });
    nodes.filter(isSelected).forEach((node) => {
      node.classList.add("is-selected");
      ancestors(node).forEach((ancestor) => setExpanded(ancestor, true));
    });

    function descendants(node) {
      const found = [];
      const pending = [...(children.get(node) || [])];
      while (pending.length) {
        const child = pending.shift();
        found.push(child);
        pending.push(...(children.get(child) || []));
      }
      return found;
    }

    function selectedNodes() {
      return nodes.filter(isSelected);
    }

    function updateSummary() {
      const selected = selectedNodes();
      if (summary) {
        summary.textContent = selected.length
          ? `Выбрано: ${selected.length}`
          : "Все доступные подразделения и изделия";
      }
      if (reset) reset.hidden = selected.length === 0;
    }

    function applySearch() {
      const query = (search?.value || "").trim().toLocaleLowerCase();
      let matches = 0;
      nodes.forEach((node) => {
        const label = selectButton(node).textContent.toLocaleLowerCase();
        const matched = !query || label.includes(query);
        node.dataset.searchMatch = String(matched);
        if (matched) matches += 1;
      });
      nodes.forEach((node) => {
        const visible = !query || node.dataset.searchMatch === "true" || descendants(node).some((child) => child.dataset.searchMatch === "true");
        node.hidden = !visible;
        if (query && visible && children.get(node).length) setExpanded(node, true);
      });
      if (noResults) noResults.hidden = !query || matches > 0;
    }

    function chooseNode(node, additive) {
      if (!additive) {
        nodes.forEach((item) => setSelected(item, item === node));
      } else {
        const shouldSelect = !isSelected(node);
        if (shouldSelect && node.dataset.nodeKind === "department") {
          [...ancestors(node), ...descendants(node)]
            .filter((item) => item.dataset.nodeKind === "department")
            .forEach((item) => setSelected(item, false));
        }
        setSelected(node, shouldSelect);
      }
      ancestors(node).forEach((ancestor) => setExpanded(ancestor, true));
      updateSummary();
      submitFilters();
    }

    tree.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-department-filter-toggle]");
      if (toggle) {
        const node = toggle.closest("[data-department-filter-node]");
        setExpanded(node, node.dataset.expanded !== "true");
        return;
      }
      const button = event.target.closest("[data-department-filter-select]");
      if (!button) return;
      const node = button.closest("[data-department-filter-node]");
      chooseNode(node, event.ctrlKey || event.metaKey);
    });
    search?.addEventListener("input", applySearch);
    reset?.addEventListener("click", () => {
      nodes.forEach((node) => setSelected(node, false));
      updateSummary();
      submitFilters();
    });
    updateSummary();
  }

  function initFilterForm() {
    const form = filterForm();
    if (!form || form.dataset.ready === "true") return;
    form.dataset.ready = "true";
    let searchTimer;
    form.addEventListener("input", (event) => {
      if (!event.target.matches("[data-workorder-filter-search]")) return;
      window.clearTimeout(searchTimer);
      searchTimer = window.setTimeout(submitFilters, 300);
    });
    form.addEventListener("change", (event) => {
      if (event.target.matches("[data-workorder-board-select]")) return;
      submitFilters();
    });
    form.querySelector("[data-workorder-board-select]")?.addEventListener("change", (event) => {
      const destination = new URL(event.target.value, window.location.origin);
      const values = new URLSearchParams(new FormData(form));
      values.delete("board");
      destination.search = values.toString();
      window.location.assign(destination.toString());
    });
  }

  function initSidebarResize(shell) {
    const handle = shell.querySelector("[data-workorders-sidebar-resize]");
    const sidebar = document.getElementById("sidebar");
    if (!handle || !sidebar || handle.dataset.ready === "true") return;
    handle.dataset.ready = "true";
    const clamp = (width) => Math.max(SIDEBAR_MIN_WIDTH, Math.min(SIDEBAR_MAX_WIDTH, width));
    const setWidth = (width, persist = true) => {
      if (window.innerWidth <= MOBILE_BREAKPOINT) return;
      const value = clamp(width);
      sidebar.style.setProperty("--workorders-sidebar-width", `${value}px`);
      handle.setAttribute("aria-valuenow", String(value));
      if (persist) {
        try {
          localStorage.setItem(SIDEBAR_WIDTH_KEY, String(value));
        } catch (_error) {
          // Изменение ширины остается рабочим, даже если хранилище запрещено браузером.
        }
      }
    };
    let storedValue = null;
    try {
      storedValue = localStorage.getItem(SIDEBAR_WIDTH_KEY);
    } catch (_error) {
      // Используем ширину по умолчанию при недоступном localStorage.
    }
    const storedWidth = Number.parseInt(storedValue, 10);
    setWidth(Number.isFinite(storedWidth) ? storedWidth : 320, false);
    handle.addEventListener("pointerdown", (event) => {
      if (window.innerWidth <= MOBILE_BREAKPOINT || sidebar.classList.contains("collapsed") || event.button !== 0) return;
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
      if (window.innerWidth <= MOBILE_BREAKPOINT) return;
      const current = Number.parseInt(handle.getAttribute("aria-valuenow"), 10) || SIDEBAR_MIN_WIDTH;
      if (event.key === "ArrowLeft") setWidth(current - 16);
      else if (event.key === "ArrowRight") setWidth(current + 16);
      else if (event.key === "Home") setWidth(SIDEBAR_MIN_WIDTH);
      else if (event.key === "End") setWidth(SIDEBAR_MAX_WIDTH);
      else return;
      event.preventDefault();
    });
  }

  function initSidebarShell(shell) {
    if (!shell || shell.dataset.ready === "true") return;
    shell.dataset.ready = "true";
    const sidebar = document.getElementById("sidebar");
    const launcher = shell.querySelector("[data-workorders-ai-launcher]");
    const launcherText = shell.querySelector("[data-workorders-ai-launcher-text]");
    const launcherStatus = shell.querySelector("[data-workorders-ai-launcher-status]");
    const chatPanel = shell.querySelector("[data-workorders-ai-panel]");
    const collapse = shell.querySelector("[data-workorders-ai-collapse]");
    const close = shell.querySelector("[data-workorders-sidebar-close]");
    const backdrop = document.querySelector("[data-workorders-sidebar-backdrop]");
    let mobileInvoker = null;

    if (backdrop && backdrop.parentElement !== document.body) document.body.appendChild(backdrop);
    function setChatMode(mode) {
      shell.dataset.aiSidebarMode = mode;
      const isChat = mode === "chat";
      launcher?.setAttribute("aria-expanded", String(isChat));
      chatPanel?.setAttribute("aria-hidden", String(!isChat));
      if (isChat) { if (launcherText) launcherText.textContent = "Сообщение ИИ..."; if (launcherStatus) launcherStatus.textContent = ""; }
      document.dispatchEvent(new CustomEvent(isChat ? "workorders:ai-sidebar-open" : "workorders:ai-sidebar-collapse"));
    }
    function openMobile(invoker) {
      if (window.innerWidth > MOBILE_BREAKPOINT || !sidebar) return;
      mobileInvoker = invoker || document.activeElement; sidebar.classList.remove("collapsed"); sidebar.dataset.workordersSidebarOpen = "true";
      sidebar.setAttribute("role", "dialog"); sidebar.setAttribute("aria-modal", "true"); sidebar.setAttribute("aria-label", "Фильтры заявок и ИИ-чат"); backdrop.hidden = false; close?.focus();
    }
    function closeMobile() {
      if (!sidebar) return; delete sidebar.dataset.workordersSidebarOpen; sidebar.removeAttribute("role"); sidebar.removeAttribute("aria-modal"); sidebar.removeAttribute("aria-label"); backdrop.hidden = true; mobileInvoker?.focus?.();
    }
    launcher?.addEventListener("click", () => setChatMode("chat"));
    collapse?.addEventListener("click", () => { setChatMode("filters"); launcher?.focus(); });
    close?.addEventListener("click", closeMobile); backdrop?.addEventListener("click", closeMobile);
    document.addEventListener("workorders:ai-run-finished", (event) => { if (shell.dataset.aiSidebarMode !== "filters") return; const message = event.detail?.error ? "Ответ ИИ завершился с ошибкой" : "Ответ ИИ готов"; if (launcherText) launcherText.textContent = message; if (launcherStatus) launcherStatus.textContent = message; });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const nestedDialog = event.target.closest?.("[role='dialog'][aria-modal='true']");
      if (nestedDialog && nestedDialog !== sidebar) return;
      if (shell.dataset.aiSidebarMode === "chat" && chatPanel?.contains(document.activeElement)) { setChatMode("filters"); launcher?.focus(); }
      else if (sidebar?.dataset.workordersSidebarOpen === "true") closeMobile();
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || sidebar?.dataset.workordersSidebarOpen !== "true") return;
      const focusable = Array.from(sidebar.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]",
      )).filter((element) => !element.hidden && element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
      else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
    });
    document.addEventListener("click", (event) => { const toggle = event.target.closest(".sidebar-toggle"); if (!toggle || window.innerWidth > MOBILE_BREAKPOINT) return; event.preventDefault(); event.stopImmediatePropagation(); openMobile(toggle); }, true);
  }

  function init() {
    document.querySelectorAll("[data-department-filter]").forEach(initDepartmentFilter);
    initFilterForm();
    document.querySelectorAll("[data-workorders-sidebar-shell]").forEach((shell) => { initSidebarShell(shell); initSidebarResize(shell); });
  }
  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSwap", init);
})();
