import { expect, test, type Page } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;

async function expectToolbarTouchesHeader(page: Page) {
  const headerBox = await page.locator(".site-header").boundingBox();
  const toolbarBox = await page.locator(".page-container > .toolbar, .workorders-board-context > .toolbar").boundingBox();
  expect(headerBox).not.toBeNull();
  expect(toolbarBox).not.toBeNull();
  expect(Math.abs((toolbarBox?.y || 0) - ((headerBox?.y || 0) + (headerBox?.height || 0)))).toBeLessThanOrEqual(1);
}

test("@smoke authenticated user opens the portal shell", async ({ page }) => {
  expect(username, "Set E2E_USERNAME for the authenticated smoke test.").toBeTruthy();
  expect(password, "Set E2E_PASSWORD for the authenticated smoke test.").toBeTruthy();

  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();

  await expect(page).not.toHaveURL(/\/accounts\/login\//);
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
  await expect(page.locator("#global-right-panel")).toBeAttached();
  await expect(page.getByRole("button", { name: "Уведомления" })).toBeVisible();

  await page.goto("/workorders/");
  await expectToolbarTouchesHeader(page);

  await page.goto("/waiting-list/");
  await expectToolbarTouchesHeader(page);
});
