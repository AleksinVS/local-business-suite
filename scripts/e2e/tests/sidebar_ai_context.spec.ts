import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;

test.describe("context-aware sidebar AI chat", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");

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
