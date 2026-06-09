import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const aiUiDriver = process.env.E2E_AI_UI_DRIVER || "legacy";

async function login(page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
}

test.describe("native AG-UI-compatible sidebar", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");
  test.skip(aiUiDriver !== "native", "Native AI UI checks run only when E2E_AI_UI_DRIVER=native.");

  test("loads native sidebar config and renders an AG-UI stream response", async ({ page }) => {
    let aguiRequestSeen = false;
    await page.route("**/ai/ui/ag-ui/run/", async (route) => {
      aguiRequestSeen = true;
      const body = route.request().postDataJSON();
      const lastMessage = body.messages[body.messages.length - 1];
      expect(body.threadId).toBeTruthy();
      expect(lastMessage?.role).toBe("user");
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"type":"RUN_STARTED","threadId":"thread","runId":"run"}',
          "",
          'data: {"type":"CUSTOM","name":"local_business.protocol","value":{"local_business_protocol":"1.0"}}',
          "",
          'data: {"type":"TEXT_MESSAGE_START","messageId":"msg","role":"assistant"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"msg","delta":"ok"}',
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

    const config = await page.evaluate(async () => {
      const response = await fetch("/ai/ui/config/", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error(`AI UI config failed: ${response.status}`);
      return response.json();
    });

    expect(config.enabled).toBe(true);
    expect(config.driver).toBe("native");
    expect(config.runtime_url).toBe("/ai/ui/ag-ui/run/");
    expect(config.forwarded_props?.ui_driver).toBe("native");
    expect(config.forwarded_props?.signature).toMatch(/^[a-f0-9]{64}$/);

    const root = page.locator("#native-ai-sidebar-root");
    await expect(root).toBeVisible();
    await expect(page.locator("#copilotkit-sidebar-root")).toHaveCount(0);
    await expect(page.locator("#sidebar-ai-chat")).toHaveCount(0);

    const input = root.locator("textarea");
    await input.fill("Коротко ответь: ok");
    await input.press("Enter");

    await expect(root.locator(".native-ai-ui-message.is-assistant .native-ai-ui-bubble").last()).toHaveText("ok");
    expect(aguiRequestSeen).toBe(true);
  });
});
