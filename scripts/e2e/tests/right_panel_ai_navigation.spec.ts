import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;

async function login(page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
}

test.describe("AI right panel navigation", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");

  test("opens a work order in the global right panel from the AI chat page", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/");
    const firstCard = page.locator(".work-card:not(.work-card-empty)").first();
    test.skip((await firstCard.count()) === 0, "No visible work order cards.");
    const htmxUrl = await firstCard.getAttribute("hx-get");
    expect(htmxUrl).toBeTruthy();

    await page.goto("/ai/chat/");
    await expect(page.locator("#global-right-panel")).toBeAttached();
    await page.evaluate(async (url) => {
      await window.LocalBusinessRightPanel?.open({
        type: "open_right_panel",
        source_code: "workorders",
        object_type: "workorder",
        object_id: "e2e",
        htmx_url: url,
        target: "#global-right-panel-content",
        swap: "innerHTML",
        drawer_size: "large",
      });
    }, htmxUrl);

    await expect(page.locator("#global-right-panel.active")).toBeVisible();
    await expect(page.locator("#global-right-panel-content [data-ai-context]")).toBeVisible();
    const context = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(context?.envelope?.selection?.object_type).toBe("workorder");
  });

  test("opens a waiting-list entry in the global right panel from the AI chat page", async ({ page }) => {
    await login(page);
    await page.goto("/waiting-list/");
    if ((await page.locator("#entry-table tr[hx-get]").count()) === 0) {
      await page.goto("/waiting-list/new/");
      await page.locator('input[name="patient_name"]').fill("E2E Пациент");
      await page.locator('input[name="patient_dob"]').fill("01.01.1990");
      await page.locator('input[name="patient_phone"]').fill("+7 (900) 111-22-33");
      await page.locator('select[name="service_id"]').selectOption("s1");
      await page.getByRole("button", { name: "Сохранить" }).click();
      await expect(page).toHaveURL(/\/waiting-list\/$/);
    }
    const firstRow = page.locator("#entry-table tr[hx-get]").first();
    test.skip((await firstRow.count()) === 0, "No visible waiting-list entries.");
    const htmxUrl = await firstRow.getAttribute("hx-get");
    expect(htmxUrl).toBeTruthy();

    await page.goto("/ai/chat/");
    await expect(page.locator("#global-right-panel")).toBeAttached();
    await page.evaluate(async (url) => {
      await window.LocalBusinessRightPanel?.open({
        type: "open_right_panel",
        source_code: "waiting_list",
        object_type: "waiting_list_entry",
        object_id: "e2e",
        htmx_url: url,
        target: "#global-right-panel-content",
        swap: "innerHTML",
        drawer_size: "waiting_list",
      });
    }, htmxUrl);

    await expect(page.locator("#global-right-panel.active")).toBeVisible();
    await expect(page.locator("#global-right-panel-content [data-ai-context]")).toBeVisible();
    const context = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(context?.envelope?.selection?.object_type).toBe("waiting_list_entry");
  });
});

declare global {
  interface Window {
    LocalBusinessRightPanel?: {
      open: (command: Record<string, string>) => Promise<boolean>;
    };
    LocalBusinessPageContext?: {
      getCurrent: () => {
        envelope?: {
          selection?: { object_type?: string; object_id?: string };
        };
      };
    };
  }
}
