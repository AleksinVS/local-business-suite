import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const aiUiDriver = process.env.E2E_AI_UI_DRIVER || "native";

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

  test("native chat UX parity: loads config, starts a new chat and handles AG-UI events", async ({ page }) => {
    let aguiRequestSeen = false;
    let newThreadId = "";
    let panelLoads = 0;
    await page.route("**/e2e-native-panel/", async (route) => {
      panelLoads += 1;
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: '<div class="drawer-content"><div data-ai-context="{&quot;selection&quot;:{&quot;object_type&quot;:&quot;workorder&quot;,&quot;object_id&quot;:&quot;e2e-native&quot;,&quot;source_code&quot;:&quot;workorders&quot;,&quot;display&quot;:&quot;Native panel&quot;}}">Native panel opened</div></div>',
      });
    });
    await page.route("**/ai/ui/ag-ui/run/", async (route) => {
      aguiRequestSeen = true;
      const body = route.request().postDataJSON();
      const lastMessage = body.messages[body.messages.length - 1];
      expect(body.threadId).toBeTruthy();
      if (newThreadId) expect(body.threadId).toBe(newThreadId);
      expect(lastMessage?.role).toBe("user");
      expect(body.forwardedProps?.ui_driver).toBe("native");
      expect(body.forwardedProps?.page_context?.envelope?.page?.path).toBe("/workorders/");
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"type":"RUN_STARTED","threadId":"thread","runId":"run"}',
          "",
          'data: {"type":"CUSTOM","name":"local_business.protocol","value":{"local_business_protocol":"1.0","agui_profile":"ag-ui@0.0.55"}}',
          "",
          'data: {"type":"TOOL_CALL_START","toolCallId":"tool-1","toolCallName":"workorders.open_right_panel"}',
          "",
          'data: {"type":"TOOL_CALL_ARGS","toolCallId":"tool-1","delta":"{\\"object_id\\":\\"e2e-native\\"}"}',
          "",
          'data: {"type":"TOOL_CALL_END","toolCallId":"tool-1"}',
          "",
          'data: {"type":"TOOL_CALL_RESULT","toolCallId":"tool-1","content":"{\\"status\\":\\"completed\\"}"}',
          "",
          'data: {"type":"STATE_DELTA","delta":[{"op":"replace","path":"/localBusiness/uiCommands","value":[{"type":"open_right_panel","version":"1.0","source_code":"workorders","object_type":"workorder","object_id":"e2e-native","mode":"view","title":"Native panel","htmx_url":"/e2e-native-panel/","target":"#global-right-panel-content","swap":"innerHTML","drawer_size":"large"}]}]}',
          "",
          'data: {"type":"CUSTOM","name":"local_business.ui_command","value":{"type":"open_right_panel","version":"1.0","source_code":"workorders","object_type":"workorder","object_id":"e2e-native","mode":"view","title":"Native panel","htmx_url":"/e2e-native-panel/","target":"#global-right-panel-content","swap":"innerHTML","drawer_size":"large"}}',
          "",
          'data: {"type":"SOME_FUTURE_EVENT","value":{"ignored":true}}',
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
    expect(config.urls?.clear_session_url).toBe("/ai/ui/session/clear/");
    expect(config.urls?.full_chat_url).toContain("/ai/chat/");
    expect(config.urls?.model_update_url).toContain("/ai/chat/");
    expect(config.models?.length).toBeGreaterThan(0);

    const root = page.locator("#native-ai-sidebar-root");
    await expect(root).toBeVisible();
    await expect(page.locator('script[src*="native_ai.js?v=20260610-native-ag-ui-chat"]')).toHaveCount(1);
    await expect(page.locator("#copilotkit-sidebar-root")).toHaveCount(0);
    await expect(page.locator("#sidebar-ai-chat")).toHaveCount(0);
    await expect(root.getByRole("button", { name: "Очистить чат" })).toBeVisible();
    await expect(root.getByRole("link", { name: "Открыть полный чат" })).toHaveAttribute("href", config.urls.full_chat_url);

    const modelSelect = root.locator("[data-native-ai-model]");
    await expect(modelSelect).toBeVisible();
    const selectedModel = await modelSelect.inputValue();
    const nextModel = config.models.find((model) => model.id && model.id !== selectedModel);
    if (nextModel) {
      const modelUpdateResponse = page.waitForResponse((response) => (
        response.url().includes("/ai/chat/")
        && response.url().includes("/model/")
        && response.request().method() === "POST"
        && response.status() === 200
      ));
      await modelSelect.selectOption(nextModel.id);
      const modelUpdatePayload = await (await modelUpdateResponse).json();
      expect(modelUpdatePayload.model_id).toBe(nextModel.id);
    }

    const newSessionResponse = page.waitForResponse((response) => (
      response.url().includes("/ai/ui/session/new/")
      && response.request().method() === "POST"
      && response.status() === 200
    ));
    await root.getByRole("button", { name: "Новый чат" }).click();
    const newSessionPayload = await (await newSessionResponse).json();
    newThreadId = newSessionPayload.thread_id;
    expect(newSessionPayload.driver).toBe("native");
    if (nextModel) expect(newSessionPayload.current_model_id).toBe(nextModel.id);

    const input = root.locator("textarea");
    await input.fill("Коротко ответь: ok");
    await input.press("Enter");

    await expect(root.locator(".native-ai-ui-message.is-assistant .native-ai-ui-bubble").last()).toHaveText("ok");
    await expect(root.locator(".native-ai-ui-message.is-user time").last()).toHaveText(/\d{2}:\d{2}/);
    await expect(root.locator(".native-ai-ui-message.is-tool .native-ai-ui-bubble").last()).toHaveText("Результат получен");
    await expect(page.locator("#global-right-panel.active")).toBeVisible();
    await expect(page.locator("#global-right-panel-content")).toContainText("Native panel opened");
    expect(aguiRequestSeen).toBe(true);
    expect(panelLoads).toBe(1);

    const clearSessionResponse = page.waitForResponse((response) => (
      response.url().includes("/ai/ui/session/clear/")
      && response.request().method() === "POST"
      && response.status() === 200
    ));
    page.once("dialog", (dialog) => dialog.accept());
    await root.getByRole("button", { name: "Очистить чат" }).click();
    const clearPayload = await (await clearSessionResponse).json();
    expect(clearPayload.messages).toEqual([]);
    await expect(root.locator(".native-ai-ui-message")).toHaveCount(0);
  });

  test("shows RUN_ERROR without leaving the form locked", async ({ page }) => {
    await page.route("**/ai/ui/ag-ui/run/", async (route) => {
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          'data: {"type":"RUN_STARTED","threadId":"thread","runId":"run"}',
          "",
          'data: {"type":"RUN_ERROR","message":"LLM не настроен","code":"service_not_configured"}',
          "",
          "",
        ].join("\n"),
      });
    });

    await login(page);
    await page.goto("/workorders/");

    const root = page.locator("#native-ai-sidebar-root");
    await expect(root).toBeVisible();
    const input = root.locator("textarea");
    await input.fill("Проверка ошибки");
    await input.press("Enter");

    await expect(root.locator(".native-ai-ui-message.is-assistant.is-error .native-ai-ui-bubble").last()).toHaveText("LLM не настроен");
    await expect(input).toBeEnabled();
  });
});
