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

test.describe("workorder tree view", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");

  test("switches to tree mode and opens a workorder drawer", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/?view=tree");

    await expect(page.locator("#workorders-tree")).toBeVisible();
    await expect(page.locator('[role="treegrid"]')).toBeVisible();

    const firstWorkorder = page.locator('.workorder-tree-row[data-node-type="workorder"]').first();
    test.skip((await firstWorkorder.count()) === 0, "No visible workorders in tree view.");

    await firstWorkorder.focus();
    await page.keyboard.press("Enter");

    await expect(page.locator("#detail-panel.active")).toBeVisible();
    await expect(page.locator("#detail-panel-content [data-ai-context]")).toBeVisible();

    const context = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(context?.envelope?.selection?.object_type).toBe("workorder");
  });

  test("supports keyboard expand and collapse", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/?view=tree");

    const expandable = page.locator('.workorder-tree-row[data-has-children="true"]').first();
    await expect(expandable).toBeVisible();
    await expandable.focus();
    await page.keyboard.press("ArrowLeft");
    await expect(expandable).toHaveAttribute("aria-expanded", "false");
    await page.keyboard.press("ArrowRight");
    await expect(expandable).toHaveAttribute("aria-expanded", "true");
  });

  test("collapses branches recursively from the toggle button", async ({ page }) => {
    await login(page);
    await page.goto("/workorders/?view=tree");

    const root = page.locator('.workorder-tree-row[data-node-type="organization"]').first();
    await expect(root).toBeVisible();
    const childRows = page.locator('.workorder-tree-row[data-parent-id="organization:root"]');
    await expect(childRows.first()).toBeVisible();

    await root.locator(".tree-toggle").click();
    await expect(root).toHaveAttribute("aria-expanded", "false");
    await expect(childRows.first()).toBeHidden();

    await root.locator(".tree-toggle").click();
    await expect(root).toHaveAttribute("aria-expanded", "true");
    await expect(childRows.first()).toBeVisible();

    const expandedDescendants = await page
      .locator('.workorder-tree-row[data-has-children="true"]:not([data-node-id="organization:root"])')
      .evaluateAll((nodes) => nodes.filter((node) => node.getAttribute("aria-expanded") === "true").length);
    expect(expandedDescendants).toBe(0);
  });
});

declare global {
  interface Window {
    LocalBusinessPageContext?: {
      getCurrent: () => {
        envelope?: {
          selection?: { object_type?: string; object_id?: string };
        };
      };
    };
  }
}
