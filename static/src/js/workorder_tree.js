(function () {
  function rows(tree) {
    return Array.from(tree.querySelectorAll(".workorder-tree-row"));
  }

  function rowById(tree, id) {
    if (!id) return null;
    return tree.querySelector(`.workorder-tree-row[data-node-id="${CSS.escape(id)}"]`);
  }

  function storageKey(tree) {
    return `workorder_tree_expanded:${tree.dataset.treeKey || "default"}`;
  }

  function readState(tree) {
    try {
      return JSON.parse(localStorage.getItem(storageKey(tree)) || "{}");
    } catch (_error) {
      return {};
    }
  }

  function writeState(tree, state) {
    localStorage.setItem(storageKey(tree), JSON.stringify(state));
  }

  function isExpanded(row) {
    return row.getAttribute("aria-expanded") !== "false";
  }

  function setExpanded(row, expanded) {
    if (!row || row.dataset.hasChildren !== "true") return;
    row.setAttribute("aria-expanded", expanded ? "true" : "false");
    const icon = row.querySelector(".tree-toggle span");
    if (icon) icon.textContent = expanded ? "▾" : "▸";
  }

  function hasCollapsedAncestor(tree, row) {
    let parentId = row.dataset.parentId;
    while (parentId) {
      const parent = rowById(tree, parentId);
      if (!parent) return false;
      if (!isExpanded(parent)) return true;
      parentId = parent.dataset.parentId;
    }
    return false;
  }

  function refreshVisibility(tree) {
    rows(tree).forEach((row) => {
      row.hidden = hasCollapsedAncestor(tree, row);
    });
  }

  function visibleRows(tree) {
    return rows(tree).filter((row) => !row.hidden);
  }

  function descendantRows(tree, row) {
    const descendants = [];
    const stack = [row.dataset.nodeId];
    while (stack.length) {
      const parentId = stack.pop();
      rows(tree).forEach((candidate) => {
        if (candidate.dataset.parentId !== parentId) return;
        descendants.push(candidate);
        stack.push(candidate.dataset.nodeId);
      });
    }
    return descendants;
  }

  function focusRow(row) {
    rows(row.closest(".workorder-tree-shell")).forEach((item) => {
      item.tabIndex = item === row ? 0 : -1;
    });
    row.focus();
  }

  function toggle(row, forceExpanded) {
    if (!row || row.dataset.hasChildren !== "true") return;
    const tree = row.closest(".workorder-tree-shell");
    const expanded = typeof forceExpanded === "boolean" ? forceExpanded : !isExpanded(row);
    const state = readState(tree);
    setExpanded(row, expanded);
    state[row.dataset.nodeId] = expanded;
    if (!expanded) {
      descendantRows(tree, row).forEach((descendant) => {
        if (descendant.dataset.hasChildren !== "true") return;
        setExpanded(descendant, false);
        state[descendant.dataset.nodeId] = false;
      });
    }
    writeState(tree, state);
    refreshVisibility(tree);
  }

  function restore(tree) {
    const state = readState(tree);
    rows(tree).forEach((row) => {
      if (row.dataset.hasChildren !== "true") return;
      const stored = state[row.dataset.nodeId];
      setExpanded(row, stored === undefined ? true : Boolean(stored));
    });
    refreshVisibility(tree);
  }

  function refreshCurrentView() {
    const view = document.getElementById("workorders-view");
    if (!view || !window.htmx) return;
    window.htmx.ajax("GET", `${window.location.pathname}${window.location.search}`, {
      target: "#workorders-view",
      swap: "outerHTML",
    });
  }

  function initTree(tree) {
    if (!tree || tree.dataset.workorderTreeReady === "true") return;
    tree.dataset.workorderTreeReady = "true";
    restore(tree);

    tree.addEventListener("click", (event) => {
      const row = event.target.closest(".workorder-tree-row");
      if (!row || row.dataset.nodeType !== "workorder") return;
      rows(tree).forEach((item) => item.classList.remove("selected"));
      row.classList.add("selected");
    });

    tree.addEventListener("keydown", (event) => {
      const current = event.target.closest(".workorder-tree-row");
      if (!current) return;
      const visible = visibleRows(tree);
      const index = visible.indexOf(current);

      if (event.key === "ArrowDown") {
        event.preventDefault();
        focusRow(visible[Math.min(index + 1, visible.length - 1)] || current);
      } else if (event.key === "ArrowUp") {
        event.preventDefault();
        focusRow(visible[Math.max(index - 1, 0)] || current);
      } else if (event.key === "ArrowRight" && current.dataset.hasChildren === "true") {
        event.preventDefault();
        toggle(current, true);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        if (current.dataset.hasChildren === "true" && isExpanded(current)) {
          toggle(current, false);
          return;
        }
        const parent = rowById(tree, current.dataset.parentId);
        if (parent) focusRow(parent);
      } else if (event.key === "Enter") {
        event.preventDefault();
        if (current.dataset.nodeType === "workorder") {
          current.click();
        } else if (current.dataset.hasChildren === "true") {
          toggle(current);
        }
      }
    });
  }

  function initAll() {
    document.querySelectorAll(".workorder-tree-shell").forEach(initTree);
  }

  window.WorkorderTree = {
    toggle,
    refreshCurrentView,
  };

  document.addEventListener("DOMContentLoaded", initAll);
  document.addEventListener("htmx:afterSwap", initAll);
  document.body.addEventListener("workordersChanged", refreshCurrentView);
})();
