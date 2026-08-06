import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const aiUiDriver = process.env.E2E_AI_UI_DRIVER || "native";

async function login(page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/accounts\/login\//);
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
}

test.describe("@workorders канбан и фильтр подразделений", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");

  test("показывает только канбан и хранит выбранные фильтры в URL", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/?view=tree");

    await expect(page).not.toHaveURL(/(?:\?|&)view=/);
    await expect(page.locator("#workorders-view")).toBeVisible();
    await expect(page.locator("#board-columns")).toBeVisible();
    await expect(page.locator("#workorders-tree")).toHaveCount(0);
    await expect(page.locator("[data-workorders-filter-panel]")).toBeVisible();
    await expect(page.locator("[data-workorders-ai-panel]")).toBeHidden();

    let filterRequests = 0;
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/workorders/") && request.method() === "GET") filterRequests += 1;
    });
    await page.locator("[data-department-filter-search]").fill("несуществующее подразделение");
    await page.waitForTimeout(350);
    expect(filterRequests).toBe(0);
    await page.locator("[data-department-filter-search]").fill("");

    const department = page.locator("[data-department-filter-checkbox]").first();
    test.skip((await department.count()) === 0, "У пользователя нет доступных подразделений для фильтра.");
    const departmentId = await department.getAttribute("value");
    await expect(department).toHaveAttribute("form", "workorder-filters");
    const contextUpdate = page.waitForRequest((request) => {
      if (!request.url().includes("/ai/context/window/") || request.method() !== "POST") return false;
      const body = request.postDataJSON();
      return Array.isArray(body?.filters?.department) && body.filters.department.includes(departmentId);
    });
    await department.check();
    await expect.poll(() => new URL(page.url()).searchParams.getAll("department")).toContain(departmentId);
    await contextUpdate;

    await page.locator("#boardStatus summary").click();
    await page.locator("#boardStatus_new").check();
    await expect.poll(() => new URL(page.url()).searchParams.getAll("status")).toContain("new");
    expect(new URL(page.url()).searchParams.getAll("department")).toContain(departmentId);

    await page.reload();
    await expect(page.locator(`[data-department-filter-checkbox][value="${departmentId}"]`)).toBeChecked();
    await expect(page.locator("#boardStatus_new")).toBeChecked();
  });

  test("разворачивает и сворачивает ИИ-чат без пересоздания клиента", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/");

    const shell = page.locator("[data-workorders-sidebar-shell]");
    const launcher = page.locator("[data-workorders-ai-launcher]");
    const panel = page.locator("[data-workorders-ai-panel]");
    const driverRoot = panel.locator("#native-ai-sidebar-root, #copilotkit-sidebar-root");

    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "filters");
    const hasDriverRoot = (await driverRoot.count()) > 0;
    if (hasDriverRoot) await driverRoot.evaluate((node) => { (node as HTMLElement).dataset.e2eRoot = "preserved"; });
    await launcher.focus();
    await launcher.press("Enter");
    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "chat");
    await expect(launcher).toHaveAttribute("aria-expanded", "true");
    await expect(panel).toBeVisible();

    const textbox = panel.getByRole("textbox").last();
    if (await textbox.count()) await expect(textbox).toBeFocused();

    await page.locator("[data-workorders-ai-collapse]").click();
    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "filters");
    await expect(launcher).toBeFocused();
    await expect(panel).toBeHidden();
    await expect(launcher).toHaveAttribute("aria-expanded", "false");
    if (hasDriverRoot) await expect(driverRoot).toHaveAttribute("data-e2e-root", "preserved");

    await launcher.press("Space");
    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "chat");
    await page.locator("#boardSearch").focus();
    await page.keyboard.press("Escape");
    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "chat");
    if (await textbox.count()) {
      await textbox.focus();
      await page.keyboard.press("Escape");
      await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "filters");
    }

    await page.reload();
    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "filters");
  });

  test("не возвращает скрытый фокус после завершения потока", async ({ page }) => {
    test.skip(aiUiDriver !== "native", "Проверка управляемого потока относится к native-драйверу.");
    let releaseResponse: (() => void) | undefined;
    const responseGate = new Promise<void>((resolve) => { releaseResponse = resolve; });
    await page.route("**/ai/ui/ag-ui/run/", async (route) => {
      await responseGate;
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"type":"RUN_STARTED","threadId":"thread","runId":"run"}',
          "",
          'data: {"type":"TEXT_MESSAGE_START","messageId":"msg","role":"assistant"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"готово"}',
          "",
          'data: {"type":"TEXT_MESSAGE_END","messageId":"msg"}',
          "",
          'data: {"type":"RUN_FINISHED","threadId":"thread","runId":"run","outcome":{"type":"success"}}',
          "",
          "",
        ].join("\n"),
      });
    });

    await login(page);
    await page.goto("/workorders/");
    const shell = page.locator("[data-workorders-sidebar-shell]");
    const launcher = page.locator("[data-workorders-ai-launcher]");
    await launcher.click();
    const input = page.locator("#native-ai-sidebar-root textarea");
    const requestStarted = page.waitForRequest((request) => request.url().includes("/ai/ui/ag-ui/run/"));
    await input.fill("Проверка сворачивания");
    await input.press("Enter");
    await requestStarted;

    await page.locator("[data-workorders-ai-collapse]").click();
    await expect(launcher).toBeFocused();
    releaseResponse?.();

    await expect(shell).toHaveAttribute("data-ai-sidebar-mode", "filters");
    await expect(launcher).toContainText("Ответ ИИ готов");
    await expect(launcher).toBeFocused();
  });

  test("на мобильном экране открывает панель как доступный диалог", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await login(page);
    await page.goto("/workorders/");

    const sidebar = page.locator("#sidebar");
    await page.locator(".sidebar-toggle").click();
    await expect(sidebar).toHaveAttribute("data-workorders-sidebar-open", "true");
    await expect(sidebar).toHaveAttribute("role", "dialog");
    await expect(sidebar).toHaveAttribute("aria-modal", "true");

    const close = page.locator("[data-workorders-sidebar-close]");
    const size = await close.boundingBox();
    expect(size?.height).toBeGreaterThanOrEqual(44);
    expect(size?.width).toBeGreaterThanOrEqual(44);
    await page.keyboard.press("Shift+Tab");
    expect(await page.evaluate(() => document.querySelector("#sidebar")?.contains(document.activeElement))).toBe(true);
    await close.focus();
    await close.click();
    await expect(sidebar).not.toHaveAttribute("data-workorders-sidebar-open", "true");
    await expect(page.locator(".sidebar-toggle")).toBeFocused();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  });
});
