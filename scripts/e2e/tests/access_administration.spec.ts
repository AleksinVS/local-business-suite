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

test("@smoke access administration keeps one entrypoint and a compact user workflow", async ({ page }) => {
  await login(page);
  await page.goto("/settings/users/");

  await expect(page.getByRole("heading", { name: "Доступ сотрудников" })).toBeVisible();
  await expect(page.getByRole("columnheader")).toHaveCount(5);

  await page.getByRole("searchbox", { name: "Поиск" }).fill(targetUsername || "");
  await page.getByRole("button", { name: "Найти" }).click();
  const targetRow = page.locator("tbody tr", { hasText: targetUsername || "" }).first();
  await expect(targetRow).toBeVisible();

  const openLink = targetRow.getByRole("link", { name: "Открыть" });
  const accessUrl = await openLink.getAttribute("href");
  expect(accessUrl).toMatch(/\/settings\/users\/\d+\/edit\//);
  await openLink.click();

  await expect(page.getByRole("heading", { name: /Карточка доступа/ })).toBeVisible();
  await expect(page.locator("#assign")).toBeVisible();
  await expect(page.getByText("Возможности и технические источники")).toBeVisible();

  const userId = accessUrl?.match(/\/users\/(\d+)\/edit\//)?.[1];
  expect(userId).toBeTruthy();
  await page.goto(`/admin/accounts/user/${userId}/access-assignment/`);
  await expect(page.getByRole("heading", { name: /Резервное изменение доступа/ })).toBeVisible();
  await expect(page.getByLabel("Причина резервного изменения")).toBeVisible();
});

test("@smoke access list remains operable on a narrow viewport", async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 760 });
  await login(page);
  await page.goto("/settings/users/");

  await expect(page.getByRole("searchbox", { name: "Поиск" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Найти" })).toBeVisible();
  const tableContainer = page.locator(".table-container");
  await expect(tableContainer).toBeVisible();
  const overflowX = await tableContainer.evaluate(
    (element) => window.getComputedStyle(element).overflowX,
  );
  expect(["auto", "scroll"]).toContain(overflowX);
});
