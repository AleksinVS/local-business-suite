import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const copilotkitEnabled = process.env.E2E_COPILOTKIT_ENABLED === "true";

test.describe("context-aware sidebar AI chat", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");
  test.skip(copilotkitEnabled, "HTMX sidebar checks run only when CopilotKit sidebar is disabled.");

  test("loads from the left panel and tracks the opened work order", async ({ page }) => {
    await page.goto("/accounts/login/");
    await page.locator('input[name="username"]').fill(username || "");
    await page.locator('input[name="password"]').fill(password || "");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();

    const firstContextUpdate = page.waitForResponse((response) => (
      response.url().includes("/ai/context/window/")
      && response.request().method() === "POST"
      && response.status() === 200
    ));
    await page.goto("/workorders/");
    await firstContextUpdate;

    await page.getByRole("button", { name: "Все функции" }).click();
    await expect(page.getByRole("link", { name: /Доска/ }).first()).toBeVisible();

    const sidebarChat = page.locator("#sidebar-ai-chat [data-sidebar-chat]");
    await expect(sidebarChat).toBeVisible();
    await expect(page.locator('#sidebar-ai-chat input[name="surface"]')).toHaveValue("sidebar");

    const pageContext = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(pageContext?.envelope?.page?.module).toBe("workorders");
    expect(pageContext?.envelope?.page?.view).toBe("board");

    const firstCard = page.locator(".work-card:not(.work-card-empty)").first();
    await expect(firstCard).toBeVisible();

    const detailContextUpdate = page.waitForResponse((response) => (
      response.url().includes("/ai/context/window/")
      && response.request().method() === "POST"
      && response.status() === 200
    ));
    await firstCard.click();
    await expect(page.locator("#detail-panel.active")).toBeVisible();
    await expect(page.locator("#detail-panel-content [data-ai-context]")).toBeVisible();
    await detailContextUpdate;

    const detailContext = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(detailContext?.envelope?.selection?.object_type).toBe("workorder");
    expect(detailContext?.envelope?.selection?.object_id).toBeTruthy();
    await expect(page.locator("#sidebar-ai-context-version")).not.toHaveValue("");
  });

  test("sends a sidebar chat message with the prompt field included", async ({ page }) => {
    await page.route("**/ai/chat/*/stream/", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: 'data: {"content":"Тестовый ответ"}\n\ndata: [DONE]\n\n',
      });
    });

    await page.goto("/accounts/login/");
    await page.locator('input[name="username"]').fill(username || "");
    await page.locator('input[name="password"]').fill(password || "");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();

    await page.goto("/workorders/");
    const sidebarChat = page.locator("#sidebar-ai-chat [data-sidebar-chat]");
    await expect(sidebarChat).toBeVisible();

    const sendResponse = page.waitForResponse((response) => (
      /\/ai\/chat\/[^/]+\/send\/$/.test(new URL(response.url()).pathname)
      && response.request().method() === "POST"
    ));
    const promptInput = page.locator("#sidebar-ai-prompt-input");
    await promptInput.fill("Открой");
    await promptInput.press("Shift+Enter");
    await expect(promptInput).toHaveValue("Открой\n");
    await promptInput.type("заявку");
    await promptInput.press("Enter");

    const response = await sendResponse;
    expect(response.status()).toBe(200);
    await expect(page.locator("#sidebar-ai-message-list")).not.toContainText("Не удалось отправить сообщение.");
    await expect(page.locator("#sidebar-ai-message-list")).toContainText("Тестовый ответ");
  });

  test("executes a sidebar AI right-panel command for a work order", async ({ page }) => {
    await page.goto("/accounts/login/");
    await page.locator('input[name="username"]').fill(username || "");
    await page.locator('input[name="password"]').fill(password || "");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();

    await page.goto("/workorders/");
    const firstCard = page.locator(".work-card:not(.work-card-empty)").first();
    await expect(firstCard).toBeVisible();
    const objectId = await firstCard.getAttribute("data-workorder-id");
    expect(objectId).toBeTruthy();

    await page.route("**/ai/chat/*/stream/", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"content":"Открываю заявку справа."}',
          `data: {"ui_command":{"type":"open_right_panel","source_code":"workorders","object_type":"workorder","object_id":"${objectId}","mode":"view","title":"Заявка","htmx_url":"/workorders/${objectId}/","target":"#global-right-panel-content","swap":"innerHTML","drawer_size":"large"}}`,
          "data: [DONE]",
          "",
        ].join("\n\n"),
      });
    });

    await page.locator("#sidebar-ai-prompt-input").fill(`Открой заявку №${objectId}`);
    await page.locator("#sidebar-ai-send-button").click();

    await expect(page.locator("#global-right-panel.active")).toBeVisible();
    await expect(page.locator("#global-right-panel-content [data-ai-context]")).toBeVisible();
    const detailContext = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(detailContext?.envelope?.selection?.object_type).toBe("workorder");
    expect(detailContext?.envelope?.selection?.object_id).toBe(objectId);
  });

  test("executes a sidebar AI right-panel command for a waiting-list entry when one exists", async ({ page }) => {
    await page.goto("/accounts/login/");
    await page.locator('input[name="username"]').fill(username || "");
    await page.locator('input[name="password"]').fill(password || "");
    await page.locator('button[type="submit"]').click();
    await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();

    await page.goto("/waiting-list/");
    const firstRow = page.locator("#entry-table tr[hx-get]").first();
    test.skip(await firstRow.count() === 0, "No waiting-list entries are available in this environment.");
    await expect(firstRow).toBeVisible();
    const htmxUrl = await firstRow.getAttribute("hx-get");
    const objectId = htmxUrl?.match(/\/waiting-list\/(\d+)\//)?.[1];
    expect(objectId).toBeTruthy();

    await page.route("**/ai/chat/*/stream/", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"content":"Открываю запись листа ожидания справа."}',
          `data: {"ui_command":{"type":"open_right_panel","source_code":"waiting_list","object_type":"waiting_list_entry","object_id":"${objectId}","mode":"view","title":"Лист ожидания","htmx_url":"${htmxUrl}","target":"#global-right-panel-content","swap":"innerHTML","drawer_size":"waiting_list"}}`,
          "data: [DONE]",
          "",
        ].join("\n\n"),
      });
    });

    await page.locator("#sidebar-ai-prompt-input").fill(`Открой запись листа ожидания ${objectId}`);
    await page.locator("#sidebar-ai-send-button").click();

    await expect(page.locator("#global-right-panel.active")).toBeVisible();
    await expect(page.locator("#global-right-panel-content [data-ai-context]")).toBeVisible();
    const detailContext = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(detailContext?.envelope?.selection?.object_type).toBe("waiting_list_entry");
    expect(detailContext?.envelope?.selection?.object_id).toBe(objectId);
  });
});

declare global {
  interface Window {
    LocalBusinessPageContext?: {
      getCurrent: () => {
        envelope?: {
          page?: { module?: string; view?: string };
          selection?: { object_type?: string; object_id?: string };
        };
      };
    };
  }
}
