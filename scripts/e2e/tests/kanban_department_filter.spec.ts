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
  test.setTimeout(60_000);
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");

  test("показывает только канбан и фильтрует деревом подразделений и изделий", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/?view=tree");

    await expect(page).not.toHaveURL(/(?:\?|&)view=/);
    await expect(page.locator("#workorders-view")).toBeVisible();
    await expect(page.locator("#board-columns")).toBeVisible();
    await expect(page.locator("#workorders-tree")).toHaveCount(0);
    await expect(page.locator("[data-workorders-filter-panel]")).toBeVisible();
    await expect(page.locator("[data-workorders-ai-panel]")).toBeHidden();
    await expect(page.getByText("Обычный клик выбирает один элемент.", { exact: false })).toHaveCount(0);

    const visibleLabels = page.locator("[data-department-filter-select]:visible .department-filter-node-label");
    expect(await visibleLabels.count()).toBeGreaterThan(0);
    for (const label of await visibleLabels.all()) {
      await expect.poll(async () => Math.round((await label.boundingBox())?.width || 0)).toBeGreaterThan(8);
    }

    let filterRequests = 0;
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname.startsWith("/workorders/") && request.method() === "GET") filterRequests += 1;
    });
    await page.locator("[data-department-filter-search]").fill("несуществующее подразделение");
    await page.waitForTimeout(350);
    expect(filterRequests).toBe(0);
    await page.locator("[data-department-filter-search]").fill("");

    const departmentNode = page.locator('[data-department-filter-node][data-node-kind="department"]').first();
    test.skip((await departmentNode.count()) === 0, "У пользователя нет доступных подразделений для фильтра.");
    const department = departmentNode.locator(":scope > .department-filter-node-row > [data-department-filter-select]");
    const departmentValue = departmentNode.locator(":scope > .department-filter-node-row > [data-department-filter-value]");
    const departmentId = await departmentValue.getAttribute("value");
    await expect(department).toHaveAttribute("role", "treeitem");
    await expect(departmentValue).toHaveAttribute("form", "workorder-filters");
    const contextUpdate = page.waitForRequest((request) => {
      if (!request.url().includes("/ai/context/window/") || request.method() !== "POST") return false;
      const body = request.postDataJSON();
      return Array.isArray(body?.filters?.department) && body.filters.department.includes(departmentId);
    });
    await department.click();
    await expect(department).toHaveAttribute("aria-selected", "true");
    await expect.poll(() => new URL(page.url()).searchParams.getAll("department")).toContain(departmentId);
    await contextUpdate;

    await page.locator("#boardStatus summary").click();
    await page.locator("#boardStatus_new").check();
    await expect.poll(() => new URL(page.url()).searchParams.getAll("status")).toContain("new");
    expect(new URL(page.url()).searchParams.getAll("department")).toContain(departmentId);

    await page.reload();
    await expect(page.locator(`[data-department-filter-value][name="department"][value="${departmentId}"]`)).not.toBeDisabled();
    await expect(page.locator("#boardStatus_new")).toBeChecked();
  });

  test("поддерживает множественный выбор и контекстное действие изделия", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/");

    const rootDepartments = page.locator(
      '[data-department-filter-node][data-node-kind="department"][data-parent-key=""] > .department-filter-node-row > [data-department-filter-select]',
    );
    if ((await rootDepartments.count()) >= 2) {
      const firstDepartmentId = await rootDepartments.nth(0)
        .locator("xpath=../input[@data-department-filter-value]")
        .getAttribute("value");
      await rootDepartments.nth(0).click();
      await expect(rootDepartments.nth(0)).toHaveAttribute("aria-selected", "true");
      await expect.poll(() => new URL(page.url()).searchParams.getAll("department")).toContain(firstDepartmentId);
      await rootDepartments.nth(1).click({ modifiers: ["Control"] });
      await expect(rootDepartments.nth(0)).toHaveAttribute("aria-selected", "true");
      await expect(rootDepartments.nth(1)).toHaveAttribute("aria-selected", "true");
    }

    const deviceNode = page.locator('[data-department-filter-node][data-node-kind="device"]').first();
    const device = deviceNode.locator(":scope > .department-filter-node-row > [data-department-filter-select]");
    if (await deviceNode.count()) {
      const deviceLabel = device.locator(".department-filter-node-label");
      const deviceName = (await deviceLabel.textContent())?.trim() || "";
      await page.locator("[data-department-filter-search]").fill(deviceName);
      await expect(device).toBeVisible();
      await expect.poll(async () => Math.round((await deviceLabel.boundingBox())?.width || 0)).toBeGreaterThan(40);
      await device.click();
      await expect(device).toHaveAttribute("aria-selected", "true");
      const create = deviceNode.locator(":scope > .department-filter-node-row > [data-department-filter-create-workorder]");
      await expect(create).toBeVisible();
      await expect(create).toHaveAttribute("title", "Создать заявку");
      const request = page.waitForRequest((candidate) => candidate.url().includes("/workorders/new/") && candidate.url().includes("device="));
      await create.click();
      await request;
      await expect(page.locator("#detail-panel")).toHaveClass(/active/);
    }
  });

  test("сворачивает ветви рекурсивно и помнит раскрытые узлы", async ({ page, context }) => {
    await login(page);
    await page.evaluate(() => localStorage.removeItem("workorders_department_tree_expanded_v1"));
    await page.goto("/workorders/");

    const root = page.locator(
      '[data-department-filter-node][data-parent-key=""][data-has-children="true"]',
    ).first();
    test.skip((await root.count()) === 0, "У пользователя нет ветвей с вложенными узлами.");

    const rootToggle = root.locator(":scope > .department-filter-node-row > [data-department-filter-toggle]");
    const rootChildren = root.locator(":scope > ul");
    await expect(rootToggle).toHaveAttribute("aria-expanded", "false");
    await expect(rootChildren).toBeHidden();

    const descendantLabel = root.locator(
      '[data-department-filter-node] .department-filter-node-label',
    ).first();
    if (await descendantLabel.count()) {
      const descendantName = (await descendantLabel.textContent())?.trim() || "";
      await page.locator("[data-department-filter-search]").fill(descendantName);
      await expect(rootToggle).toHaveAttribute("aria-expanded", "true");
      await page.locator("[data-department-filter-search]").fill("");
      await expect(rootToggle).toHaveAttribute("aria-expanded", "false");
      await expect(rootChildren).toBeHidden();
    }

    await rootToggle.click();
    await expect(rootToggle).toHaveAttribute("aria-expanded", "true");
    await expect(rootChildren).toBeVisible();

    const nested = root.locator(
      '[data-department-filter-node][data-has-children="true"]',
    ).first();
    if (await nested.count()) {
      const nestedToggle = nested.locator(":scope > .department-filter-node-row > [data-department-filter-toggle]");
      await nestedToggle.click();
      await expect(nestedToggle).toHaveAttribute("aria-expanded", "true");

      await rootToggle.click();
      await expect(rootToggle).toHaveAttribute("aria-expanded", "false");
      await expect(nestedToggle).toHaveAttribute("aria-expanded", "false");
      await expect(rootChildren).toBeHidden();

      await rootToggle.click();
      await expect(nestedToggle).toHaveAttribute("aria-expanded", "false");
    }

    await page.reload();
    await expect(rootToggle).toHaveAttribute("aria-expanded", "true");
    await expect(rootChildren).toBeVisible();

    await page.close();
    const reopenedPage = await context.newPage();
    await reopenedPage.goto("/workorders/");
    const reopenedRoot = reopenedPage.locator(
      '[data-department-filter-node][data-parent-key=""][data-has-children="true"]',
    ).first();
    await expect(
      reopenedRoot.locator(":scope > .department-filter-node-row > [data-department-filter-toggle]"),
    ).toHaveAttribute("aria-expanded", "true");
  });

  test("стабильно изменяет ширину и действительно сворачивает панель", async ({ page }) => {
    await login(page);
    await page.evaluate(() => {
      localStorage.removeItem("sidebarCollapsed");
      localStorage.removeItem("workorders_sidebar_width");
    });
    await page.goto("/workorders/");

    await page.setViewportSize({ width: 1280, height: 900 });
    const sidebar = page.locator("#sidebar");
    const handle = page.locator("[data-workorders-sidebar-resize]");
    const rightPanel = page.locator("#detail-panel");
    await expect(handle).toHaveAttribute("role", "separator");
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(320);

    await page.evaluate(() => (window as typeof window & { openWorkorderDrawer: () => void }).openWorkorderDrawer());
    await expect(rightPanel).toHaveClass(/active/);
    await expect(rightPanel).toBeVisible();
    await expect.poll(async () => {
      const box = await rightPanel.boundingBox();
      return Math.round((box?.x || 0) + (box?.width || 0));
    }).toBe(1280);
    const initialRightPanelWidth = Math.round((await rightPanel.boundingBox())?.width || 0);

    await handle.focus();
    const initial = Number(await handle.getAttribute("aria-valuenow"));
    await page.keyboard.press("ArrowRight");
    await expect.poll(async () => Number(await handle.getAttribute("aria-valuenow"))).toBe(initial + 16);
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(initial + 16);
    await expect.poll(async () => Math.round((await rightPanel.boundingBox())?.width || 0)).toBe(
      initialRightPanelWidth - 16,
    );
    await page.evaluate(() => (window as typeof window & { closeWorkorderDrawer: () => void }).closeWorkorderDrawer());

    const handleBox = await handle.boundingBox();
    expect(handleBox).not.toBeNull();
    await page.mouse.move((handleBox?.x || 0) + (handleBox?.width || 0) / 2, (handleBox?.y || 0) + 100);
    await page.mouse.down();
    await page.mouse.move(420, (handleBox?.y || 0) + 100, { steps: 5 });
    await page.mouse.up();
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(420);

    await page.reload();
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(420);

    await page.evaluate(() => (window as typeof window & { openWorkorderDrawer: () => void }).openWorkorderDrawer());
    await expect.poll(async () => {
      const box = await rightPanel.boundingBox();
      return Math.round((box?.x || 0) + (box?.width || 0));
    }).toBe(1280);
    const sidebarBox = await sidebar.boundingBox();
    const constrainedRightPanelBox = await rightPanel.boundingBox();
    expect(constrainedRightPanelBox).not.toBeNull();
    expect(sidebarBox).not.toBeNull();
    expect(Math.round(constrainedRightPanelBox?.x || 0)).toBeGreaterThanOrEqual(
      Math.round((sidebarBox?.x || 0) + (sidebarBox?.width || 0)),
    );
    expect(Math.round(constrainedRightPanelBox?.width || 0)).toBeLessThan(initialRightPanelWidth);
    expect(Math.round((constrainedRightPanelBox?.x || 0) + (constrainedRightPanelBox?.width || 0))).toBe(1280);
    await page.evaluate(() => (window as typeof window & { closeWorkorderDrawer: () => void }).closeWorkorderDrawer());

    const toggle = page.locator(".sidebar-toggle");
    await toggle.click();
    await expect(sidebar).toHaveClass(/collapsed/);
    await expect(toggle).toHaveAttribute("aria-expanded", "false");
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(68);
    await expect(handle).toBeHidden();

    await toggle.click();
    await expect(sidebar).not.toHaveClass(/collapsed/);
    await expect(toggle).toHaveAttribute("aria-expanded", "true");
    await expect.poll(async () => Math.round((await sidebar.boundingBox())?.width || 0)).toBe(420);
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
