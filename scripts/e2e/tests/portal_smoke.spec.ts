import { expect, test, type Page } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;

async function login(page: Page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/accounts\/login\//);
}

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

  await login(page);
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
  await expect(page.locator("#global-right-panel")).toBeAttached();
  await expect(page.getByRole("button", { name: "Уведомления" })).toBeVisible();

  await page.goto("/workorders/");
  await expectToolbarTouchesHeader(page);

  await page.goto("/waiting-list/");
  await expectToolbarTouchesHeader(page);
});

test("@smoke administrator changes the waiting-list status palette", async ({ page }) => {
  expect(username, "Set E2E_USERNAME for the authenticated smoke test.").toBeTruthy();
  expect(password, "Set E2E_PASSWORD for the authenticated smoke test.").toBeTruthy();

  await login(page);
  await page.goto("/settings/waiting-list/status-colors/");
  await expect(page.getByRole("heading", { name: "Цвета статусов листа ожидания" })).toBeVisible();

  await page.locator('input[name="color__waiting"]').fill("#123456");
  await page.locator('input[name="confirm"]').check();
  await page.getByRole("button", { name: "Сохранить палитру" }).click();
  await expect(page).toHaveURL(/\/settings\/waiting-list\/status-colors\/$/);

  await page.goto("/waiting-list/");
  const configuredColor = await page.locator(".waiting-list-context").evaluate((element) =>
    getComputedStyle(element).getPropertyValue("--waiting-list-status-waiting").trim(),
  );
  expect(configuredColor).toBe("#123456");
});
