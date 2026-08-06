(() => {
  "use strict";

  const MOBILE_BREAKPOINT = 960;

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
    const byId = new Map(nodes.map((node) => [node.dataset.departmentId, node]));
    const children = new Map(nodes.map((node) => [node, []]));

    nodes.forEach((node) => {
      const parent = byId.get(node.dataset.parentId);
      if (parent && parent !== node) children.get(parent).push(node);
    });
    nodes.forEach((node) => {
      const parent = byId.get(node.dataset.parentId);
      if (!parent || parent === node) return;
      const list = parent.querySelector(":scope > ul");
      (list || parent.appendChild(document.createElement("ul"))).appendChild(node);
    });

    function childList(node) {
      return node.querySelector(":scope > ul");
    }

    function setExpanded(node, expanded) {
      const list = childList(node);
      const toggle = node.querySelector("[data-department-filter-toggle]");
      if (!list || !toggle) return;
      list.hidden = !expanded;
      toggle.hidden = false;
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute(
        "aria-label",
        `${expanded ? "Свернуть" : "Развернуть"} подразделение ${node.querySelector("label span").textContent.trim()}`,
      );
      node.dataset.expanded = String(expanded);
    }

    function ancestors(node) {
      const found = [];
      let parent = byId.get(node.dataset.parentId);
      while (parent) {
        found.push(parent);
        parent = byId.get(parent.dataset.parentId);
      }
      return found;
    }

    nodes.forEach((node) => {
      if (!children.get(node).length) return;
      const isRoot = !byId.has(node.dataset.parentId);
      const wasExpanded = node.querySelector("[data-department-filter-toggle]").getAttribute("aria-expanded") === "true";
      const isSelectedPath = Boolean(node.querySelector("[data-department-filter-checkbox]:checked"));
      setExpanded(node, isRoot || wasExpanded || isSelectedPath);
    });
    nodes.filter((node) => node.querySelector("[data-department-filter-checkbox]:checked")).forEach((node) => {
      ancestors(node).forEach((ancestor) => setExpanded(ancestor, true));
    });

    function updateSummary() {
      const selected = nodes.filter((node) => node.querySelector("[data-department-filter-checkbox]").checked);
      if (summary) {
        summary.textContent = selected.length
          ? `Выбрано подразделений: ${selected.length}`
          : "Все доступные подразделения";
      }
      if (reset) reset.hidden = selected.length === 0;
    }

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

    function updateHierarchyState() {
      [...nodes].reverse().forEach((node) => {
        const checkbox = node.querySelector("[data-department-filter-checkbox]");
        if (!checkbox) return;
        checkbox.indeterminate = !checkbox.checked && descendants(node).some((child) => (
          child.querySelector("[data-department-filter-checkbox]")?.checked
        ));
      });
    }

    function applySearch() {
      const query = (search?.value || "").trim().toLocaleLowerCase();
      let matches = 0;
      nodes.forEach((node) => {
        const label = node.querySelector("label span").textContent.toLocaleLowerCase();
        const matched = !query || label.includes(query);
        node.dataset.searchMatch = String(matched);
        if (matched) matches += 1;
      });
      nodes.forEach((node) => {
        const visible = !query || node.dataset.searchMatch === "true" || Array.from(node.querySelectorAll("[data-department-filter-node]")).some((child) => child.dataset.searchMatch === "true");
        node.hidden = !visible;
        if (query && visible && children.get(node).length) setExpanded(node, true);
      });
      if (noResults) noResults.hidden = !query || matches > 0;
    }

    tree.addEventListener("click", (event) => {
      const toggle = event.target.closest("[data-department-filter-toggle]");
      if (!toggle) return;
      const node = toggle.closest("[data-department-filter-node]");
      setExpanded(node, node.dataset.expanded !== "true");
    });
    tree.addEventListener("change", (event) => {
      if (!event.target.matches("[data-department-filter-checkbox]")) return;
      const node = event.target.closest("[data-department-filter-node]");
      if (event.target.checked) {
        const selectedAncestor = ancestors(node).find((ancestor) => (
          ancestor.querySelector("[data-department-filter-checkbox]")?.checked
        ));
        if (selectedAncestor) {
          event.target.checked = false;
          selectedAncestor.querySelector("[data-department-filter-checkbox]")?.focus();
        } else {
          descendants(node).forEach((child) => {
            child.querySelector("[data-department-filter-checkbox]").checked = false;
          });
        }
      }
      updateHierarchyState();
      updateSummary();
      submitFilters();
    });
    search?.addEventListener("input", applySearch);
    reset?.addEventListener("click", () => {
      nodes.forEach((node) => { node.querySelector("[data-department-filter-checkbox]").checked = false; });
      updateHierarchyState();
      updateSummary();
      submitFilters();
    });
    updateHierarchyState();
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

    sidebar?.classList.remove("collapsed");
    if (backdrop && backdrop.parentElement !== document.body) {
      document.body.appendChild(backdrop);
    }

    function setChatMode(mode) {
      shell.dataset.aiSidebarMode = mode;
      const isChat = mode === "chat";
      launcher?.setAttribute("aria-expanded", String(isChat));
      chatPanel?.setAttribute("aria-hidden", String(!isChat));
      if (isChat) {
        if (launcherText) launcherText.textContent = "Сообщение ИИ...";
        if (launcherStatus) launcherStatus.textContent = "";
      }
      document.dispatchEvent(new CustomEvent(isChat ? "workorders:ai-sidebar-open" : "workorders:ai-sidebar-collapse"));
    }

    function openMobile(invoker) {
      if (window.innerWidth > MOBILE_BREAKPOINT || !sidebar) return;
      mobileInvoker = invoker || document.activeElement;
      sidebar.classList.remove("collapsed");
      sidebar.dataset.workordersSidebarOpen = "true";
      sidebar.setAttribute("role", "dialog");
      sidebar.setAttribute("aria-modal", "true");
      sidebar.setAttribute("aria-label", "Фильтры заявок и ИИ-чат");
      backdrop.hidden = false;
      close?.focus();
    }

    function closeMobile() {
      if (!sidebar) return;
      delete sidebar.dataset.workordersSidebarOpen;
      sidebar.removeAttribute("role");
      sidebar.removeAttribute("aria-modal");
      sidebar.removeAttribute("aria-label");
      backdrop.hidden = true;
      mobileInvoker?.focus?.();
    }

    launcher?.addEventListener("click", () => setChatMode("chat"));
    collapse?.addEventListener("click", () => {
      setChatMode("filters");
      launcher?.focus();
    });
    close?.addEventListener("click", closeMobile);
    backdrop?.addEventListener("click", closeMobile);
    document.addEventListener("workorders:ai-run-finished", (event) => {
      if (shell.dataset.aiSidebarMode !== "filters") return;
      const message = event.detail?.error ? "Ответ ИИ завершился с ошибкой" : "Ответ ИИ готов";
      if (launcherText) launcherText.textContent = message;
      if (launcherStatus) launcherStatus.textContent = message;
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Escape") return;
      const nestedDialog = event.target.closest?.("[role='dialog'][aria-modal='true']");
      if (nestedDialog && nestedDialog !== sidebar) return;
      if (shell.dataset.aiSidebarMode === "chat" && chatPanel?.contains(document.activeElement)) {
        setChatMode("filters");
        launcher?.focus();
      } else if (sidebar?.dataset.workordersSidebarOpen === "true") {
        closeMobile();
      }
    });
    document.addEventListener("keydown", (event) => {
      if (event.key !== "Tab" || sidebar?.dataset.workordersSidebarOpen !== "true") return;
      const focusable = Array.from(sidebar.querySelectorAll(
        "button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), a[href]",
      )).filter((element) => !element.hidden && element.offsetParent !== null);
      if (!focusable.length) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
    document.addEventListener("click", (event) => {
      const toggle = event.target.closest(".sidebar-toggle");
      if (!toggle || window.innerWidth > MOBILE_BREAKPOINT) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      openMobile(toggle);
    }, true);
  }

  function init() {
    document.querySelectorAll("[data-department-filter]").forEach(initDepartmentFilter);
    initFilterForm();
    document.querySelectorAll("[data-workorders-sidebar-shell]").forEach(initSidebarShell);
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("htmx:afterSwap", init);
})();
