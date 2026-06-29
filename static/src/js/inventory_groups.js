(function () {
  // Состояние «раскрыт/свёрнут» для каждой группы подразделения
  // и опциональные флаги «Развернуть все / Свернуть все» как режим.
  const STORAGE_KEY = "inventory_device_group_state";
  const ALL_EXPANDED = "__all_expanded__";
  const ALL_COLLAPSED = "__all_collapsed__";

  function readState() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}") || {};
    } catch (error) {
      return {};
    }
  }

  function writeState(state) {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (error) {
      // localStorage может быть недоступен (приватный режим) — молча игнорируем.
    }
  }

  function groups() {
    return Array.from(document.querySelectorAll(".device-group"));
  }

  function persistGroup(group) {
    if (!group || !group.dataset || !group.dataset.departmentId) return;
    const state = readState();
    state[group.dataset.departmentId] = group.open;
    // Любое индивидуальное действие пользователя сбрасывает массовые флаги —
    // иначе «Развернуть все» затирало бы свернутую по одиночке группу.
    delete state[ALL_EXPANDED];
    delete state[ALL_COLLAPSED];
    writeState(state);
  }

  function restore() {
    const state = readState();
    let flag = null;
    if (state[ALL_EXPANDED] === true) flag = true;
    else if (state[ALL_COLLAPSED] === true) flag = false;

    groups().forEach((group) => {
      let open;
      if (flag !== null) {
        open = flag;
      } else if (typeof state[group.dataset.departmentId] === "boolean") {
        open = state[group.dataset.departmentId];
      } else {
        // По умолчанию группы свёрнуты.
        open = false;
      }
      group.open = open;
    });
  }

  function bulk(open) {
    const state = readState();
    groups().forEach((group) => {
      group.open = open;
      if (group.dataset.departmentId) {
        state[group.dataset.departmentId] = open;
      }
    });
    state[ALL_EXPANDED] = open ? true : undefined;
    state[ALL_COLLAPSED] = open ? undefined : true;
    // Чистим undefined-ключи, чтобы JSON оставался компактным.
    if (state[ALL_EXPANDED] === undefined) delete state[ALL_EXPANDED];
    if (state[ALL_COLLAPSED] === undefined) delete state[ALL_COLLAPSED];
    writeState(state);
  }

  function init() {
    // Маркер data-inventory-groups есть и на панели кнопок, и на корне списка.
    const hasControls = document.querySelector("[data-inventory-groups][data-inventory-action], [data-inventory-groups] [data-inventory-action]");
    const anyGroup = document.querySelector(".device-group");
    if (!anyGroup && !hasControls) return;

    restore();

    // Глобальный capture-listener перехватывает toggle у любого <details>
    // с классом device-group, в том числе динамически добавленного.
    document.addEventListener(
      "toggle",
      (event) => {
        const target = event.target;
        if (
          target &&
          target.classList &&
          target.classList.contains("device-group") &&
          target.dataset &&
          target.dataset.departmentId
        ) {
          persistGroup(target);
        }
      },
      true
    );

    document.querySelectorAll("[data-inventory-action]").forEach((button) => {
      button.addEventListener("click", (event) => {
        event.preventDefault();
        const action = button.dataset.inventoryAction;
        bulk(action === "expand");
      });
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();