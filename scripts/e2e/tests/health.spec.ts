import { expect, test } from "@playwright/test";

test("Django health endpoint is reachable", async ({ request }) => {
  const response = await request.get("/health/");

  await expect(response).toBeOK();
  expect(await response.json()).toEqual({ status: "ok" });
});
