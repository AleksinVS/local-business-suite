import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const aiUiDriver = process.env.E2E_AI_UI_DRIVER || "native";
const unavailableMessage = "В данный момент, ИИ-чат недоступен, обратитесь к администратору портала";

async function login(page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page).not.toHaveURL(/\/accounts\/login\//);
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
}

test.describe("@ai native AG-UI-compatible sidebar", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");
  test.skip(aiUiDriver !== "native", "Native AI UI checks run only when E2E_AI_UI_DRIVER=native.");

  test("native chat UX parity: loads config, starts a new chat and handles AG-UI events", async ({ page }) => {
    let prepareRequestSeen = false;
    let aguiRequestSeen = false;
    let newThreadId = "";
    let preparedRunId = "";
    let panelLoads = 0;
    await page.route("**/e2e-native-panel/", async (route) => {
      panelLoads += 1;
      await route.fulfill({
        status: 200,
        contentType: "text/html",
        body: '<div class="drawer-content"><div data-ai-context="{&quot;selection&quot;:{&quot;object_type&quot;:&quot;workorder&quot;,&quot;object_id&quot;:&quot;e2e-native&quot;,&quot;source_code&quot;:&quot;workorders&quot;,&quot;display&quot;:&quot;Native panel&quot;}}">Native panel opened</div></div>',
      });
    });
    await page.route("**/ai/chat/*/turn/prepare/", async (route) => {
      prepareRequestSeen = true;
      const body = route.request().postData() || "";
      expect(body).toContain("name=\"run_id\"");
      expect(body).toContain("name=\"prompt\"");
      expect(body).toContain("name=\"surface\"");
      expect(body).toContain("name=\"page_context\"");
      const runMatch = /name="run_id"[^]*?\r?\n\r?\n([^\r\n]+)/.exec(body);
      preparedRunId = runMatch ? runMatch[1] : "native-e2e-run";
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ message_id: "e2e-user-message", assistant_message_id: "e2e-assistant-message", run_id: preparedRunId }),
      });
    });
    await page.route("**/ai/chat/*/turn/run/", async (route) => {
      aguiRequestSeen = true;
      const body = route.request().postDataJSON();
      expect(body.threadId).toBeTruthy();
      if (newThreadId) expect(body.threadId).toBe(newThreadId);
      expect(body.runId).toBe(preparedRunId);
      expect(Object.keys(body).sort()).toEqual(["runId", "threadId"]);
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: {"type":"RUN_STARTED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
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
          `data: {"type":"RUN_FINISHED","threadId":"${body.threadId}","runId":"${body.runId}","outcome":{"type":"success"}}`,
          "",
          "",
        ].join("\n"),
      });
    });

    await login(page);
    await page.goto("/workorders/");
    await page.locator("[data-workorders-ai-launcher]").click();

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
    expect(config.runtime_url).toContain("/ai/chat/");
    expect(config.prepare_url).toContain("/turn/prepare/");
    expect(config.forwarded_props).toBeUndefined();
    expect(config.urls?.clear_session_url).toBe("/ai/ui/session/clear/");
    expect(config.urls?.full_chat_url).toContain("/ai/chat/");
    expect(config.urls?.model_update_url).toContain("/ai/chat/");
    expect(config.models?.length).toBeGreaterThan(0);

    const root = page.locator("#native-ai-sidebar-root");
    await expect(root).toBeVisible();
    await expect(page.locator('script[src*="native_ai.js?v="]')).toHaveCount(1);
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
    expect(prepareRequestSeen).toBe(true);
    expect(aguiRequestSeen).toBe(true);
    expect(panelLoads).toBe(1);

    await page.evaluate(() => (window as any).closeGlobalRightPanel?.());
    await expect(page.locator("#global-right-panel.active")).toHaveCount(0);
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
    let releaseRunResponse: (() => void) | undefined;
    await page.route("**/ai/chat/*/turn/prepare/", async (route) => {
      const body = route.request().postData() || "";
      const runMatch = /name="run_id"[^]*?\r?\n\r?\n([^\r\n]+)/.exec(body);
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        body: JSON.stringify({ message_id: "e2e-error-user", assistant_message_id: "e2e-error-assistant", run_id: runMatch ? runMatch[1] : "native-error-run" }),
      });
    });
    await page.route("**/ai/chat/*/turn/run/", async (route) => {
      const body = route.request().postDataJSON();
      await new Promise<void>((resolve) => {
        releaseRunResponse = resolve;
      });
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: {"type":"RUN_STARTED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
          "",
          'data: {"type":"RUN_ERROR","message":"LLM не настроен","code":"service_not_configured"}',
          "",
          "",
        ].join("\n"),
      });
    });

    await login(page);
    await page.goto("/workorders/");
    await page.locator("[data-workorders-ai-launcher]").click();

    const root = page.locator("#native-ai-sidebar-root");
    await expect(root).toBeVisible();
    const input = root.locator("textarea");
    await page.evaluate(() => {
      (window as any).__nativeAiLastRunError = null;
      document.addEventListener("workorders:ai-run-finished", (event) => {
        (window as any).__nativeAiLastRunError = (event as CustomEvent).detail?.error;
      }, { once: true });
    });
    await input.fill("Проверка ошибки");
    await input.press("Enter");
    await expect.poll(() => Boolean(releaseRunResponse)).toBe(true);
    await root.getByRole("button", { name: "Свернуть ИИ-чат" }).click();
    releaseRunResponse?.();

    await expect(root.locator(".native-ai-ui-message.is-assistant.is-error .native-ai-ui-bubble").last()).toHaveText(unavailableMessage);
    await expect(input).toBeEnabled();
    await expect.poll(() => page.evaluate(() => (window as any).__nativeAiLastRunError)).toBe(true);
  });

  test("resumes the prepared turn after reload without duplicating the user message", async ({ page }) => {
    const recoverableRunId = "native-recoverable-run";
    let runRequests = 0;
    await page.route("**/ai/chat/*/config/", async (route) => {
      const response = await route.fetch();
      const payload = await response.json();
      payload.messages = [{
        id: "recoverable-user-message",
        role: "user",
        content: "Продолжить потерянный запрос",
        created_at_display: "12:00",
        attachments: [],
      }];
      payload.recoverable_run = {
        status: "prepared",
        run_id: recoverableRunId,
        message_id: "recoverable-user-message",
        assistant_message_id: null,
      };
      await route.fulfill({ response, json: payload });
    });
    await page.route("**/ai/chat/*/turn/run/", async (route) => {
      runRequests += 1;
      const body = route.request().postDataJSON();
      expect(body.runId).toBe(recoverableRunId);
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: {"type":"RUN_STARTED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
          "",
          'data: {"type":"TEXT_MESSAGE_START","messageId":"recoverable-assistant"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"recoverable-assistant","delta":"Запрос восстановлен"}',
          "",
          'data: {"type":"TEXT_MESSAGE_END","messageId":"recoverable-assistant"}',
          "",
          `data: {"type":"RUN_FINISHED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
          "",
          "",
        ].join("\n"),
      });
    });

    await login(page);
    await page.goto("/ai/chat/");
    const root = page.locator("[data-native-ai-root][data-surface=full_page]");
    await expect(root).toBeVisible();
    await expect(root.locator(".native-ai-ui-message.is-user")).toHaveCount(1);
    await expect(root.locator(".native-ai-ui-message.is-user .native-ai-ui-bubble")).toHaveText("Продолжить потерянный запрос");
    await expect(root.locator(".native-ai-ui-message.is-assistant .native-ai-ui-bubble").last()).toHaveText("Запрос восстановлен");
    expect(runRequests).toBe(1);
  });

  test("native full-page mount supports local commands, title and safe markdown", async ({ page }) => {
    let runId = "";
    let releaseRunResponse: (() => void) | undefined;
    await page.route("**/ai/chat/*/title/", async (route) => {
      await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ title: "Переименованный чат" }) });
    });
    await page.route("**/ai/chat/*/turn/prepare/", async (route) => {
      const body = route.request().postData() || "";
      const runMatch = /name="run_id"[^]*?\r?\n\r?\n([^\r\n]+)/.exec(body);
      runId = runMatch ? runMatch[1] : "native-full-page-run";
      await route.fulfill({ status: 201, contentType: "application/json", body: JSON.stringify({ message_id: "full-user", assistant_message_id: "full-assistant", run_id: runId }) });
    });
    await page.route("**/ai/chat/*/turn/run/", async (route) => {
      const body = route.request().postDataJSON();
      await new Promise<void>((resolve) => {
        releaseRunResponse = resolve;
      });
      await route.fulfill({
        status: 200,
        contentType: "text/event-stream",
        body: [
          `data: {"type":"RUN_STARTED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
          "",
          'data: {"type":"TEXT_MESSAGE_START","messageId":"full-assistant"}',
          "",
          'data: {"type":"TEXT_MESSAGE_CONTENT","messageId":"full-assistant","delta":"**safe** [bad](javascript:alert(1))"}',
          "",
          'data: {"type":"TEXT_MESSAGE_END","messageId":"full-assistant"}',
          "",
          `data: {"type":"RUN_FINISHED","threadId":"${body.threadId}","runId":"${body.runId}"}`,
          "",
        ].join("\n"),
      });
    });
    await login(page);
    await page.goto("/ai/chat/");
    const root = page.locator("[data-native-ai-root][data-surface=full_page]");
    await expect(root).toBeVisible();
    await expect(page.locator('script[src*="dompurify"], script[src*="marked"]')).toHaveCount(0);

    await root.locator("[data-native-ai-title-edit]").click();
    await root.locator("[data-native-ai-title-input]").fill("Переименованный чат");
    await root.locator("[data-native-ai-title-save]").click();
    await expect(root.locator("[data-native-ai-title]")).toHaveText("Переименованный чат");

    await root.locator("[data-native-ai-command-button]").click();
    await expect(root.locator("[data-native-ai-command-list] [role=option]").first()).toBeVisible();
    await root.locator("[data-native-ai-command-search]").fill("команды");
    await expect(root.locator("[data-native-ai-command-list] [role=option]")).toHaveCount(1);

    const fileInput = root.locator("[data-native-ai-file-input]");
    await fileInput.setInputFiles({ name: "note.txt", mimeType: "text/plain", buffer: Buffer.from("hello") });
    await expect(root.locator("[data-native-ai-attachment-preview]")).toBeVisible();
    await root.locator("[data-native-ai-attachment-preview] button").click();
    await expect(root.locator("[data-native-ai-attachment-preview]")).toBeHidden();

    await root.locator("[data-native-ai-prompt]").fill("Покажи markdown");
    await root.locator("[data-native-ai-prompt]").press("Enter");
    await expect.poll(() => Boolean(releaseRunResponse)).toBe(true);
    for (const selector of [
      "[data-native-ai-file-input]",
      "[data-native-ai-command-button]",
      "[data-native-ai-command-search]",
      "[data-native-ai-title-edit]",
      "[data-native-ai-title-save]",
      "[data-native-ai-title-cancel]",
      "[data-native-ai-delete]",
      "[data-native-ai-model]",
      "[data-native-ai-send]",
      "[data-native-ai-prompt]",
    ]) {
      await expect(root.locator(selector)).toBeDisabled();
    }
    releaseRunResponse?.();
    await expect(root.locator(".native-ai-ui-message.is-assistant strong")).toHaveText("safe");
    await expect(root.locator(".native-ai-ui-message.is-assistant a")).toHaveCount(0);
  });
});
