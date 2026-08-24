import { expect, test, type Page } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const targetUsername = process.env.E2E_ACCESS_TARGET_USERNAME || username;

async function login(page: Page) {
  expect(username, "Set E2E_USERNAME to an active superuser.").toBeTruthy();
  expect(password, "Set E2E_PASSWORD for the superuser.").toBeTruthy();
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/accounts\/login\//);
}

async function closeAccessPanels(page: Page) {
  for (let index = 0; index < 3; index += 1) {
    const close = page.locator("[data-access-panel]:not([inert]) .access-panel-close").first();
    if (await close.count() === 0) return;
    await close.click();
    await expect(page.locator("[data-access-panel]:not([inert]) .access-panel-close")).toHaveCount(0);
  }
}

async function expectAccessRequestIdle(page: Page) {
  await expect(page.locator(".access-context-form.htmx-request, .access-context-form[aria-busy='true']")).toHaveCount(0);
  await expect(page.locator("#access-field-sidebar-host.htmx-request, #access-field-sidebar-host[aria-busy='true'], #access-inspector-host.htmx-request, #access-inspector-host[aria-busy='true']")).toHaveCount(0);
}

test("@smoke access workspace exposes the six access cuts and master-detail panels", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");

  await expect(page).toHaveURL(/\/settings\/access\//);
  await expect(page.locator(".access-tab")).toHaveCount(6);
  await expect(page.locator(".access-users-table thead th")).toHaveCount(8);
  await expect(page.locator(".access-users-table thead")).not.toContainText("Пользователь AD");

  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  let documentNavigationBaseline = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  const targetRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await expect(targetRow).toBeVisible();
  await expect(targetRow.locator(".access-user-identity .access-object-link strong")).toBeVisible();
  await expect(targetRow.locator(".access-user-identity .access-ad-identity")).toBeVisible();

  await targetRow.locator(".access-object-link").click();
  await expect(page.locator(".access-inspector")).toBeVisible();
  await expect(page.locator(".access-inspector")).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".access-table-panel")).toHaveAttribute("inert", "");
  await expect(page.getByText("Основные данные")).toBeVisible();
  await expect(page.locator("[data-access-bundle-form]")).toBeVisible();
  const baselineNavigation = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  await page.locator("[data-access-bundle-form] [data-editor-tab='ad']").click();
  await expect(page.locator("[data-access-bundle-form] [data-editor-group='ad']")).toBeVisible();
  await page.locator("[data-access-bundle-form] [data-editor-tab='roles']").click();
  await expect(page.locator("[data-access-bundle-form] [data-editor-group='roles']")).toBeVisible();
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(baselineNavigation);

  await page.locator(".access-inspector .access-panel-close").click();
  const reopenedTargetRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await reopenedTargetRow.locator(".access-ad-identity").click();
  await expect(page.locator(".access-sidebar-editor")).toBeVisible();
  await expect(page.locator("#sidebar")).not.toHaveClass(/collapsed/);
  await expect(page.locator(".access-sidebar-editor").getByRole("heading", { name: /Связь с Active Directory|Поле объекта/ })).toBeVisible();

  await closeAccessPanels(page);
  await page.getByRole("link", { name: "Роли", exact: true }).click();
  await expect(page.locator(".access-roles-table thead th")).toHaveCount(4);
  const roleRow = page.locator(".access-roles-table tbody tr").first();
  await roleRow.locator(".access-object-link").click();
  await expect(page.locator(".access-inspector")).toBeVisible();
  await page.locator(".access-inspector .access-panel-close").click();
  await page.locator(".access-roles-table tbody tr").first().locator(".access-cell-link").last().click();
  await expect(page.locator(".access-sidebar-editor")).toBeVisible();

  await closeAccessPanels(page);
  await page.getByRole("link", { name: "Группы памяти", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Группы памяти" })).toBeVisible();
  const memoryRow = page.locator(".access-generic-table tbody tr").first();
  await memoryRow.locator(".access-object-link").click();
  await expect(page.getByText(/только для чтения|read-only/i)).toBeVisible();

  await closeAccessPanels(page);
  await page.getByRole("link", { name: "Пользователи", exact: true }).click();
  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  documentNavigationBaseline = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  const userRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await userRow.locator('.access-cell-link[href*="field=memory-groups"]').click();
  await expect(page.getByRole("heading", { name: /Группы памяти пользователя/ })).toBeVisible();
  const memoryForm = page.locator(".access-sidebar-editor .access-context-form");
  const firstMemoryGroup = memoryForm.locator('input[name="group_names"]').first();
  if (await firstMemoryGroup.isChecked()) await firstMemoryGroup.uncheck();
  else await firstMemoryGroup.check();
  await memoryForm.getByLabel("Причина").fill("Сквозная проверка назначения группы памяти.");
  const previewUrl = page.url();
  const previewHistoryLength = await page.evaluate(() => history.length);
  await memoryForm.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByText("Предпросмотр изменения")).toBeVisible();
  await expect(memoryForm.getByRole("button", { name: "Проверить" })).toBeFocused();
  expect(page.url()).toBe(previewUrl);
  expect(await page.evaluate(() => history.length)).toBe(previewHistoryLength);
  await page.locator('.access-sidebar-editor input[name="confirmed"]').check();
  await page.locator(".access-sidebar-editor").getByRole("button", { name: "Применить" }).click();
  await expect(page.getByRole("heading", { name: /Группы памяти пользователя/ })).toBeVisible();
  await expect(page.locator("#access-field-sidebar-host .flash[role='status'][tabindex='-1']")).toBeFocused();
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(documentNavigationBaseline);
});

test("@smoke HTMX panel navigation preserves document, AI root and table scroll state", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  const documentNavigationBaseline = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  await page.evaluate(() => {
    (window as Window & { __accessAiNode?: Element }).__accessAiNode = document.querySelector("#access-ai-chat-host > *");
  });
  const tableScroll = page.locator(".access-table-scroll").first();
  await tableScroll.evaluate((element) => { element.scrollLeft = 37; });
  const source = page.locator(".access-users-table tbody tr").first().locator(".access-object-link");

  await source.click();
  await expect(page.locator(".access-inspector.active")).toBeVisible();
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(documentNavigationBaseline);
  expect(await page.evaluate(() => document.querySelector("#access-ai-chat-host > *") === (window as Window & { __accessAiNode?: Element }).__accessAiNode)).toBe(true);
  await page.locator(".access-inspector .access-panel-close").click();
  await expect(page.locator(".access-inspector.active")).toHaveCount(0);
  await expect(page.locator("[data-access-workspace][inert]")).toHaveCount(0);
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(documentNavigationBaseline);
  expect(await page.evaluate(() => document.querySelector("#access-ai-chat-host > *") === (window as Window & { __accessAiNode?: Element }).__accessAiNode)).toBe(true);
  expect(await tableScroll.evaluate((element) => element.scrollLeft)).toBe(37);

  await source.click();
  await expect(page.locator(".access-inspector.active")).toBeVisible();
  await page.goBack({ waitUntil: "commit" });
  await expect(page).toHaveURL(/\/settings\/access\/\?view=users$/);
  await page.waitForFunction(() => !document.querySelector(".access-inspector.active"));
  await expect(page.locator(".access-inspector.active")).toHaveCount(0);
  expect(await page.evaluate(() => document.querySelector("#access-ai-chat-host > *") === (window as Window & { __accessAiNode?: Element }).__accessAiNode)).toBe(true);
  await page.goForward();
  await expect(page.locator(".access-inspector.active")).toBeVisible();
  expect(await page.evaluate(() => document.querySelector("#access-ai-chat-host > *") === (window as Window & { __accessAiNode?: Element }).__accessAiNode)).toBe(true);
});

test("@smoke composite user draft saves profile and role together and can be reverted", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  await page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first().locator(".access-object-link").click();

  let form = page.locator("[data-access-bundle-form]");
  const originalFirstName = await form.locator('input[name="first_name"]').inputValue();
  const changedFirstName = `${originalFirstName || "Проверка"} e2e`;
  await form.locator('input[name="first_name"]').fill(changedFirstName);
  await form.locator("[data-editor-tab='department']").click();
  const department = form.locator('select[name="department"]');
  if (!(await department.inputValue())) await department.selectOption({ index: 1 });
  const departmentValue = await department.inputValue();
  await form.locator("[data-editor-tab='roles']").click();
  const role = form.locator('input[name="roles"]:not(:checked)').first();
  await expect(role).toBeVisible();
  const roleValue = await role.getAttribute("value");
  await role.check();
  await form.getByLabel("Причина всех изменений").fill("Сквозная проверка единого сохранения карточки.");
  const navigationBaseline = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  await form.getByRole("button", { name: "Проверить изменения" }).click();
  await expect(page.getByText("Предпросмотр изменений")).toBeVisible();
  expect(await page.evaluate(() => performance.getEntriesByType("navigation").length)).toBe(navigationBaseline);
  form = page.locator("[data-access-bundle-form]");
  const riskConfirmation = form.locator('input[name="confirm_risk"]');
  if (await riskConfirmation.count()) await riskConfirmation.check();
  await form.getByRole("button", { name: "Сохранить все" }).click();
  await expect(page.getByText(/Карточка пользователя сохранена/)).toBeVisible();
  await expectAccessRequestIdle(page);

  form = page.locator("[data-access-bundle-form]");
  await expect(form.locator('input[name="first_name"]')).toHaveValue(changedFirstName);
  await expect(form.locator('select[name="department"]')).toHaveValue(departmentValue);
  await expect(form.locator(`input[name="roles"][value="${roleValue}"]`)).toBeChecked();
  await form.locator('input[name="first_name"]').fill(originalFirstName);
  await form.locator("[data-editor-tab='roles']").click();
  await form.locator(`input[name="roles"][value="${roleValue}"]`).uncheck();
  await form.getByLabel("Причина всех изменений").fill("Возврат данных после сквозной проверки.");
  await form.getByRole("button", { name: "Проверить изменения" }).click();
  await expect(page.getByText("Предпросмотр изменений")).toBeVisible();
  form = page.locator("[data-access-bundle-form]");
  const revertRiskConfirmation = form.locator('input[name="confirm_risk"]');
  if (await revertRiskConfirmation.count()) await revertRiskConfirmation.check();
  await form.getByRole("button", { name: "Сохранить все" }).click();
  await expect(page.getByText(/Карточка пользователя сохранена/)).toBeVisible();
  await expectAccessRequestIdle(page);
  await expect(page.locator("[data-access-bundle-form] input[name='first_name']")).toHaveValue(originalFirstName);
});

test("@smoke access workspace uses a single dialog layer on 320px and Escape follows close href", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await login(page);
  await page.goto("/settings/access/");
  const firstUser = page.locator(".access-users-table tbody tr").first();
  await firstUser.locator(".access-object-link").click();
  const inspector = page.locator(".access-inspector");
  await expect(inspector).toHaveAttribute("role", "dialog");
  await expect(inspector).toHaveAttribute("aria-modal", "true");
  await page.keyboard.press("Escape");
  await expect(page).toHaveURL(/\/settings\/access\/\?view=users/);
  await expect(page.locator(".access-inspector")).toHaveCount(0);
});

test("@smoke access left sidebar keeps its width and restores the full AI chat", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await login(page);
  await page.goto("/settings/access/");

  const sidebar = page.locator("#sidebar");
  const handle = page.locator("[data-access-sidebar-resize]");
  await handle.focus();
  await page.keyboard.press("End");
  await expect(handle).toHaveAttribute("aria-valuenow", "560");
  await expect(sidebar).toHaveCSS("width", "560px");
  await page.reload();
  await expect(handle).toHaveAttribute("aria-valuenow", "560");
  await expect(sidebar).toHaveCSS("width", "560px");

  await page.locator(".access-users-table tbody tr").first().locator(".access-ad-identity").click();
  const editor = page.locator("#access-field-sidebar-host");
  const chat = page.locator("#access-ai-chat-host");
  const launcher = page.locator("[data-access-ai-launcher]");
  await expect(editor).toBeVisible();
  await expect(chat).toHaveAttribute("aria-hidden", "true");
  await expect(launcher).toBeVisible();

  await editor.locator(".access-panel-close").click();
  await expect(editor).toBeHidden();
  await expect(chat).toHaveAttribute("aria-hidden", "false");
  await expect(chat).toHaveClass(/is-expanded/);
  const geometry = await page.evaluate(() => {
    const sidebarBox = document.querySelector("#sidebar")?.getBoundingClientRect();
    const chatBox = document.querySelector("#access-ai-chat-host")?.getBoundingClientRect();
    return {
      sidebarWidth: sidebarBox?.width || 0,
      chatWidth: chatBox?.width || 0,
      chatHeight: chatBox?.height || 0,
    };
  });
  expect(geometry.chatWidth).toBeGreaterThan(geometry.sidebarWidth * 0.9);
  expect(geometry.chatHeight).toBeGreaterThan(400);
});

test("@smoke access field editor is visible over the workspace on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator(".access-ad-identity").click();
  const editor = page.locator(".access-sidebar-editor");
  await expect(editor).toBeVisible();
  await expect(editor).toHaveAttribute("role", "dialog");
  await expect(editor).toHaveAttribute("aria-modal", "true");
  await expect(page.locator("[data-access-ai-launcher]")).toBeVisible();
});

test("@smoke access workspace uses one modal editor on tablet and isolates the table", async ({ page }) => {
  await page.setViewportSize({ width: 1024, height: 768 });
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator(".access-object-link").click();

  const inspector = page.locator(".access-inspector");
  await expect(inspector).toHaveAttribute("role", "dialog");
  await expect(inspector).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".access-table-panel")).toHaveAttribute("inert", "");
  const backdrop = page.locator(".access-inspector-overlay.is-active");
  await expect(backdrop).toBeVisible();
  expect(await backdrop.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
  await backdrop.click({ position: { x: 10, y: 300 } });
  await expect(page.locator(".access-inspector.active")).toHaveCount(0);
});

test("@smoke access workspace warns before browser reload with dirty editor data", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  const targetRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await targetRow.locator(".access-object-link").click();
  await page.locator(".access-inspector input[name=email]").fill("dirty@example.invalid");

  let dialogType = "";
  page.once("dialog", async (dialog) => {
    dialogType = dialog.type();
    await dialog.accept();
  });
  await page.reload();
  expect(dialogType).toBe("beforeunload");

  await page.locator(".access-inspector input[name=email]").fill("still-dirty@example.invalid");
  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    await dialog.dismiss();
  });
  await page.locator(".access-inspector .access-panel-close").click();
  await expect(page).toHaveURL(/view=users/);
  await expect(page.locator(".access-inspector")).toBeVisible();
});

test("@smoke access workspace protects dirty sidebar from toggle and header navigation", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator('.access-cell-link[href*="field=ad"]').click();
  const editor = page.locator(".access-sidebar-editor");
  await expect(editor).toBeVisible();
  await editor.locator("textarea").last().fill("dirty-sidebar-value");

  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    await dialog.dismiss();
  });
  await page.locator('.sidebar-toggle[aria-controls="sidebar"]').click();
  await expect(page.locator("#sidebar")).not.toHaveClass(/collapsed/);

  page.once("dialog", async (dialog) => {
    expect(dialog.type()).toBe("confirm");
    await dialog.dismiss();
  });
  await page.locator(".brand").click();
  await expect(page).toHaveURL(/\/settings\/access\//);
  await expect(editor).toBeVisible();
});

test("@smoke access workspace restores dirty marker after failed HTMX editor request", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator('.access-cell-link[href*="field=ad"]').click();
  const editor = page.locator(".access-sidebar-editor");
  const form = editor.locator(".access-context-form");
  await expect(editor).toBeVisible();
  await editor.locator("textarea").last().fill("dirty-after-failed-request");
  await page.route("**/*", async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.pathname === "/settings/access/" && route.request().method() === "POST") {
      await route.abort("failed");
      return;
    }
    await route.continue();
  });
  await form.getByRole("button", { name: "Проверить" }).click();
  await expect(form).toHaveAttribute("data-access-dirty", "true");
  await expect(page.getByText(/Не удалось сохранить изменения/)).toBeVisible();
  await expectAccessRequestIdle(page);
  await page.unroute("**/*");

  let confirmed = false;
  page.once("dialog", async (dialog) => {
    confirmed = dialog.type() === "confirm";
    await dialog.dismiss();
  });
  await editor.locator(".access-panel-close").click();
  expect(confirmed).toBe(true);
  await expect(editor).toBeVisible();
});

test("@smoke access workspace times out a hung POST without losing the dirty draft", async ({ page }) => {
  test.setTimeout(45_000);
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator('.access-cell-link[href*="field=ad"]').click();
  const editor = page.locator(".access-sidebar-editor");
  const form = editor.locator(".access-context-form");
  await editor.locator("textarea").last().fill("dirty-after-timeout");
  await page.route("**/*", async (route) => {
    const requestUrl = new URL(route.request().url());
    if (requestUrl.pathname === "/settings/access/" && route.request().method() === "POST") {
      await new Promise((resolve) => setTimeout(resolve, 16_000));
      try { await route.abort("timedout"); } catch (_) { /* browser already aborted the request */ }
      return;
    }
    await route.continue();
  });
  await form.getByRole("button", { name: "Проверить" }).click();
  await expect(form.getByRole("button", { name: "Проверить" })).toBeDisabled({ timeout: 3_000 });
  await expect(form).toHaveAttribute("data-access-dirty", "true", { timeout: 20_000 });
  await expect(page.getByText(/Не удалось сохранить изменения/)).toBeVisible();
  await expectAccessRequestIdle(page);
  await page.unroute("**/*");
});

test("@smoke completing one parallel access request keeps the other form busy", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  await page.locator(".access-users-table tbody tr").first().locator('.access-cell-link[href*="field=ad"]').click();
  const original = page.locator(".access-sidebar-editor .access-context-form");
  await expect(original).toBeVisible();
  await page.evaluate(() => {
    const source = document.querySelector<HTMLFormElement>(".access-sidebar-editor .access-context-form");
    if (!source) throw new Error("Access form is missing");
    source.setAttribute("hx-swap", "none");
    source.insertAdjacentHTML("beforeend", '<input type="hidden" name="e2e_request_marker" value="first">');
    const host = document.createElement("div");
    host.id = "access-parallel-request-host";
    const clone = source.cloneNode(true) as HTMLFormElement;
    clone.id = "access-parallel-request-form";
    clone.setAttribute("hx-target", "#access-parallel-request-host");
    clone.querySelector<HTMLInputElement>('input[name="e2e_request_marker"]')!.value = "second";
    host.appendChild(clone);
    document.body.appendChild(host);
    (window as Window & { htmx: { process: (element: Element) => void } }).htmx.process(clone);
  });

  const clone = page.locator("#access-parallel-request-form");
  await page.evaluate(() => {
    const forms = document.querySelectorAll<HTMLFormElement>(
      ".access-sidebar-editor .access-context-form, #access-parallel-request-form",
    );
    if (forms.length !== 2) throw new Error("Parallel access forms are missing");
    const target = document.getElementById("access-field-sidebar-host");
    if (!target) throw new Error("Access field target is missing");
    const xhrs = [{}, {}];
    (window as Window & { __accessParallelXhrs?: object[] }).__accessParallelXhrs = xhrs;
    forms.forEach((form, index) => {
      form.dispatchEvent(new CustomEvent("htmx:beforeRequest", {
        bubbles: true,
        cancelable: true,
        detail: { elt: form, target, xhr: xhrs[index] },
      }));
    });
  });
  await expect(original).toHaveAttribute("aria-busy", "true");
  await expect(clone).toHaveAttribute("aria-busy", "true");
  await expect(page.locator("#access-field-sidebar-host")).toHaveAttribute("aria-busy", "true");

  await page.evaluate(() => {
    const form = document.querySelector<HTMLFormElement>(".access-sidebar-editor .access-context-form")!;
    const target = document.getElementById("access-field-sidebar-host")!;
    const xhr = (window as Window & { __accessParallelXhrs?: object[] }).__accessParallelXhrs![0];
    form.dispatchEvent(new CustomEvent("htmx:afterRequest", {
      bubbles: true,
      detail: { elt: form, target, xhr, successful: true },
    }));
  });
  await expect(original).not.toHaveAttribute("aria-busy", "true");
  await expect(clone).toHaveAttribute("aria-busy", "true");
  await expect(clone.getByRole("button", { name: "Проверить" })).toBeDisabled();
  await expect(page.locator("#access-field-sidebar-host")).toHaveAttribute("aria-busy", "true");

  await page.evaluate(() => {
    const form = document.querySelector<HTMLFormElement>("#access-parallel-request-form")!;
    const target = document.getElementById("access-field-sidebar-host")!;
    const xhr = (window as Window & { __accessParallelXhrs?: object[] }).__accessParallelXhrs![1];
    form.dispatchEvent(new CustomEvent("htmx:afterRequest", {
      bubbles: true,
      detail: { elt: form, target, xhr, successful: true },
    }));
  });
  await expect(clone).not.toHaveAttribute("aria-busy", "true");
  await expectAccessRequestIdle(page);
});

test("@smoke access workspace restores source focus after drawer close at layout boundaries", async ({ page }) => {
  await login(page);
  for (const width of [1200, 767]) {
    await page.setViewportSize({ width, height: 760 });
    await page.goto("/settings/access/");
    const source = page.locator(".access-users-table tbody tr").first().locator(".access-object-link");
    await source.click();
    await expect(page.locator(".access-inspector.active")).toBeVisible();
    await page.locator(".access-inspector .access-panel-close").click();
    await expect(source).toBeFocused();
  }
});

test("@smoke role sidebar adds a user through preview and confirmation", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/?view=roles");
  const roleRow = page.locator(".access-roles-table tbody tr").first();
  await roleRow.locator('.access-cell-link[href*="field=users"]').click();
  const roleForm = page.locator(".access-sidebar-editor .access-context-form");
  const targetMembership = roleForm.getByLabel(targetUsername || "", { exact: true });
  if (await targetMembership.isChecked()) await targetMembership.uncheck();
  else await targetMembership.check();
  await roleForm.getByLabel("Причина изменения состава").fill("Сквозная проверка состава роли.");
  await roleForm.getByRole("button", { name: "Проверить" }).click();
  await expect(page.getByText("Предпросмотр изменения")).toBeVisible();
  await page.locator('.access-sidebar-editor input[name="risk_confirmed"]').check();
  await page.locator(".access-sidebar-editor").getByRole("button", { name: "Применить" }).click();
  await expect(page.getByText(/Состав роли изменён/)).toBeVisible();
});

test("@smoke role definition groups switch locally and retain draft", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/?view=roles");
  const pageIdentity = await page.evaluate(() => {
    const identity = crypto.randomUUID();
    (window as Window & { __accessRoleEditorIdentity?: string }).__accessRoleEditorIdentity = identity;
    return identity;
  });
  await page.locator(".access-roles-table tbody tr").first().locator(".access-object-link").click();
  const editor = page.locator(".role-capability-editor");
  await expect(editor).toBeVisible();
  const name = editor.locator('input[name="display_name"]');
  const draft = `${await name.inputValue()} draft`;
  await name.fill(draft);
  const tabs = editor.locator("[data-role-editor-tab]");
  const tabCount = await tabs.count();
  expect(tabCount).toBeGreaterThan(1);
  await tabs.first().focus();
  await page.keyboard.press("ArrowRight");
  await expect(tabs.nth(1)).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tabs.first()).toBeFocused();
  await page.keyboard.press("End");
  await expect(tabs.nth(tabCount - 1)).toBeFocused();
  await tabs.nth(1).click();
  await tabs.first().click();
  await expect(editor.locator("[data-role-editor-panel]:not([hidden])")).toHaveCount(1);
  if (tabCount > 2) {
    await tabs.nth(2).click();
    await expect(editor.locator("[data-role-editor-panel]:not([hidden])")).toHaveCount(1);
  }
  await expect(name).toHaveValue(draft);
  expect(await page.evaluate(() => (window as Window & { __accessRoleEditorIdentity?: string }).__accessRoleEditorIdentity)).toBe(pageIdentity);
  await expect(editor.locator("input[name='active_group']")).not.toHaveValue("");
});

test("@smoke admin role uses one kanban capability group", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/?view=roles");
  const adminRow = page.locator(".access-roles-table tbody tr").filter({ hasText: "Администратор портала" });
  await adminRow.locator(".access-object-link").click();
  const editor = page.locator(".role-capability-editor");
  await expect(editor).toBeVisible();
  await expect(editor.locator('[data-role-editor-tab="kanban"]')).toHaveText("Канбан-доска");
  await expect(editor.locator('[data-role-editor-tab="workorders"]')).toHaveCount(0);
  await expect(editor.locator('[data-role-editor-tab="boards"]')).toHaveCount(0);
  await expect(editor.locator('[data-role-editor-tab="system"]')).toHaveCount(0);
  await expect(editor.locator('[data-role-editor-tab="access_scopes"]')).toHaveCount(0);
  await expect(editor.locator('[data-role-editor-tab="administration"]')).toHaveCount(0);
  await editor.locator('[data-role-editor-tab="kanban"]').click();
  const panel = editor.locator('[data-role-editor-panel="kanban"]:not([hidden])');
  await expect(panel).toHaveCount(1);
  for (const label of [
    "Область видимости заявок",
    "Создание заявок",
    "Редактирование заявок",
    "Комментирование заявок",
    "Загрузка файлов к заявкам",
    "Подтверждение закрытия",
    "Оценка выполненной работы",
    "Смена статусов заявок",
    "Доступные статусы",
    "Управление досками",
    "Управление назначениями",
  ]) {
    await expect(panel).toContainText(label);
  }
});

test("@smoke role inspector preview renders impact and diff without navigation", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/?view=roles");
  const pageIdentity = await page.evaluate(() => {
    const identity = crypto.randomUUID();
    (window as Window & { __accessRoleEditorIdentity?: string }).__accessRoleEditorIdentity = identity;
    return identity;
  });
  await page.locator(".access-roles-table tbody tr").first().locator(".access-object-link").click();
  const editor = page.locator(".role-capability-editor");
  const originalName = await editor.locator('input[name="display_name"]').inputValue();
  await editor.locator('input[name="display_name"]').fill(`${originalName} preview`);
  await editor.getByRole("button", { name: "Проверить изменение" }).click();
  await expect(editor.getByRole("table", { name: "Сравнение изменений роли" })).toBeVisible();
  await expect(editor.getByText(/фактически изменится доступ/)).toBeVisible();
  expect(await page.evaluate(() => (window as Window & { __accessRoleEditorIdentity?: string }).__accessRoleEditorIdentity)).toBe(pageIdentity);
  await editor.getByRole("button", { name: "Подтвердить и применить" }).click();
  await expect(page.getByText(/Роль изменена/)).toBeVisible();
  await expectAccessRequestIdle(page);

  const restoredEditor = page.locator(".role-capability-editor");
  await restoredEditor.locator('input[name="display_name"]').fill(originalName);
  await restoredEditor.getByRole("button", { name: "Проверить изменение" }).click();
  await expect(restoredEditor.getByRole("table", { name: "Сравнение изменений роли" })).toBeVisible();
  await restoredEditor.getByRole("button", { name: "Подтвердить и применить" }).click();
  await expect(page.getByText(/Роль изменена/)).toBeVisible();
  await expectAccessRequestIdle(page);
});

test("@smoke Django Admin reserve remains available from the workspace standalone action", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");
  const standalone = page.locator(".access-users-table tbody tr").first().locator(".access-standalone a");
  const href = await standalone.getAttribute("href");
  expect(href).toMatch(/\/settings\/users\/\d+\/edit\//);
  const userId = href?.match(/\/users\/(\d+)\/edit\//)?.[1];
  expect(userId).toBeTruthy();
  await page.goto(`/admin/accounts/user/${userId}/access-assignment/`);
  await expect(page.getByRole("heading", { name: /Резервное изменение доступа/ })).toBeVisible();
});
