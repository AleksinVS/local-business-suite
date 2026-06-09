import { expect, test } from "@playwright/test";

const username = process.env.E2E_USERNAME;
const password = process.env.E2E_PASSWORD;
const copilotkitEnabled = process.env.E2E_COPILOTKIT_ENABLED === "true";
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
  test.skip(!copilotkitEnabled, "CopilotKit sidebar checks run only when E2E_COPILOTKIT_ENABLED=true.");

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

    const copilotHealth = await request.get(`${copilotRuntimeUrl}/health`);
    await expect(copilotHealth).toBeOK();
    expect(await copilotHealth.json()).toMatchObject({
      status: "ok",
      basePath: "/copilotkit",
      agentId: "local_business",
    });

    const agentHealth = await request.get(`${agentRuntimeUrl}/health`);
    await expect(agentHealth).toBeOK();
    expect(await agentHealth.json()).toEqual({ status: "ok" });

    const aguiResponse = await request.post(`${agentRuntimeUrl}/ag-ui`, {
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
        forwardedProps: config.forwarded_props,
      },
    });
    expect(aguiResponse.status()).toBe(200);
    const aguiBody = await aguiResponse.text();
    expect(aguiBody).toContain('"type":"RUN_STARTED"');
    expect(aguiBody).not.toContain("invalid_actor_signature");

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
