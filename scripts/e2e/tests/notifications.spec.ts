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

test.describe("@notifications notifications PWA", () => {
  test("serves manifest and root service worker", async ({ request }) => {
    const manifest = await request.get("/static/manifest.webmanifest");
    await expect(manifest).toBeOK();
    expect(manifest.headers()["content-type"] || "").toMatch(/json|manifest|octet-stream|text/);
    const manifestPayload = await manifest.json();
    expect(manifestPayload.display).toBe("standalone");
    expect(manifestPayload.scope).toBe("/");

    const worker = await request.get("/service-worker.js");
    await expect(worker).toBeOK();
    const workerSource = await worker.text();
    expect(workerSource).toContain("self.addEventListener(\"fetch\"");
    expect(workerSource).toContain("local-business-suite-pwa-");
    expect(workerSource).toContain("networkFirstStatic(request)");
    expect(workerSource.indexOf("fetch(request)")).toBeLessThan(workerSource.indexOf("caches.match(request)"));
  });

  test.describe("authenticated notification center", () => {
    test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated notification checks.");

    test("replaces the legacy static cache and versions core assets", async ({ page }) => {
      await page.goto("/accounts/login/");
      await page.evaluate(async () => {
        const legacy = await caches.open("local-business-suite-pwa-v3:static");
        await legacy.put(
          "/static/src/css/app.css",
          new Response("legacy-static-content", { headers: { "Content-Type": "text/css" } }),
        );
      });

      await login(page);

      await expect(page.locator('link[href*="/static/src/css/app.css"][href*="v=pwa-v4"]')).toHaveCount(1);
      await expect.poll(async () => page.evaluate(async () => await caches.keys())).not.toContain(
        "local-business-suite-pwa-v3:static",
      );
      await expect.poll(async () => page.evaluate(async () => await caches.keys())).toContain(
        "local-business-suite-pwa-v4:static",
      );
    });

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
