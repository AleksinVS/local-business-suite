import path from "node:path";

import { expect, test } from "@playwright/test";

const shellUrl = "http://right-panel-shell.test/";

function formMarkup(value = "Черновик", error = "") {
  return `
    <form data-right-panel-form hx-post="/form/" hx-target="#global-right-panel-content" hx-swap="innerHTML">
      <label>Название <input name="name" autofocus value="${value}"></label>
      <div data-right-panel-errors>${error ? `<p class="form-error">${error}</p>` : ""}</div>
      <div class="right-panel-form-actions">
        <button type="submit">Сохранить</button>
        <button type="button" onclick="closeGlobalRightPanel()">Отмена</button>
      </div>
    </form>`;
}

async function mountShell(page, options: {postDelayMs?: number} = {}) {
  const state = {postAttempts: 0};
  await page.route(`${shellUrl}**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === "/form/") {
      if (route.request().method() === "POST") {
        state.postAttempts += 1;
        const value = new URLSearchParams(route.request().postData() || "").get("name") || "";
        if (options.postDelayMs) {
          await new Promise((resolve) => setTimeout(resolve, options.postDelayMs));
        }
        if (state.postAttempts === 1) {
          await route.fulfill({
            status: 422,
            contentType: "text/html; charset=utf-8",
            body: formMarkup(value, "Проверьте значение"),
          });
        } else {
          await route.fulfill({
            status: 204,
            headers: {"HX-Trigger": JSON.stringify({rightPanelFormSucceeded: {id: "42"}})},
          });
        }
        return;
      }
      await route.fulfill({
        contentType: "text/html; charset=utf-8",
        body: formMarkup(),
      });
      return;
    }
    if (url.pathname === "/slow-a/" || url.pathname === "/slow-b/") {
      await new Promise((resolve) => setTimeout(resolve, url.pathname === "/slow-a/" ? 220 : 20));
      try {
        await route.fulfill({
          contentType: "text/html; charset=utf-8",
          body: `<button>${url.pathname === "/slow-a/" ? "Первая панель" : "Вторая панель"}</button>`,
        });
      } catch (_error) {
        // The expected AbortController cancellation can dispose the route.
      }
      return;
    }
    await route.fulfill({
      contentType: "text/html; charset=utf-8",
      body: `<!doctype html><html><body>
        <div class="app-layout"><button id="open">Открыть</button></div>
        <div id="globalRightPanelOverlay"></div>
        <aside id="global-right-panel" class="drawer global-right-panel" aria-hidden="true" tabindex="-1">
          <div id="global-right-panel-content"></div>
        </aside>
      </body></html>`,
    });
  });
  await page.goto(shellUrl);
  await page.addStyleTag({path: path.resolve(process.cwd(), "static/src/css/app.css")});
  await page.addScriptTag({path: path.resolve(process.cwd(), "static/django_htmx/htmx.min.js")});
  await page.addScriptTag({path: path.resolve(process.cwd(), "static/src/js/right_panel.js")});
  return state;
}

async function openForm(page) {
  await page.locator("#open").focus();
  await page.evaluate(() => window.LocalBusinessRightPanel.openForm({
    mode: "edit",
    title: "Редактирование",
    htmx_url: "/form/",
    target: "#global-right-panel-content",
    swap: "innerHTML",
    drawer_size: "workspace",
  }));
}

test.describe("@ui shared right-panel form shell", () => {
  test("tracks dirty state, guards close and restores focus", async ({page}) => {
    await mountShell(page);
    await page.evaluate(() => { window.confirm = () => false; });
    await openForm(page);

    const name = page.locator("input[name=name]");
    await expect(name).toBeFocused();
    await name.fill("Изменено");
    await expect(page.locator("form[data-right-panel-form]")).toHaveAttribute("data-right-panel-dirty", "true");

    await page.evaluate(() => window.LocalBusinessRightPanel.close());
    await expect(page.locator("#global-right-panel")).toHaveClass(/active/);
    await page.evaluate(() => { window.confirm = () => true; window.LocalBusinessRightPanel.close(); });
    await expect(page.locator("#global-right-panel")).not.toHaveClass(/active/);
    await expect(page.locator("#open")).toBeFocused();
  });

  test("keeps a real delayed validation response and drops a rapid duplicate submission", async ({page}) => {
    const state = await mountShell(page, {postDelayMs: 220});
    await openForm(page);

    await page.locator("input[name=name]").fill("Двойная отправка");
    await page.locator("form[data-right-panel-form]").evaluate((form: HTMLFormElement) => {
      form.requestSubmit();
      form.requestSubmit();
    });

    await page.waitForTimeout(60);
    expect(state.postAttempts).toBe(1);
    await expect(page.getByRole("button", {name: "Сохранить"})).toBeDisabled();

    await expect(page.locator("[data-right-panel-errors]")).toContainText("Проверьте значение");
    await expect(page.locator("input[name=name]")).toHaveValue("Двойная отправка");
    await expect(page.getByRole("button", {name: "Сохранить"})).toBeEnabled();
    expect(state.postAttempts).toBe(1);
  });

  test("runs a real HTMX validation and success flow", async ({page}) => {
    const state = await mountShell(page);
    await openForm(page);

    await page.locator("input[name=name]").fill("Введённое значение");
    await page.getByRole("button", {name: "Сохранить"}).click();
    await expect(page.locator("[data-right-panel-errors]")).toContainText("Проверьте значение");
    await expect(page.locator("input[name=name]")).toHaveValue("Введённое значение");
    await expect(page.locator("form[data-right-panel-form]")).toHaveAttribute("data-right-panel-dirty", "true");

    await page.getByRole("button", {name: "Сохранить"}).click();
    await expect(page.locator("#global-right-panel")).not.toHaveClass(/active/);
    expect(state.postAttempts).toBe(2);
  });

  test("closes without confirmation on canonical success and fits a narrow viewport", async ({page}) => {
    await page.setViewportSize({width: 390, height: 844});
    await mountShell(page);
    let confirmations = 0;
    await page.evaluate(() => { window.confirm = () => { window.__confirmations += 1; return false; }; window.__confirmations = 0; });
    await openForm(page);
    await page.locator("input[name=name]").fill("Изменено");

    const box = await page.locator("#global-right-panel").boundingBox();
    expect(box?.width).toBeLessThanOrEqual(390);
    const viewport = page.viewportSize();
    expect(viewport).not.toBeNull();
    for (const label of ["Сохранить", "Отмена"]) {
      const button = page.getByRole("button", {name: label});
      await expect(button).toBeVisible();
      const buttonBox = await button.boundingBox();
      expect(buttonBox, `${label}: bounding box`).not.toBeNull();
      expect(buttonBox!.x, `${label}: left edge`).toBeGreaterThanOrEqual(0);
      expect(buttonBox!.y, `${label}: top edge`).toBeGreaterThanOrEqual(0);
      expect(buttonBox!.x + buttonBox!.width, `${label}: right edge`).toBeLessThanOrEqual(viewport!.width);
      expect(buttonBox!.y + buttonBox!.height, `${label}: bottom edge`).toBeLessThanOrEqual(viewport!.height);
    }
    await page.evaluate(() => document.body.dispatchEvent(new CustomEvent("rightPanelFormSucceeded", {detail: {id: "42"}})));

    await expect(page.locator("#global-right-panel")).not.toHaveClass(/active/);
    confirmations = await page.evaluate(() => window.__confirmations);
    expect(confirmations).toBe(0);
  });

  test("traps focus when focus starts outside the open panel", async ({page}) => {
    await mountShell(page);
    await openForm(page);
    await page.evaluate(() => {
      const overlay = document.querySelector("#globalRightPanelOverlay");
      overlay.setAttribute("tabindex", "0");
      overlay.focus();
    });

    await page.keyboard.press("Tab");
    await expect(page.locator("input[name=name]")).toBeFocused();
    await page.evaluate(() => document.querySelector("#globalRightPanelOverlay").focus());
    await page.keyboard.press("Shift+Tab");
    await expect(page.getByRole("button", {name: "Отмена"})).toBeFocused();
  });

  test("rejects authority tricks, backslashes and unsupported outerHTML", async ({page}) => {
    await mountShell(page);
    const commands = [
      {htmx_url: "//evil.test/form/", swap: "innerHTML"},
      {htmx_url: "/\\\\evil.test/form/", swap: "innerHTML"},
      {htmx_url: "/%5C%5Cevil.test/form/", swap: "innerHTML"},
      {htmx_url: "/%2F%2Fevil.test/form/", swap: "innerHTML"},
      {htmx_url: "/%252F%252Fevil.test/form/", swap: "innerHTML"},
      {htmx_url: "/form/#fragment", swap: "innerHTML"},
      {htmx_url: "/form/%23fragment", swap: "innerHTML"},
      {htmx_url: "/form/", swap: "outerHTML"},
    ];

    for (const command of commands) {
      const rejected = await page.evaluate(async (candidate) => {
        try {
          await window.LocalBusinessRightPanel.open({...candidate, target: "#global-right-panel-content"});
          return false;
        } catch (_error) {
          return true;
        }
      }, command);
      expect(rejected).toBe(true);
    }
    await expect(page.locator("#global-right-panel")).not.toHaveClass(/active/);
  });

  test("aborts a load on close and ignores an older out-of-order response", async ({page}) => {
    await mountShell(page);
    await page.evaluate(() => {
      window.LocalBusinessRightPanel.open({htmx_url: "/slow-a/", target: "#global-right-panel-content"});
    });
    await expect(page.locator("#global-right-panel")).toHaveClass(/active/);
    await page.evaluate(() => window.LocalBusinessRightPanel.close());
    await page.waitForTimeout(260);
    await expect(page.locator("#global-right-panel")).not.toHaveClass(/active/);
    await expect(page.locator("#global-right-panel-content")).not.toContainText("Первая панель");

    await page.evaluate(() => {
      window.LocalBusinessRightPanel.open({htmx_url: "/slow-a/", target: "#global-right-panel-content"});
      window.LocalBusinessRightPanel.open({htmx_url: "/slow-b/", target: "#global-right-panel-content"});
    });
    await expect(page.locator("#global-right-panel-content")).toContainText("Вторая панель");
    await page.waitForTimeout(260);
    await expect(page.locator("#global-right-panel-content")).toContainText("Вторая панель");
    await expect(page.locator("#global-right-panel-content")).not.toContainText("Первая панель");
  });

});

declare global {
  interface Window {
    __confirmations: number;
    LocalBusinessRightPanel: {
      open: (command: Record<string, string>) => Promise<boolean>;
      openForm: (command: Record<string, string>) => Promise<boolean>;
      close: (options?: {force?: boolean}) => boolean;
    };
  }
}
