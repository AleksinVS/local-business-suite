(() => {
  const form = document.getElementById("role-rules-form");
  if (!form) return;

  const summary = document.getElementById("access-preview-summary");
  const list = document.getElementById("access-preview-list");
  const confirmation = document.getElementById("sensitive-confirmation");
  const confirmInput = document.getElementById("confirm-sensitive-changes");
  const roleMemberIdsElement = document.getElementById("role-member-ids");
  const roleMemberIds = roleMemberIdsElement ? JSON.parse(roleMemberIdsElement.textContent) : {};
  const controls = Array.from(form.querySelectorAll("[data-role-capability]"));
  const descriptions = Array.from(form.querySelectorAll("[data-capability-description]"));

  const controlValue = (control) => (
    control.dataset.capabilityType === "flag" ? String(control.checked) : control.value.trim()
  );

  const updatePreview = () => {
    const changes = [];
    const affectedRoles = new Map();
    let hasCriticalChange = false;

    controls.forEach((control) => {
      if (controlValue(control) === control.dataset.original) return;
      const card = control.closest("[data-role-name]");
      const roleName = control.dataset.roleLabel;
      const capabilityName = control.dataset.capabilityLabel;
      const isFlag = control.dataset.capabilityType === "flag";
      const action = isFlag
        ? (control.checked ? "выдано" : "отозвано")
        : "изменено";
      const risk = control.dataset.risk || "normal";
      changes.push({ text: `${roleName}: «${capabilityName}» — ${action}.`, risk });
      affectedRoles.set(card.dataset.roleName, roleName);
      hasCriticalChange ||= control.dataset.requiresConfirmation === "true";
    });

    descriptions.forEach((field) => {
      if (field.value.trim() === field.dataset.original) return;
      changes.push({ text: `Описание права «${field.dataset.capabilityLabel}» изменено.`, risk: "normal" });
    });

    list.replaceChildren();
    changes.forEach((change) => {
      const item = document.createElement("li");
      item.textContent = change.text;
      item.dataset.risk = change.risk;
      list.append(item);
    });

    if (!changes.length) {
      summary.textContent = "Изменений пока нет.";
    } else {
      const uniqueAffectedUsers = new Set(
        [...affectedRoles.keys()].flatMap((roleName) => roleMemberIds[roleName] || [])
      );
      const affected = [...affectedRoles.values()].join(", ");
      summary.textContent = `Изменений: ${changes.length}. Затронутые сотрудники: ${uniqueAffectedUsers.size} (роли: ${affected || "нет"}).`;
    }

    confirmation.hidden = !hasCriticalChange;
    if (!hasCriticalChange) confirmInput.checked = false;
  };

  controls.concat(descriptions).forEach((element) => {
    element.addEventListener("change", updatePreview);
    element.addEventListener("input", updatePreview);
  });

  form.addEventListener("submit", (event) => {
    if (!confirmation.hidden && !confirmInput.checked) {
      event.preventDefault();
      confirmInput.focus();
    }
  });

  updatePreview();
})();
