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

test.describe("notifications PWA", () => {
  test("serves manifest and root service worker", async ({ request }) => {
    const manifest = await request.get("/static/manifest.webmanifest");
    await expect(manifest).toBeOK();
    expect(manifest.headers()["content-type"] || "").toMatch(/json|manifest|octet-stream|text/);
    const manifestPayload = await manifest.json();
    expect(manifestPayload.display).toBe("standalone");
    expect(manifestPayload.scope).toBe("/");

    const worker = await request.get("/service-worker.js");
    await expect(worker).toBeOK();
    expect(await worker.text()).toContain("self.addEventListener(\"fetch\"");
  });

  test.describe("authenticated notification center", () => {
    test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated notification checks.");

    test("shows center and does not request browser permission on page load", async ({ page }) => {
      await page.addInitScript(() => {
        Object.defineProperty(window, "__notificationPermissionCalls", {
          value: 0,
          writable: true
        });
        try {
          const original = Notification.requestPermission.bind(Notification);
          Notification.requestPermission = (...args) => {
            window.__notificationPermissionCalls += 1;
            return original(...args);
          };
        } catch {
          window.__notificationPermissionCalls = 0;
        }
      });

      await login(page);

      await expect(page.getByRole("button", { name: "Уведомления" })).toBeVisible();
      await expect.poll(() => page.evaluate(() => window.__notificationPermissionCalls)).toBe(0);
      await page.getByRole("button", { name: "Уведомления" }).click();
      await expect(page.locator("#notification-dropdown")).toBeVisible();
      await expect(page.locator("#notification-permission-panel")).toBeVisible();
      const permission = await page.evaluate(() => Notification.permission);
      if (permission === "denied") {
        await expect(page.locator("#notification-permission-text")).toContainText("Браузер запретил уведомления.");
        await expect(page.locator("#notification-enable-button")).toBeHidden();
      } else {
        await expect(page.locator("#notification-enable-button")).toBeVisible();
      }
    });
  });
});

declare global {
  interface Window {
    __notificationPermissionCalls: number;
  }
}
