import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;

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
});
