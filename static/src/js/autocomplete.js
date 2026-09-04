(() => {
  "use strict";

  if (window.LocalBusinessAutocomplete) {
    window.LocalBusinessAutocomplete.init(document);
    return;
  }

  const states = new WeakMap();

  function rootsWithin(scope) {
    const roots = [];
    if (scope?.matches?.("[data-autocomplete]")) roots.push(scope);
    scope?.querySelectorAll?.("[data-autocomplete]").forEach((root) => roots.push(root));
    return roots;
  }

  function dispatch(root, name, detail = {}) {
    root.dispatchEvent(new CustomEvent(name, { bubbles: true, detail }));
  }

  function normalizeResult(result) {
    if (!result || typeof result !== "object") return null;
    const value = String(result.value ?? result.id ?? "");
    const label = String(result.label ?? "").trim();
    if (!value || !label) return null;
    return {
      ...result,
      value,
      label,
      secondary: String(result.secondary ?? "").trim(),
      metadata: result.metadata && typeof result.metadata === "object" ? result.metadata : {},
    };
  }

  function contextFields(root) {
    let mapping = {};
    try {
      mapping = JSON.parse(root.dataset.autocompleteContext || "{}");
    } catch (_error) {
      mapping = {};
    }
    const form = root.closest("form");
    const fields = [];
    Object.entries(mapping).forEach(([key, selector]) => {
      if (!/^[a-z][a-z0-9_]{0,63}$/.test(key) || typeof selector !== "string") return;
      let field = null;
      try {
        field = form?.querySelector(selector) || document.querySelector(selector);
      } catch (_error) {
        field = null;
      }
      if (field) {
        const sourceRoot = field.closest?.("[data-autocomplete]");
        fields.push({ key, field, sourceRoot: sourceRoot !== root ? sourceRoot : null });
      }
    });
    return fields;
  }

  function currentParts(root) {
    const input = root.querySelector("[data-autocomplete-input]");
    const valueInput = root.querySelector("[data-autocomplete-value]");
    const optionsNode = root.querySelector("[data-autocomplete-options]");
    const endpoint = root.dataset.autocompleteUrl;
    const mode = root.dataset.autocompleteMode === "suggestion" ? "suggestion" : "entity";
    const contextSpec = root.dataset.autocompleteContext || "";
    const requiredSpec = root.dataset.autocompleteRequired || "";
    return { input, valueInput, optionsNode, endpoint, mode, contextSpec, requiredSpec };
  }

  function sameParts(state, parts) {
    return (
      state.input === parts.input &&
      state.valueInput === parts.valueInput &&
      state.optionsNode === parts.optionsNode &&
      state.endpoint === parts.endpoint &&
      state.mode === parts.mode &&
      state.contextSpec === parts.contextSpec &&
      state.requiredSpec === parts.requiredSpec
    );
  }

  function initAutocomplete(root) {
    if (!root) return;
    const parts = currentParts(root);
    const previousState = states.get(root);
    if (previousState && sameParts(previousState, parts)) return;
    if (previousState) destroyState(previousState);
    if (
      !parts.input ||
      !parts.optionsNode ||
      !parts.endpoint ||
      (parts.mode === "entity" && !parts.valueInput)
    ) {
      delete root.dataset.autocompleteInitialized;
      return;
    }

    const state = {
      root,
      ...parts,
      required: root.dataset.autocompleteRequired === "true" || parts.input.required,
      selectedLabel: parts.input.value,
      results: [],
      activeIndex: -1,
      debounceTimer: 0,
      blurTimer: 0,
      requestController: null,
      requestSequence: 0,
      contextBindings: [],
      handlers: {},
    };
    states.set(root, state);
    root.dataset.autocompleteInitialized = "true";

    state.input.setAttribute("role", "combobox");
    state.input.setAttribute("aria-autocomplete", "list");
    state.input.setAttribute("aria-expanded", "false");
    if (state.optionsNode.id) state.input.setAttribute("aria-controls", state.optionsNode.id);
    state.optionsNode.setAttribute("role", "listbox");

    state.handlers.focus = () => {
      window.clearTimeout(state.blurTimer);
      state.blurTimer = 0;
      loadOptions(state);
    };
    state.handlers.input = () => {
      invalidatePending(state);
      if (state.mode === "entity" && state.input.value !== state.selectedLabel) {
        clearSelection(state, { preserveText: true, notify: true, invalidate: false });
      } else if (state.mode === "suggestion" && state.valueInput) {
        state.valueInput.value = state.input.value;
      }
      validateSelection(state);
      scheduleLoad(state);
    };
    state.handlers.keydown = (event) => handleKeydown(state, event);
    state.handlers.blur = () => {
      window.clearTimeout(state.blurTimer);
      state.blurTimer = window.setTimeout(() => invalidatePending(state), 100);
      validateSelection(state);
    };
    state.input.addEventListener("focus", state.handlers.focus);
    state.input.addEventListener("input", state.handlers.input);
    state.input.addEventListener("keydown", state.handlers.keydown);
    state.input.addEventListener("blur", state.handlers.blur);

    contextFields(root).forEach(({ key, field, sourceRoot }) => {
      const handler = () => {
        invalidatePending(state);
        clearSelection(state, { notify: true, invalidate: false });
      };
      field.addEventListener("input", handler);
      field.addEventListener("change", handler);
      sourceRoot?.addEventListener("autocomplete:select", handler);
      sourceRoot?.addEventListener("autocomplete:clear", handler);
      state.contextBindings.push({ key, field, sourceRoot, handler });
    });
    validateSelection(state);
  }

  function closeOptions(state) {
    state.optionsNode.hidden = true;
    state.input.setAttribute("aria-expanded", "false");
    state.activeIndex = -1;
    state.input.removeAttribute("aria-activedescendant");
  }

  function invalidatePending(state, { close = true } = {}) {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = 0;
    state.requestSequence += 1;
    state.requestController?.abort();
    state.requestController = null;
    if (close) closeOptions(state);
  }

  function destroyState(state) {
    invalidatePending(state);
    window.clearTimeout(state.blurTimer);
    state.input.removeEventListener("focus", state.handlers.focus);
    state.input.removeEventListener("input", state.handlers.input);
    state.input.removeEventListener("keydown", state.handlers.keydown);
    state.input.removeEventListener("blur", state.handlers.blur);
    state.contextBindings.forEach(({ field, sourceRoot, handler }) => {
      field.removeEventListener("input", handler);
      field.removeEventListener("change", handler);
      sourceRoot?.removeEventListener("autocomplete:select", handler);
      sourceRoot?.removeEventListener("autocomplete:clear", handler);
    });
    states.delete(state.root);
    delete state.root.dataset.autocompleteInitialized;
  }

  function validateSelection(state) {
    if (state.mode === "suggestion") {
      state.input.setCustomValidity("");
      return;
    }
    const hasTextWithoutEntity = Boolean(state.input.value.trim() && !state.valueInput.value);
    if (hasTextWithoutEntity) {
      state.input.setCustomValidity(
        state.root.dataset.autocompleteSelectionMessage ||
          "Выберите значение из предложенных вариантов."
      );
    } else if (state.required && !state.valueInput.value) {
      state.input.setCustomValidity(
        state.root.dataset.autocompleteRequiredMessage ||
          "Выберите значение из предложенных вариантов."
      );
    } else {
      state.input.setCustomValidity("");
    }
  }

  function clearSelection(
    state,
    { preserveText = false, notify = false, invalidate = true } = {}
  ) {
    if (invalidate) invalidatePending(state);
    const previousValue = state.mode === "entity" ? state.valueInput.value : state.input.value;
    if (state.mode === "entity") state.valueInput.value = "";
    if (state.mode === "suggestion" && state.valueInput) state.valueInput.value = "";
    if (!preserveText) state.input.value = "";
    state.selectedLabel = "";
    validateSelection(state);
    if (notify && previousValue) {
      dispatch(state.root, "autocomplete:clear", { previousValue, mode: state.mode });
    }
  }

  function selectResult(state, rawResult, { notify = true } = {}) {
    const result = normalizeResult(rawResult);
    if (!result) return;
    invalidatePending(state);
    if (state.mode === "entity") {
      state.valueInput.value = result.value;
      state.input.value = result.label;
      state.selectedLabel = result.label;
    } else {
      state.input.value = result.value;
      state.selectedLabel = result.value;
      if (state.valueInput) state.valueInput.value = result.value;
    }
    state.input.setCustomValidity("");
    if (notify) dispatch(state.root, "autocomplete:select", { option: result, mode: state.mode });
  }

  function activateOption(state, index) {
    if (!state.results.length) return;
    state.activeIndex = Math.max(0, Math.min(index, state.results.length - 1));
    state.optionsNode.querySelectorAll("[data-autocomplete-option]").forEach((option, optionIndex) => {
      const active = optionIndex === state.activeIndex;
      option.classList.toggle("active", active);
      option.setAttribute("aria-selected", String(active));
      if (active) {
        state.input.setAttribute("aria-activedescendant", option.id);
        option.scrollIntoView({ block: "nearest" });
      }
    });
  }

  function renderOptions(state, rawItems) {
    state.results = (Array.isArray(rawItems) ? rawItems : [])
      .map(normalizeResult)
      .filter(Boolean)
      .slice(0, 20);
    state.activeIndex = -1;
    state.input.removeAttribute("aria-activedescendant");
    state.optionsNode.replaceChildren();
    if (!state.results.length) {
      const empty = document.createElement("div");
      empty.className = "workorder-autocomplete-empty autocomplete-empty";
      empty.textContent = "Подходящих вариантов нет";
      state.optionsNode.appendChild(empty);
    } else {
      state.results.forEach((result, index) => {
        const option = document.createElement("div");
        option.id = `${state.optionsNode.id || "autocomplete-options"}-option-${index}`;
        option.className = "workorder-autocomplete-option autocomplete-option";
        option.setAttribute("role", "option");
        option.setAttribute("aria-selected", "false");
        option.tabIndex = -1;
        option.dataset.autocompleteOption = "";

        const label = document.createElement("span");
        label.textContent = result.label;
        option.appendChild(label);
        if (result.secondary) {
          const secondary = document.createElement("small");
          secondary.textContent = result.secondary;
          option.appendChild(secondary);
        }
        option.addEventListener("mousedown", (event) => event.preventDefault());
        option.addEventListener("click", () => selectResult(state, result));
        state.optionsNode.appendChild(option);
      });
    }
    state.optionsNode.hidden = false;
    state.input.setAttribute("aria-expanded", "true");
  }

  function requestContext(state) {
    const context = {};
    state.contextBindings.forEach(({ key, field }) => {
      if (field.value) context[key] = field.value;
    });
    return context;
  }

  async function loadOptions(state) {
    invalidatePending(state);
    const controller = new AbortController();
    const sequence = state.requestSequence;
    state.requestController = controller;
    const url = new URL(state.endpoint, window.location.origin);
    url.searchParams.set("q", state.input.value.trim());
    Object.entries(requestContext(state)).forEach(([key, value]) => {
      url.searchParams.set(key, value);
    });
    try {
      const response = await fetch(url, {
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        signal: controller.signal,
        cache: "no-store",
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      if (
        sequence !== state.requestSequence ||
        controller.signal.aborted ||
        states.get(state.root) !== state
      ) return;
      state.requestController = null;
      renderOptions(state, payload.results);
    } catch (error) {
      if (
        error.name === "AbortError" ||
        sequence !== state.requestSequence ||
        states.get(state.root) !== state
      ) return;
      state.requestController = null;
      renderOptions(state, []);
    }
  }

  function scheduleLoad(state) {
    window.clearTimeout(state.debounceTimer);
    state.debounceTimer = window.setTimeout(() => {
      state.debounceTimer = 0;
      loadOptions(state);
    }, 200);
  }

  function handleKeydown(state, event) {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      if (state.optionsNode.hidden) loadOptions(state);
      else activateOption(state, state.activeIndex + 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      if (state.optionsNode.hidden) loadOptions(state);
      else activateOption(state, state.activeIndex <= 0 ? state.results.length - 1 : state.activeIndex - 1);
    } else if (event.key === "Enter" && state.activeIndex >= 0) {
      event.preventDefault();
      selectResult(state, state.results[state.activeIndex]);
    } else if (event.key === "Tab" && state.activeIndex >= 0) {
      selectResult(state, state.results[state.activeIndex]);
    } else if (event.key === "Escape") {
      event.preventDefault();
      invalidatePending(state);
    }
  }

  function init(scope = document) {
    rootsWithin(scope).forEach(initAutocomplete);
  }

  function destroy(scope = document) {
    rootsWithin(scope).forEach((root) => {
      const state = states.get(root);
      if (state) destroyState(state);
    });
  }

  function setSelection(root, option, options = {}) {
    const state = states.get(root);
    if (state) selectResult(state, option, options);
  }

  function clear(root, options = {}) {
    const state = states.get(root);
    if (state) clearSelection(state, options);
  }

  window.LocalBusinessAutocomplete = { init, destroy, setSelection, clear };
  document.addEventListener("DOMContentLoaded", () => init(document));
  document.addEventListener("htmx:beforeCleanupElement", (event) => {
    destroy(event.detail?.elt || event.target);
  });
  document.addEventListener("htmx:afterSwap", (event) => init(event.detail.target || document));
  init(document);
})();
