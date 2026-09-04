(function () {
  "use strict";

  function initializeSelection(root) {
    if (!root || root.dataset.relocationInitialized === "true") return;
    root.dataset.relocationInitialized = "true";
    var actions = root.querySelector("[data-relocation-actions]");
    var count = root.querySelector("[data-relocation-count]");
    var submit = root.querySelector("[data-relocation-submit]");

    function refresh() {
      var selected = root.querySelectorAll("[data-relocation-select]:checked");
      root.querySelectorAll("[data-relocation-row]").forEach(function (row) {
        var checkbox = row.querySelector("[data-relocation-select]");
        var quantity = row.querySelector("[data-relocation-quantity]");
        var enabled = Boolean(checkbox && checkbox.checked);
        if (!quantity) return;
        quantity.disabled = !enabled;
        quantity.required = enabled;
        if (!enabled) quantity.value = "";
      });
      if (count) count.textContent = String(selected.length);
      if (actions) actions.hidden = selected.length === 0;
      if (submit) submit.disabled = selected.length === 0;
    }

    root.addEventListener("change", function (event) {
      if (event.target.matches("[data-relocation-select]")) refresh();
    });
    root.addEventListener("submit", function (event) {
      refresh();
      if (!root.querySelector("[data-relocation-select]:checked")) {
        event.preventDefault();
      }
    });
    refresh();
  }

  function initializeDestination(panel) {
    if (!panel || panel.dataset.relocationDestinationInitialized === "true") return;
    panel.dataset.relocationDestinationInitialized = "true";
    var destination = panel.querySelector("[data-relocation-destination]");
    var location = panel.querySelector("[data-relocation-location]");
    var locationGroup = panel.querySelector("[data-relocation-location-group]");
    if (!destination || !location || !locationGroup) return;

    function clearLocation() {
      var value = location.querySelector("[data-autocomplete-value]");
      var input = location.querySelector("[data-autocomplete-input]");
      if (value) value.value = "";
      if (input) input.value = "";
    }

    destination.addEventListener("autocomplete:select", function (event) {
      var metadata = event.detail?.option?.metadata || {};
      clearLocation();
      if (metadata.default_location_id) {
        var value = location.querySelector("[data-autocomplete-value]");
        var input = location.querySelector("[data-autocomplete-input]");
        if (value) value.value = String(metadata.default_location_id);
        if (input) input.value = String(metadata.default_location_label || "");
        locationGroup.hidden = true;
      } else {
        locationGroup.hidden = false;
      }
    });
    destination.addEventListener("autocomplete:clear", function () {
      clearLocation();
      locationGroup.hidden = false;
    });
  }

  function openRelocationPanel() {
    var panel = document.getElementById("global-right-panel");
    var overlay = document.getElementById("globalRightPanelOverlay");
    if (!document.querySelector("[data-relocation-panel]") || !panel) return;
    panel.classList.remove("drawer-large", "drawer-waiting-list");
    panel.classList.add("drawer-workspace", "active");
    panel.setAttribute("aria-hidden", "false");
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-modal", "true");
    panel.dataset.rightPanelMode = "create";
    overlay?.classList.add("active");
    document.querySelector(".app-layout")?.setAttribute("inert", "");
    initializeDestination(document.querySelector("[data-relocation-panel]"));
  }

  function initialize(scope) {
    var form = scope.matches?.("[data-relocation-selection]")
      ? scope
      : scope.querySelector?.("[data-relocation-selection]");
    if (form) initializeSelection(form);
    var panel = scope.matches?.("[data-relocation-panel]")
      ? scope
      : scope.querySelector?.("[data-relocation-panel]");
    if (panel) initializeDestination(panel);
  }

  document.addEventListener("DOMContentLoaded", function () { initialize(document); });
  document.body.addEventListener("warehouseRelocationPanelReady", openRelocationPanel);
  document.body.addEventListener("warehouseStockChanged", function () {
    window.location.reload();
  });
  document.addEventListener("htmx:afterSwap", function (event) {
    initialize(event.detail?.target || document);
  });
})();
