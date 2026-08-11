(function () {
  "use strict";

  function bindMask(input, formatter) {
    if (!input || input.dataset.maskReady === "true") return;
    input.dataset.maskReady = "true";
    input.addEventListener("input", function () { formatter(input); });
  }

  function initPanel(panel) {
    if (!panel || panel.dataset.cardEditingReady === "true") return;
    panel.dataset.cardEditingReady = "true";
    var saveButton = panel.querySelector("[data-waiting-list-save]");

    function activateCard(card) {
      if (!card) return;
      card.classList.add("is-editing");
      var toggle = card.querySelector("[data-edit-card-toggle]");
      if (toggle) toggle.setAttribute("aria-expanded", "true");
      if (saveButton) saveButton.hidden = false;
    }

    panel.querySelectorAll("[data-edit-card]").forEach(function (card) {
      if (card.classList.contains("is-editing")) activateCard(card);
      var toggle = card.querySelector("[data-edit-card-toggle]");
      if (!toggle) return;
      toggle.addEventListener("click", function () {
        activateCard(card);
        var firstField = card.querySelector('input:not([type="hidden"]), select, textarea');
        if (firstField) firstField.focus();
      });
    });

    var form = panel.querySelector("[data-waiting-list-inline-form]");
    if (!form) return;
    bindMask(form.querySelector('input[name="patient_phone"]'), function (input) {
      var value = input.value.replace(/\D/g, "").slice(0, 11);
      if (!value.length) return;
      var formatted = "+7";
      if (value.length > 1) formatted += " (" + value.substring(1, 4);
      if (value.length > 4) formatted += ") " + value.substring(4, 7);
      if (value.length > 7) formatted += "-" + value.substring(7, 9);
      if (value.length > 9) formatted += "-" + value.substring(9, 11);
      input.value = formatted;
    });
    bindMask(form.querySelector('input[name="patient_dob"]'), function (input) {
      var value = input.value.replace(/\D/g, "").slice(0, 8);
      if (value.length >= 5) input.value = value.slice(0, 2) + "." + value.slice(2, 4) + "." + value.slice(4);
      else if (value.length >= 3) input.value = value.slice(0, 2) + "." + value.slice(2);
      else input.value = value;
    });
  }

  function init(root) {
    var scope = root && root.querySelectorAll ? root : document;
    if (scope.matches && scope.matches("[data-waiting-list-detail]")) initPanel(scope);
    scope.querySelectorAll("[data-waiting-list-detail]").forEach(initPanel);
  }

  window.LocalBusinessWaitingListCards = { init: init };
  document.addEventListener("DOMContentLoaded", function () { init(document); });
  document.addEventListener("htmx:afterSwap", function (event) {
    init(event.detail && event.detail.target ? event.detail.target : document);
  });
})();
