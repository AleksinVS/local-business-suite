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

  function initWorkorderAutocomplete(root) {
    if (!root || root.dataset.autocompleteInitialized === "true") return;
    root.dataset.autocompleteInitialized = "true";

    const input = root.querySelector("[data-autocomplete-input]");
    const valueInput = root.querySelector("[data-autocomplete-value]");
    const optionsNode = root.querySelector("[data-autocomplete-options]");
    const endpoint = root.dataset.autocompleteUrl;
    const kind = root.dataset.autocompleteKind;
    const isRequired = root.dataset.autocompleteRequired === "true";
    if (!input || !valueInput || !optionsNode || !endpoint) return;

    let selectedLabel = input.value;
    let results = [];
    let activeIndex = -1;
    let debounceTimer = 0;
    let requestController = null;

    function closeOptions() {
      optionsNode.hidden = true;
      input.setAttribute("aria-expanded", "false");
      activeIndex = -1;
      input.removeAttribute("aria-activedescendant");
    }

    function setSelectionError() {
      const hasUnselectedText = Boolean(input.value.trim() && !valueInput.value);
      if (hasUnselectedText) {
        input.setCustomValidity("Выберите значение из предложенных вариантов.");
      } else if (isRequired && !valueInput.value) {
        input.setCustomValidity("Выберите подразделение из предложенных вариантов.");
      } else {
        input.setCustomValidity("");
      }
    }

    function clearDeviceIfDepartmentChanged(departmentId) {
      if (kind !== "department") return;
      const form = root.closest("form");
      const deviceRoot = form?.querySelector('[data-workorder-autocomplete][data-autocomplete-kind="device"]');
      const deviceValue = deviceRoot?.querySelector("[data-autocomplete-value]");
      const deviceInput = deviceRoot?.querySelector("[data-autocomplete-input]");
      if (!deviceValue?.value || !deviceValue.dataset.selectedDepartmentId) return;
      if (deviceValue.dataset.selectedDepartmentId === String(departmentId)) return;
      deviceValue.value = "";
      deviceValue.dataset.selectedDepartmentId = "";
      if (deviceInput) {
        deviceInput.value = "";
        deviceInput.setCustomValidity("");
      }
    }

    function selectResult(result) {
      valueInput.value = String(result.id);
      selectedLabel = result.label;
      input.value = result.label;
      input.setCustomValidity("");
      if (kind === "department") {
        clearDeviceIfDepartmentChanged(result.id);
      }
      if (kind === "device") {
        valueInput.dataset.selectedDepartmentId = String(result.department_id || "");
        const form = root.closest("form");
        const departmentRoot = form?.querySelector('[data-workorder-autocomplete][data-autocomplete-kind="department"]');
        const departmentValue = departmentRoot?.querySelector("[data-autocomplete-value]");
        const departmentInput = departmentRoot?.querySelector("[data-autocomplete-input]");
        if (departmentValue && departmentInput && result.department_id) {
          departmentValue.value = String(result.department_id);
          departmentInput.value = result.department_label || "";
          departmentInput.setCustomValidity("");
        }
      }
      closeOptions();
    }

    function activateOption(index) {
      if (!results.length) return;
      activeIndex = Math.max(0, Math.min(index, results.length - 1));
      optionsNode.querySelectorAll("[data-autocomplete-option]").forEach((option, optionIndex) => {
        const isActive = optionIndex === activeIndex;
        option.classList.toggle("active", isActive);
        option.setAttribute("aria-selected", String(isActive));
        if (isActive) {
          input.setAttribute("aria-activedescendant", option.id);
          option.scrollIntoView({ block: "nearest" });
        }
      });
    }

    function renderOptions(items) {
      results = Array.isArray(items) ? items : [];
      optionsNode.replaceChildren();
      if (!results.length) {
        const empty = document.createElement("div");
        empty.className = "workorder-autocomplete-empty";
        empty.textContent = "Подходящих вариантов нет";
        optionsNode.appendChild(empty);
      } else {
        results.forEach((result, index) => {
          const option = document.createElement("div");
          option.id = `${optionsNode.id}-option-${index}`;
          option.className = "workorder-autocomplete-option";
          option.setAttribute("role", "option");
          option.setAttribute("aria-selected", "false");
          option.tabIndex = -1;
          option.dataset.autocompleteOption = "";
          option.textContent = result.label;
          option.addEventListener("mousedown", (event) => event.preventDefault());
          option.addEventListener("click", () => selectResult(result));
          optionsNode.appendChild(option);
        });
      }
      optionsNode.hidden = false;
      input.setAttribute("aria-expanded", "true");
      activeIndex = -1;
    }

    async function loadOptions() {
      requestController?.abort();
      requestController = new AbortController();
      const url = new URL(endpoint, window.location.origin);
      url.searchParams.set("q", input.value.trim());
      try {
        const response = await fetch(url, {
          credentials: "same-origin",
          headers: { Accept: "application/json" },
          signal: requestController.signal,
        });
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        renderOptions(payload.results);
      } catch (error) {
        if (error.name === "AbortError") return;
        renderOptions([]);
      }
    }

    function scheduleLoad() {
      window.clearTimeout(debounceTimer);
      debounceTimer = window.setTimeout(loadOptions, 180);
    }

    input.addEventListener("focus", loadOptions);
    input.addEventListener("input", () => {
      if (input.value !== selectedLabel) {
        valueInput.value = "";
        valueInput.dataset.selectedDepartmentId = "";
      }
      setSelectionError();
      scheduleLoad();
    });
    input.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown") {
        event.preventDefault();
        if (optionsNode.hidden) loadOptions();
        else activateOption(activeIndex + 1);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        activateOption(activeIndex <= 0 ? results.length - 1 : activeIndex - 1);
      } else if (event.key === "Enter" && activeIndex >= 0) {
        event.preventDefault();
        selectResult(results[activeIndex]);
      } else if (event.key === "Escape") {
        closeOptions();
      }
    });
    input.addEventListener("blur", () => window.setTimeout(closeOptions, 100));
    setSelectionError();
  }

  function initWorkorderAutocompletes(scope = document) {
    scope.querySelectorAll?.("[data-workorder-autocomplete]").forEach(initWorkorderAutocomplete);
  }

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
    initWorkorderAutocompletes();
  });
  document.addEventListener("htmx:afterSwap", (event) => {
    initWorkorderAutocompletes(event.detail.target || document);
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
