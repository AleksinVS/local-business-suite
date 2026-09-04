(() => {
  "use strict";

  function openWorkorderDrawer() {
    document.getElementById("detail-panel")?.classList.add("active");
    document.getElementById("drawerOverlay")?.classList.add("active");
    window.LocalBusinessPageContext?.refresh();
  }

  function closeWorkorderDrawer() {
    document.getElementById("detail-panel")?.classList.remove("active");
    document.getElementById("drawerOverlay")?.classList.remove("active");
    window.LocalBusinessPageContext?.refresh();
  }

  function toggleColumn(column) {
    if (!column) return;
    column.classList.toggle("collapsed");
    const state = JSON.parse(localStorage.getItem("kanban_collapsed_columns") || "{}");
    state[column.dataset.columnCode] = column.classList.contains("collapsed");
    localStorage.setItem("kanban_collapsed_columns", JSON.stringify(state));
  }

  function restoreColumnStates() {
    const state = JSON.parse(localStorage.getItem("kanban_collapsed_columns") || "{}");
    Object.entries(state).forEach(([code, collapsed]) => {
      const column = document.querySelector(`.kanban-column[data-column-code="${CSS.escape(code)}"]`);
      if (column) column.classList.toggle("collapsed", Boolean(collapsed));
    });
  }

  function autocompleteMetadata(option) {
    return { ...(option?.metadata || {}), ...(option || {}) };
  }

  function clearDeviceIfDepartmentChanged(departmentRoot, departmentId) {
    const form = departmentRoot.closest("form");
    const deviceRoot = form?.querySelector('[data-autocomplete][data-autocomplete-kind="device"]');
    const deviceValue = deviceRoot?.querySelector("[data-autocomplete-value]");
    if (!deviceValue?.value || !deviceValue.dataset.selectedDepartmentId) return;
    if (deviceValue.dataset.selectedDepartmentId === String(departmentId || "")) return;
    window.LocalBusinessAutocomplete?.clear(deviceRoot, { notify: true });
    deviceValue.dataset.selectedDepartmentId = "";
  }

  document.addEventListener("autocomplete:select", (event) => {
    const root = event.target.closest?.("[data-autocomplete]");
    if (!root?.closest("#workorder-create-form")) return;
    const option = event.detail?.option || {};
    const metadata = autocompleteMetadata(option);
    if (root.dataset.autocompleteKind === "department") {
      clearDeviceIfDepartmentChanged(root, option.value);
      return;
    }
    if (root.dataset.autocompleteKind !== "device" || !metadata.department_id) return;
    const valueInput = root.querySelector("[data-autocomplete-value]");
    if (valueInput) valueInput.dataset.selectedDepartmentId = String(metadata.department_id);
    const departmentRoot = root.closest("form")?.querySelector(
      '[data-autocomplete][data-autocomplete-kind="department"]'
    );
    if (departmentRoot) {
      window.LocalBusinessAutocomplete?.setSelection(
        departmentRoot,
        {
          value: metadata.department_id,
          label: metadata.department_label || "",
        },
        { notify: true }
      );
    }
  });

  document.addEventListener("autocomplete:clear", (event) => {
    const root = event.target.closest?.('[data-autocomplete][data-autocomplete-kind="department"]');
    if (root?.closest("#workorder-create-form")) clearDeviceIfDepartmentChanged(root, "");
  });

  function csrfToken() {
    try {
      return JSON.parse(document.body.getAttribute("hx-headers") || "{}")?.["x-csrftoken"] || "";
    } catch (_error) {
      return "";
    }
  }

  function clearDropState() {
    document.querySelectorAll(".work-card.dragging").forEach((node) => node.classList.remove("dragging"));
    document.querySelectorAll(".kanban-column.drag-over").forEach((node) => node.classList.remove("drag-over"));
  }

  function refreshBoard() {
    const target = document.getElementById("workorders-view");
    if (!target || !window.htmx) return;
    window.htmx.ajax("GET", `${window.location.pathname}${window.location.search}`, {
      target: "#workorders-view",
      swap: "outerHTML",
    });
  }

  function updateEmptyState() {
    const message = document.querySelector("[data-workorders-filter-empty]");
    if (!message) return;
    message.hidden = Boolean(document.querySelector(".work-card:not(.work-card-empty)"));
  }

  document.addEventListener("DOMContentLoaded", () => {
    restoreColumnStates();
    updateEmptyState();
    window.LocalBusinessAutocomplete?.init(document);
  });
  document.addEventListener("htmx:afterSwap", (event) => {
    window.LocalBusinessAutocomplete?.init(event.detail.target || document);
    if (event.detail.target?.id === "workorders-view" || event.detail.target?.id === "board-columns") {
      restoreColumnStates();
      updateEmptyState();
    }
  });
  document.body.addEventListener("workordersChanged", refreshBoard);

  document.addEventListener("dragstart", (event) => {
    const card = event.target.closest(".work-card[draggable='true']");
    if (!card || event.target.closest("a, select, button, form")) return;
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.dataset.workorderId);
    card.classList.add("dragging");
  });
  document.addEventListener("dragend", clearDropState);
  document.addEventListener("dragover", (event) => {
    const column = event.target.closest(".kanban-column[data-column-code]");
    if (!column) return;
    event.preventDefault();
    column.classList.add("drag-over");
  });
  document.addEventListener("dragleave", (event) => {
    const column = event.target.closest(".kanban-column[data-column-code]");
    if (!column || column.contains(event.relatedTarget)) return;
    column.classList.remove("drag-over");
  });
  document.addEventListener("drop", async (event) => {
    const column = event.target.closest(".kanban-column[data-column-code]");
    if (!column) return;
    event.preventDefault();
    const workorderId = event.dataTransfer.getData("text/plain");
    clearDropState();
    if (!workorderId) return;
    const response = await fetch(`/workorders/${workorderId}/board-move/`, {
      method: "POST",
      headers: {
        "Content-Type": "application/x-www-form-urlencoded",
        "HX-Request": "true",
        "HX-Target": "board-columns",
        "X-CSRFToken": csrfToken(),
      },
      body: new URLSearchParams({ column: column.dataset.columnCode }),
      credentials: "same-origin",
    });
    if (!response.ok) return;
    const temporary = document.createElement("div");
    temporary.innerHTML = await response.text();
    temporary.querySelectorAll("[hx-swap-oob='true']").forEach((replacement) => {
      document.getElementById(replacement.id)?.replaceWith(replacement);
    });
    restoreColumnStates();
  });

  window.openWorkorderDrawer = openWorkorderDrawer;
  window.closeWorkorderDrawer = closeWorkorderDrawer;
  window.openKanbanDrawer = openWorkorderDrawer;
  window.closeKanbanDrawer = closeWorkorderDrawer;
  window.toggleColumn = toggleColumn;
})();
