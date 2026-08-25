(() => {
  "use strict";

  function initRoleEditor(root) {
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

  window.SharedRoleCapabilityEditor = { init: initRoleEditor };

  function dirtyForms(root = document) {
    return [...root.querySelectorAll(".access-context-form[data-access-dirty='true'], .role-definition-form[data-access-dirty='true']")];
  }

  function bindDirty(form) {
    if (!form || form.dataset.accessDirtyBound === "true") return;
    form.dataset.accessDirtyBound = "true";
    form.addEventListener("input", () => { form.dataset.accessDirty = "true"; });
    form.addEventListener("change", () => { form.dataset.accessDirty = "true"; });
    form.addEventListener("submit", (event) => {
      form.dataset.accessSubmittedDirty = form.dataset.accessDirty === "true" ? "true" : "false";
      const submitter = event.submitter;
      if (submitter) {
        form.dataset.accessSubmitterName = submitter.name || "";
        form.dataset.accessSubmitterValue = submitter.value || "";
      }
      form.dataset.accessDirty = "false";
    });
  }

  function initUserBundle(root) {
    if (!root || root.dataset.accessEditorReady === "true") return;
    root.dataset.accessEditorReady = "true";
    const activate = (value, focus = false) => {
      const available = [...root.querySelectorAll("[data-editor-group]")];
      if (!available.length) return;
      const active = available.some((group) => group.dataset.editorGroup === value)
        ? value : available[0].dataset.editorGroup;
      const hidden = root.querySelector("input[name='active_editor']");
      if (hidden) hidden.value = active;
      available.forEach((group) => {
        const selected = group.dataset.editorGroup === active;
        group.hidden = !selected;
        group.setAttribute("aria-hidden", String(!selected));
      });
      root.querySelectorAll("[data-editor-tab]").forEach((tab) => {
        const selected = tab.dataset.editorTab === active;
        tab.setAttribute("aria-selected", String(selected));
        tab.tabIndex = selected ? 0 : -1;
        if (focus && selected) tab.focus();
      });
    };
    root.addEventListener("click", (event) => {
      const tab = event.target.closest("[data-editor-tab], [data-editor-target]");
      if (!tab || !root.contains(tab)) return;
      event.preventDefault();
      activate(tab.dataset.editorTab || tab.dataset.editorTarget, false);
    });
    root.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "ArrowUp", "ArrowDown"].includes(event.key)) return;
      const tabs = [...root.querySelectorAll("[data-editor-tab]")];
      const current = tabs.indexOf(document.activeElement);
      if (current < 0 || !tabs.length) return;
      const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1
        : (current + (event.key === "ArrowLeft" || event.key === "ArrowUp" ? -1 : 1) + tabs.length) % tabs.length;
      event.preventDefault();
      activate(tabs[next].dataset.editorTab, true);
    });
    activate(root.querySelector("input[name='active_editor']")?.value || "roles");
  }

  function initAccessEditors(root = document) {
    root.querySelectorAll("[data-access-bundle-form]").forEach(initUserBundle);
    root.querySelectorAll(".access-context-form, .role-definition-form").forEach(bindDirty);
    root.querySelectorAll(".role-capability-editor, [data-standalone-role-editor]").forEach(initRoleEditor);
  }

  function confirmDiscard(root = document) {
    const dirty = dirtyForms(root);
    if (!dirty.length) return true;
    if (!window.confirm("Есть несохранённые изменения. Покинуть редактор?")) return false;
    dirty.forEach((form) => { form.dataset.accessDirty = "false"; });
    return true;
  }

  window.SharedAccessEditor = {
    init: initAccessEditors,
    initUserBundle,
    dirtyForms,
    confirmDiscard,
  };
  initAccessEditors(document);
  window.addEventListener("beforeunload", (event) => {
    if (!dirtyForms().length) return;
    event.preventDefault();
    event.returnValue = "";
  });
})();
