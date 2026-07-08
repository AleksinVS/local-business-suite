/*
 * filter_overflow.js — адаптивная панель фильтров по паттерну priority+
 * (Brad Frost "priority plus" / overflow-menu), с двумя стадиями.
 *
 * Всегда включён (git-level rollback: `git revert` коммита откатывает файл,
 * CSS-блок .filters--adaptive и правки шаблонов). Контролы физически остаются
 * потомками того же <form>, поэтому GET/HTMX submit и связки <label for>
 * сохраняются при переносе.
 *
 * СТАДИЯ 1 (широкие экраны): контролы держат ширину; когда полный набор не
 * помещается, ВСЕ фильтры (multi-filter dropdown'ы) уезжают в «Ещё фильтры ▾»
 * целиком. Снаружи остаются поиск, выбор доски, переключатель вида и кнопки
 * действия; поиск сжимается по ширине, чтобы остальное влезло в одну строку.
 *
 * СТАДИЯ 2 (узкие/мобильные): панель сворачивается в ряд иконок. Для доски:
 * поиск, выбор доски, переключатель вида (пиктограммы «Доска»/«Дерево»),
 * «Ещё фильтры» (воронка — держит только multi-filter dropdown'ы) и кнопка
 * «Создать заявку». Поиск сжимается, остальное — иконки.
 * На остальных страницах состав подбирается по тем же принципам: самые важные
 * контролы остаются иконками, остальное — в воронку. Все подписи заменяются
 * пиктограммами (inline SVG), каждый icon-only контрол сохраняет доступное имя
 * (aria/label + title с исходным русским текстом).
 *
 * Итог: ровно одна видимая строка на любой ширине, без горизонтальной
 * прокрутки и без обрезанных поповеров.
 */
(function () {
  "use strict";

  var COLLAPSE_BP = 768; // innerWidth < этого => стадия 2 (компактный icon-режим)
  var LABEL_MORE = "Ещё фильтры";

  var ICONS = {
    search:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>',
    board:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="5" height="16" rx="1"/><rect x="10" y="4" width="5" height="16" rx="1"/><rect x="17" y="4" width="4" height="16" rx="1"/></svg>',
    funnel:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 5h18l-7 8v6l-4 2v-8z"/></svg>',
    plus:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>',
    tree:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="3" width="6" height="5" rx="1"/><rect x="3" y="16" width="6" height="5" rx="1"/><rect x="15" y="16" width="6" height="5" rx="1"/><path d="M12 8v3.5M6 16v-2h12v2"/></svg>',
    expand:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="7 13 12 18 17 13"/><polyline points="7 6 12 11 17 6"/></svg>',
    collapse:
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="7 11 12 6 17 11"/><polyline points="7 18 12 13 17 18"/></svg>'
  };

  function iconSpan(name, cls) {
    var span = document.createElement("span");
    span.className = cls;
    span.setAttribute("aria-hidden", "true");
    span.innerHTML = ICONS[name] || "";
    return span;
  }

  function roleOf(el) {
    if (el.classList.contains("input-group--search")) return "search";
    if (el.hasAttribute("data-filter-board")) return "board";
    if (el.classList.contains("input-group--dropdown")) return "dropdown";
    if (el.classList.contains("view-switcher-group")) return "view";
    if (el.classList.contains("checkbox-group")) return "checkbox";
    return "plain";
  }

  function priorityOf(role, el) {
    if (el.dataset && el.dataset.filterPriority) {
      var n = Number(el.dataset.filterPriority);
      if (!Number.isNaN(n)) return n;
    }
    switch (role) {
      case "search": return 100;
      case "view": return 40;
      case "board": return 35;
      case "plain": return 30;
      case "checkbox": return 20;
      default: return 10; // dropdown
    }
  }

  function isSubmitBtn(el) {
    if (el.tagName === "BUTTON") {
      var bt = (el.getAttribute("type") || "submit").toLowerCase();
      return bt === "submit" || bt === "reset";
    }
    if (el.tagName === "INPUT") {
      var it = (el.getAttribute("type") || "").toLowerCase();
      return it === "submit" || it === "reset";
    }
    return false;
  }

  function isSkippable(el) {
    if (el.nodeType !== 1) return true;
    if (el.tagName === "INPUT" && (el.getAttribute("type") || "").toLowerCase() === "hidden") return true;
    return false;
  }

  function Controller(form) {
    this.form = form;
    this.toolbar = form.closest(".toolbar") || form.parentElement;
    this.items = [];       // перемещаемые фильтр-контролы
    this.pinned = [];      // submit/reset внутри формы (в стадии 1 всегда в строке)
    this.managedOrder = []; // порядок узлов для DOM-перестановки (items + submit)
    this.gap = 0;
    this.triggerW = 0;
    this.key = null;
    this.build();
  }

  Controller.prototype.build = function () {
    var self = this;
    var children = Array.prototype.slice.call(this.form.children);
    children.forEach(function (el) {
      if (isSkippable(el)) return;
      if (isSubmitBtn(el)) {
        self.pinned.push({ el: el, w: 0, isSubmit: true });
        return;
      }
      var role = roleOf(el);
      self.items.push({ el: el, role: role, priority: priorityOf(role, el), w: 0, index: self.items.length });
    });
    if (this.items.length === 0) return;
    this.toolbar.classList.add("toolbar--adaptive");

    // Лид-иконки для поиска и выбора доски (видны только в компактном режиме).
    this.items.forEach(function (it) {
      if (it.role === "search" || it.role === "board") {
        var iconName = it.role === "search" ? "search" : "board";
        var label = it.el.querySelector("label");
        var titleText = label ? label.textContent.trim() : (it.role === "search" ? "Поиск" : "Доска");
        var control = it.el.querySelector("input, select");
        if (control && !control.getAttribute("title")) control.setAttribute("title", titleText);
        it.el.insertBefore(iconSpan(iconName, "filter-lead-icon"), it.el.firstChild);
      }
    });

    // Переключатель вида остаётся снаружи «Ещё фильтры»; его опции показываются
    // пиктограммами в компактном режиме (текст скрыт, но сохранён для a11y+title).
    this.items.forEach(function (it) {
      if (it.role !== "view") return;
      var opts = it.el.querySelectorAll(".segmented-option");
      Array.prototype.forEach.call(opts, function (opt) {
        var target = (opt.dataset && opt.dataset.workorderViewTarget) || "";
        var iconName = target === "tree" ? "tree" : "board";
        var text = opt.textContent.replace(/\s+/g, " ").trim();
        if (!opt.getAttribute("title")) opt.setAttribute("title", text);
        var lbl = document.createElement("span");
        lbl.className = "filter-btn-label";
        lbl.textContent = text;
        opt.replaceChildren(iconSpan(iconName, "filter-btn-icon"), lbl);
      });
    });

    // Overflow-триггер: нативный <details> — доступен с клавиатуры, каретка/стили
    // наследуются от .multi-filter-dropdown.
    var overflow = document.createElement("details");
    overflow.className = "multi-filter-dropdown filters-overflow";
    overflow.setAttribute("hidden", "");
    var summary = document.createElement("summary");
    summary.setAttribute("title", LABEL_MORE);
    summary.appendChild(iconSpan("funnel", "filters-overflow-icon"));
    var label = document.createElement("span");
    label.className = "filters-overflow-label";
    label.textContent = LABEL_MORE;
    summary.appendChild(label);
    var badge = document.createElement("strong");
    badge.className = "filters-overflow-count";
    badge.hidden = true;
    summary.appendChild(badge);
    overflow.appendChild(summary);
    var menu = document.createElement("div");
    menu.className = "multi-filter-menu filters-overflow-menu";
    overflow.appendChild(menu);

    var firstSubmit = this.pinned.length ? this.pinned[0].el : null;
    if (firstSubmit) this.form.insertBefore(overflow, firstSubmit);
    else this.form.appendChild(overflow);

    this.overflow = overflow;
    this.overflowLabel = label;
    this.overflowBadge = badge;
    this.menu = menu;

    // managedOrder: сначала фильтр-контролы в исходном порядке, затем submit.
    this.items.forEach(function (it) { self.managedOrder.push(it); });
    this.pinned.forEach(function (p) { self.managedOrder.push(p); });
    this.managedOrder.forEach(function (node, i) { node.el.dataset.foIndex = String(i); });

    // Кнопки действий тулбара (вне формы): иконки на компактной стадии.
    var allBtns = this.toolbar.querySelectorAll(".btn");
    Array.prototype.forEach.call(allBtns, function (btn) {
      if (self.form.contains(btn)) return; // submit формы — не трогаем
      var name = "plus";
      if (btn.dataset && btn.dataset.inventoryAction === "expand") name = "expand";
      else if (btn.dataset && btn.dataset.inventoryAction === "collapse") name = "collapse";
      self.decorateButton(btn, name);
    });

    this.measure();
    this.relayout();

    if (typeof ResizeObserver !== "undefined") {
      this.ro = new ResizeObserver(function () { self.schedule(); });
      this.ro.observe(this.form);
    }
    window.addEventListener("resize", function () { self.schedule(); });
    window.addEventListener("load", function () { self.measure(); self.relayout(); });
  };

  // Оборачивает текст кнопки в .filter-btn-label и добавляет icon-only иконку;
  // текст остаётся в DOM (доступное имя) + title-подсказка.
  Controller.prototype.decorateButton = function (btn, iconName) {
    var text = btn.textContent.replace(/\s+/g, " ").trim();
    if (!btn.getAttribute("title")) btn.setAttribute("title", text);
    var label = document.createElement("span");
    label.className = "filter-btn-label";
    label.textContent = text;
    btn.replaceChildren(iconSpan(iconName, "filter-btn-icon"), label);
  };

  Controller.prototype.schedule = function () {
    if (this._raf) return;
    var self = this;
    this._raf = window.requestAnimationFrame(function () {
      self._raf = null;
      self.relayout();
    });
  };

  Controller.prototype.measure = function () {
    var self = this;
    this.toolbar.classList.remove("filters-collapsed");
    // Все контролы в строку перед триггером для замера естественной ширины.
    this.items.forEach(function (it) { self.form.insertBefore(it.el, self.overflow); });
    this.pinned.forEach(function (p) { self.form.appendChild(p.el); });
    // Поиск меряем в СЖАТОМ виде (узкий input), чтобы раскладка держала контролы
    // в строке, а сжимался именно поиск (по требованию владельца).
    var searchEls = this.items.filter(function (it) { return it.role === "search"; });
    searchEls.forEach(function (it) {
      var input = it.el.querySelector("input");
      it._savedW = input ? input.style.width : null;
      if (input) input.style.width = "40px";
      it.el.style.flex = "0 0 auto";
    });
    void this.form.offsetWidth;
    this.items.forEach(function (it) { it.w = it.el.getBoundingClientRect().width; });
    searchEls.forEach(function (it) {
      var input = it.el.querySelector("input");
      if (input) input.style.width = it._savedW || "";
      it.el.style.flex = "";
    });
    this.pinned.forEach(function (p) { p.w = p.el.getBoundingClientRect().width; });

    var wasHidden = this.overflow.hasAttribute("hidden");
    this.overflow.removeAttribute("hidden");
    this.triggerW = this.overflow.getBoundingClientRect().width;
    if (wasHidden) this.overflow.setAttribute("hidden", "");

    var cs = getComputedStyle(this.form);
    this.gap = parseFloat(cs.columnGap || cs.gap) || 0;

    // Ширина строки, доступная форме = ширина тулбара минус padding и минус
    // «хвостовой» кластер (кнопки действий / group-controls) в ТЕКСТОВОМ виде.
    // Считаем её независимо от режима (иконки в компактном режиме сужают хвост),
    // иначе решение compact/wide зациклится.
    var tbcs = getComputedStyle(this.toolbar);
    this.tbGap = parseFloat(tbcs.columnGap || tbcs.gap) || 0;
    this.padH = (parseFloat(tbcs.paddingLeft) || 0) + (parseFloat(tbcs.paddingRight) || 0);
    var trailing = Array.prototype.slice.call(this.toolbar.children).filter(function (c) { return c !== self.form; });
    var reserve = 0, count = 0;
    trailing.forEach(function (c) {
      var r = c.getBoundingClientRect();
      if (r.width > 0.5) { reserve += r.width; count += 1; }
    });
    this.trailingReserve = reserve + this.tbGap * count;
  };

  Controller.prototype.widthNeeded = function (rowItems, showTrigger) {
    var parts = [];
    rowItems.forEach(function (it) { parts.push(it.w); });
    if (showTrigger) parts.push(this.triggerW);
    this.pinned.forEach(function (p) { parts.push(p.w); });
    if (parts.length === 0) return 0;
    var sum = 0;
    for (var i = 0; i < parts.length; i++) sum += parts[i];
    return sum + this.gap * (parts.length - 1);
  };

  Controller.prototype.relayout = function () {
    if (!this.overflow) return;
    if (!this.toolbar.clientWidth) return;
    if (this.items.some(function (it) { return !it.w; })) this.measure();

    // Место под фильтры (стабильно, не зависит от текущего режима).
    var available = this.toolbar.clientWidth - this.padH - this.trailingReserve;
    if (!(available > 0)) available = this.form.clientWidth;

    // Стадия 2 (компакт), если экран узкий ИЛИ даже минимальный набор
    // (поиск + submit-кнопки формы + воронка) не помещается в стадии 1.
    var pinItems = this.items.filter(function (it) { return it.role === "search" || it.role === "board" || it.role === "view"; });
    var forceCompact = window.innerWidth < COLLAPSE_BP;
    if (!forceCompact && this.widthNeeded(pinItems, true) > available) forceCompact = true;

    if (forceCompact) this.planCompact();
    else this.planWide(available);
  };

  Controller.prototype.planWide = function (width) {
    // Пинуются поиск, выбор доски и переключатель вида. Фильтры (multi-filter
    // dropdown'ы) уходят в «Ещё фильтры» ЦЕЛИКОМ, как только полный набор не
    // помещается, без частичного показа отдельных фильтров (по требованию владельца).
    var menuNodes = [];
    var funnelVisible;
    if (this.widthNeeded(this.items, false) <= width) {
      funnelVisible = false;
    } else {
      this.items.forEach(function (it) {
        if (it.role !== "search" && it.role !== "board" && it.role !== "view") menuNodes.push(it.el);
      });
      funnelVisible = true;
    }
    this.apply(menuNodes, funnelVisible, "wide");
  };

  Controller.prototype.planCompact = function () {
    var self = this;
    var menuNodes = [];
    // В воронку уходит всё, кроме поиска, выбора доски и переключателя вида;
    // затем submit формы.
    this.items.forEach(function (it) {
      if (it.role !== "search" && it.role !== "board" && it.role !== "view") menuNodes.push(it.el);
    });
    this.pinned.forEach(function (p) { menuNodes.push(p.el); });
    this.apply(menuNodes, true, "compact");
  };

  Controller.prototype.apply = function (menuNodes, funnelVisible, mode) {
    var menuSet = new Set(menuNodes);
    var key = mode + "|" + (funnelVisible ? 1 : 0) + "|" +
      menuNodes.map(function (el) { return el.dataset.foIndex; }).sort().join(",");
    if (key === this.key) return;
    this.key = key;

    var self = this;
    // Строчные (не в меню) — в исходном порядке: фильтры перед триггером, submit после.
    this.managedOrder.forEach(function (node) {
      var el = node.el;
      if (menuSet.has(el)) return;
      if (node.isSubmit) self.form.appendChild(el);
      else self.form.insertBefore(el, self.overflow);
    });
    // Узлы меню — в заданном порядке.
    menuNodes.forEach(function (el) { self.menu.appendChild(el); });

    var filterCount = 0;
    menuNodes.forEach(function (el) {
      if (!(el.tagName === "BUTTON" || el.tagName === "INPUT")) filterCount++;
    });

    if (funnelVisible) {
      this.overflow.removeAttribute("hidden");
      this.overflowBadge.textContent = String(filterCount);
      this.overflowBadge.hidden = filterCount === 0;
    } else {
      this.overflow.removeAttribute("open");
      this.overflow.setAttribute("hidden", "");
      this.overflowBadge.hidden = true;
    }

    this.toolbar.classList.toggle("filters-collapsed", mode === "compact");
  };

  function init() {
    var forms = document.querySelectorAll("form.filters--adaptive");
    Array.prototype.forEach.call(forms, function (form) {
      if (form.__filterOverflow) return;
      form.__filterOverflow = new Controller(form);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
