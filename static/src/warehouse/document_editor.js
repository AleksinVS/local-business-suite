(function () {
  "use strict";

  function editor(root) {
    if (!root || root.dataset.documentEditorInitialized === "true") return;
    root.dataset.documentEditorInitialized = "true";
    var form = root.querySelector("[data-warehouse-document-editor] > form") || root.querySelector("form[data-right-panel-form]");
    if (!form) return;
    var body = root.querySelector("[data-document-lines-body]");
    var total = form.querySelector("[name$='-TOTAL_FORMS']");
    var type = form.querySelector("[name='document_type']");
    if (!body || !total) return;

    function setOperationColumns() {
      var value = type ? type.value : "";
      root.querySelectorAll(".line-source-column").forEach(function (cell) {
        cell.hidden = ["opening", "receipt"].indexOf(value) !== -1;
      });
      root.querySelectorAll(".line-destination-column").forEach(function (cell) {
        cell.hidden = ["issue", "writeoff"].indexOf(value) !== -1;
      });
      root.querySelectorAll(".line-fefo-column").forEach(function (cell) {
        cell.hidden = value !== "issue";
      });
      var reason = root.querySelector(".operation-reason-field");
      if (reason) reason.hidden = ["writeoff", "adjustment"].indexOf(value) === -1;
      root.querySelectorAll("[data-document-line-row]").forEach(function (row) {
        row.querySelectorAll(".line-source-column input, .line-destination-column input").forEach(function (input) {
          input.disabled = input.closest(".line-source-column")?.hidden || input.closest(".line-destination-column")?.hidden;
        });
      });
    }

    function clearClone(row, index) {
      row.querySelectorAll("input, textarea, select").forEach(function (input) {
        if (input.name) input.name = input.name.replace(/-\d+-/, "-" + index + "-");
        if (input.id) input.id = input.id.replace(/-\d+-/, "-" + index + "-");
        if (input.type === "hidden" && /-id$/.test(input.name || "")) input.value = "";
        else if (input.type === "hidden" && /sequence/.test(input.name || "")) input.value = "";
        else if (input.type === "checkbox") input.checked = false;
        else input.value = "";
      });
      // The shared autocomplete client resolves context selectors relative to
      // the form.  Reindex every selector-bearing row, not just input names,
      // otherwise a cloned row keeps reading the first row's item/series.
      row.querySelectorAll("[data-autocomplete-context]").forEach(function (node) {
        var raw = node.getAttribute("data-autocomplete-context") || "";
        node.setAttribute("data-autocomplete-context", raw.replace(/lines-\d+-/g, "lines-" + index + "-"));
      });
      row.querySelectorAll("[id]").forEach(function (node) {
        node.id = node.id.replace(/-\d+-/, "-" + index + "-");
      });
      row.querySelectorAll("[data-autocomplete-input]").forEach(function (input) { input.value = ""; });
      row.querySelectorAll("[data-autocomplete-options]").forEach(function (node) { node.replaceChildren(); node.hidden = true; });
      row.querySelectorAll(".errorlist").forEach(function (node) { node.remove(); });
      delete row.dataset.persisted;
      row.dataset.documentLineRow = "";
    }

    function addLine() {
      var source = [...body.querySelectorAll("[data-document-line-row]")].find(function (row) { return !row.hidden; }) || body.querySelector("[data-document-line-row]");
      if (!source) return;
      var index = Number(total.value || body.children.length);
      var clone = source.cloneNode(true);
      clearClone(clone, index);
      clone.hidden = false;
      body.appendChild(clone);
      total.value = String(index + 1);
      window.LocalBusinessAutocomplete?.init(clone);
      setOperationColumns();
      clone.querySelector("[data-autocomplete-input], input:not([type='hidden']), select")?.focus();
    }

    root.querySelector("[data-add-document-line]")?.addEventListener("click", addLine);
    body.addEventListener("click", function (event) {
      var button = event.target.closest("[data-remove-document-line]");
      if (!button) return;
      var row = button.closest("[data-document-line-row]");
      if (!row) return;
      var deleted = row.querySelector("input[name$='-DELETE']");
      if (deleted && row.dataset.persisted === "true") {
        deleted.checked = true;
        row.hidden = true;
      } else if (body.children.length > 1) row.remove();
      else row.querySelectorAll("input:not([type='hidden']), textarea").forEach(function (input) { input.value = ""; });
    });
    type?.addEventListener("change", setOperationColumns);
    root.addEventListener("autocomplete:select", function (event) {
      var selected = event.detail?.option?.metadata || {};
      var fieldRoot = event.target.closest?.("[data-autocomplete]");
      var row = fieldRoot?.closest?.("[data-document-line-row]");
      if (!row) return;
      var endpoint = fieldRoot?.dataset.autocompleteUrl || "";
      function fillEntity(urlPart, value, label) {
        if (!value) return;
        row.querySelectorAll("[data-autocomplete]").forEach(function (candidate) {
          if ((candidate.dataset.autocompleteUrl || "").indexOf(urlPart) === -1) return;
          var hidden = candidate.querySelector("[data-autocomplete-value]");
          var input = candidate.querySelector("[data-autocomplete-input]");
          if (hidden) hidden.value = String(value);
          if (input) input.value = String(label || value);
        });
      }
      if (endpoint.indexOf("autocomplete/item") !== -1 && selected.unit_label) {
        var unit = row.querySelector("[data-line-unit]");
        if (unit) unit.textContent = String(selected.unit_label);
        var quantity = row.querySelector("input[name$='-quantity']");
        if (quantity) quantity.dataset.unitLabel = String(selected.unit_label);
        if (selected.expires_on) {
          var itemExpiry = row.querySelector("input[name$='-expires_on']");
          if (itemExpiry) itemExpiry.value = selected.expires_on;
        }
      }
      if (endpoint.indexOf("autocomplete/series") !== -1 && selected.expires_on) {
        var expiry = row.querySelector("input[name$='-expires_on']");
        if (expiry) expiry.value = selected.expires_on;
      }
      if (selected.source_location_id) fillEntity("autocomplete/location", selected.source_location_id, selected.source_location_label);
      if (selected.funding_source_id) fillEntity("autocomplete/source", selected.funding_source_id, selected.funding_source_label);
      setOperationColumns();
    });
    setOperationColumns();
    window.LocalBusinessAutocomplete?.init(root);
  }

  function init(scope) {
    (scope || document).querySelectorAll?.("[data-warehouse-document-editor]").forEach(editor);
  }
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:afterSwap", function (event) { init(event.detail?.target || document); });
  init(document);
})();
