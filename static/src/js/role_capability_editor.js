(() => {
  "use strict";

  function init(root) {
    if (!root || root.dataset.roleEditorReady === "true") return;
    root.dataset.roleEditorReady = "true";
    const form = root.closest("form");
    const hidden = form?.querySelector("input[name='active_group']");
    const panels = () => [...root.querySelectorAll("[data-role-editor-panel]")];
    const activate = (value, focus = false) => {
      const available = panels();
      if (!available.length) return;
      const active = available.some((panel) => panel.dataset.roleEditorPanel === value)
        ? value
        : available[0].dataset.roleEditorPanel;
      if (hidden) hidden.value = active;
      root.querySelectorAll("[data-role-editor-panel]").forEach((panel) => {
        const selected = panel.dataset.roleEditorPanel === active;
        panel.hidden = !selected;
        panel.setAttribute("aria-hidden", String(!selected));
      });
      root.querySelectorAll("[data-role-editor-tab]").forEach((tab) => {
        const selected = tab.dataset.roleEditorTab === active;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (focus && selected) tab.focus();
      });
    };
    const tabs = () => [...root.querySelectorAll("[data-role-editor-tab]")];
    root.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-role-editor-tab]");
      if (!tab || !root.contains(tab)) return;
      event.preventDefault();
      activate(tab.dataset.roleEditorTab);
    });
    root.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      const list = tabs();
      const current = list.indexOf(document.activeElement);
      if (current < 0 || !list.length) return;
      let next = current;
      if (event.key === "Home") next = 0;
      else if (event.key === "End") next = list.length - 1;
      else if (event.key === "ArrowLeft" || event.key === "ArrowUp") next = (current - 1 + list.length) % list.length;
      else next = (current + 1) % list.length;
      event.preventDefault();
      activate(list[next].dataset.roleEditorTab, true);
    });
    const initial = hidden?.value || root.querySelector("[data-role-editor-tab]")?.dataset.roleEditorTab;
    activate(initial);
  }

  window.SharedRoleCapabilityEditor = { init };
})();
