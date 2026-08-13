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

test("@smoke access workspace exposes the six access cuts and master-detail panels", async ({ page }) => {
  await login(page);
  await page.goto("/settings/access/");

  await expect(page).toHaveURL(/\/settings\/access\//);
  await expect(page.locator(".access-tab")).toHaveCount(6);
  await expect(page.locator(".access-users-table thead th")).toHaveCount(9);

  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  let documentNavigationBaseline = await page.evaluate(() => performance.getEntriesByType("navigation").length);
  const targetRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await expect(targetRow).toBeVisible();

  await targetRow.locator(".access-object-link").click();
  await expect(page.locator(".access-inspector")).toBeVisible();
  await expect(page.locator(".access-inspector")).toHaveAttribute("aria-modal", "true");
  await expect(page.locator(".access-table-panel")).toHaveAttribute("inert", "");
  await expect(page.getByText("Текущие значения")).toBeVisible();

  await page.locator(".access-inspector .access-panel-close").click();
  const reopenedTargetRow = page.locator(".access-users-table tbody tr", { hasText: targetUsername || "" }).first();
  await reopenedTargetRow.locator(".access-cell-link").nth(0).click();
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
