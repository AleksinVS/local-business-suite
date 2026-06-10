import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const aiUiDriver = process.env.E2E_AI_UI_DRIVER || (process.env.E2E_COPILOTKIT_ENABLED === "true" ? "copilotkit" : "legacy");
const copilotkitEnabled = aiUiDriver === "copilotkit";
const agentRuntimeUrl = process.env.E2E_AGENT_RUNTIME_URL || "http://127.0.0.1:8090";
const copilotRuntimeUrl = process.env.E2E_COPILOT_RUNTIME_URL || "http://127.0.0.1:3100";

async function login(page) {
  await page.goto("/accounts/login/");
  await page.locator('input[name="username"]').fill(username || "");
  await page.locator('input[name="password"]').fill(password || "");
  await page.locator('button[type="submit"]').click();
  await expect(page.getByRole("button", { name: "Все функции" })).toBeVisible();
}

test.describe("CopilotKit AG-UI sidebar", () => {
  test.skip(!username || !password, "Set E2E_USERNAME and E2E_PASSWORD to run authenticated UI checks.");
  test.skip(!copilotkitEnabled, "CopilotKit sidebar checks run only when E2E_AI_UI_DRIVER=copilotkit.");

  test("loads embedded chat, signed actor config and AG-UI runtime bridge", async ({ page, request }) => {
    await login(page);

    const configResponsePromise = page.waitForResponse((response) => (
      response.url().includes("/ai/chat/copilotkit/config/")
      && response.request().method() === "GET"
    ));
    await page.goto("/workorders/");
    const configResponse = await configResponsePromise;
    expect(configResponse.status()).toBe(200);

    const config = await page.evaluate(async () => {
      const response = await fetch("/ai/chat/copilotkit/config/", {
        credentials: "same-origin",
        headers: { "X-Requested-With": "XMLHttpRequest" },
      });
      if (!response.ok) throw new Error(`CopilotKit config failed: ${response.status}`);
      return response.json();
    });

    expect(config.enabled).toBe(true);
    expect(config.agent_id).toBe("local_business");
    expect(config.thread_id).toBeTruthy();
    expect(config.forwarded_props?.actor?.username).toBe(username);
    expect(config.forwarded_props?.signature).toMatch(/^[a-f0-9]{64}$/);

    const sidebarRoot = page.locator("#copilotkit-sidebar-root");
    await expect(sidebarRoot).toBeVisible();
    await expect(page.locator("#sidebar-ai-chat")).toHaveCount(0);
    await expect(page.locator(".copilotkit-error")).toHaveCount(0);
    await expect(sidebarRoot.getByRole("textbox")).toBeVisible();

    const rootDataset = await sidebarRoot.evaluate((node) => ({
      runtimeUrl: (node as HTMLElement).dataset.runtimeUrl,
      agentId: (node as HTMLElement).dataset.agentId,
    }));
    expect(rootDataset.runtimeUrl).toBe(config.runtime_url);
    expect(rootDataset.agentId).toBe(config.agent_id);

    const newSessionResponsePromise = page.waitForResponse((response) => (
      response.url().includes("/ai/ui/session/new/")
      && response.request().method() === "POST"
    ));
    await sidebarRoot.getByTitle("Новый чат").click();
    const newSessionResponse = await newSessionResponsePromise;
    expect(newSessionResponse.status()).toBe(200);
    const newSession = await newSessionResponse.json();
    expect(newSession.enabled).toBe(true);
    expect(newSession.driver).toBe("copilotkit");
    expect(newSession.thread_id).toBeTruthy();
    expect(newSession.thread_id).not.toBe(config.thread_id);
    expect(newSession.forwarded_props?.session_id).toBe(newSession.thread_id);
    expect(newSession.forwarded_props?.signature).toMatch(/^[a-f0-9]{64}$/);

    const copilotHealth = await request.get(`${copilotRuntimeUrl}/health`);
    await expect(copilotHealth).toBeOK();
    expect(await copilotHealth.json()).toMatchObject({
      status: "ok",
      basePath: "/copilotkit",
      agentId: "local_business",
    });

    const runtimeInfo = await request.post(`${copilotRuntimeUrl}/copilotkit`, {
      data: { method: "info" },
    });
    await expect(runtimeInfo).toBeOK();
    expect(await runtimeInfo.json()).toMatchObject({
      agents: {
        local_business: {
          name: "local_business",
        },
      },
    });

    const threadsResponse = await request.get(`${copilotRuntimeUrl}/copilotkit/threads?agentId=local_business`);
    await expect(threadsResponse).toBeOK();
    const threadsPayload = await threadsResponse.json();
    expect(Array.isArray(threadsPayload.threads)).toBe(true);

    const agentHealth = await request.get(`${agentRuntimeUrl}/health`);
    await expect(agentHealth).toBeOK();
    expect(await agentHealth.json()).toEqual({ status: "ok" });

    const rejectedAguiResponse = await request.post(`${agentRuntimeUrl}/ag-ui`, {
      data: {
        threadId: config.thread_id,
        runId: `e2e_${Date.now()}`,
        state: {},
        messages: [
          {
            id: "e2e_user_message",
            role: "user",
            content: "Проверка AG-UI bridge без внешнего LLM.",
          },
        ],
        tools: [],
        context: [],
        forwardedProps: {
          ...config.forwarded_props,
          signature: "invalid",
        },
      },
    });
    expect(rejectedAguiResponse.status()).toBe(200);
    const aguiBody = await rejectedAguiResponse.text();
    expect(aguiBody).toContain('"type":"RUN_ERROR"');
    expect(aguiBody).toContain("invalid_actor_signature");

    const firstCard = page.locator(".work-card:not(.work-card-empty)").first();
    await expect(firstCard).toBeVisible();
    const detailContextUpdate = page.waitForResponse((response) => (
      response.url().includes("/ai/context/window/")
      && response.request().method() === "POST"
      && response.status() === 200
    ));
    await firstCard.click();
    await expect(page.locator("#detail-panel.active")).toBeVisible();
    await expect(page.locator("#detail-panel-content [data-ai-context]")).toBeVisible();
    await detailContextUpdate;

    const detailContext = await page.evaluate(() => window.LocalBusinessPageContext?.getCurrent());
    expect(detailContext?.envelope?.selection?.object_type).toBe("workorder");
    expect(detailContext?.envelope?.selection?.object_id).toBeTruthy();
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
