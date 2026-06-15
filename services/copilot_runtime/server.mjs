import { createServer } from "node:http";

import { HttpAgent } from "@ag-ui/client";
import { CopilotRuntime, createCopilotRuntimeHandler } from "@copilotkit/runtime/v2";
import { createCopilotNodeHandler } from "@copilotkit/runtime/v2/node";

const port = Number.parseInt(process.env.COPILOTKIT_RUNTIME_PORT || "3100", 10);
const host = process.env.COPILOTKIT_RUNTIME_HOST || "0.0.0.0";
const basePath = process.env.COPILOTKIT_BASE_PATH || "/copilotkit";
const agentId = process.env.LOCAL_BUSINESS_COPILOTKIT_AGENT_ID || "local_business";
const agentUrl =
  process.env.LOCAL_BUSINESS_AGENT_RUNTIME_AG_UI_URL || "http://127.0.0.1:8090/ag-ui";
const serviceToken = process.env.LOCAL_BUSINESS_COPILOTKIT_SERVICE_TOKEN || "";
const corsEnabled = (process.env.COPILOTKIT_CORS || "true").toLowerCase() !== "false";

process.env.COPILOTKIT_TELEMETRY_DISABLED = process.env.COPILOTKIT_TELEMETRY_DISABLED || "true";

const agentHeaders = serviceToken ? { "X-CopilotKit-Service-Token": serviceToken } : {};
const runtime = new CopilotRuntime({
  agents: {
    [agentId]: new HttpAgent({
      url: agentUrl,
      headers: agentHeaders,
    }),
  },
});

const copilotSingleRouteHandler = createCopilotRuntimeHandler({
  runtime,
  basePath,
  mode: "single-route",
  cors: corsEnabled,
});
const copilotMultiRouteHandler = createCopilotRuntimeHandler({
  runtime,
  basePath,
  cors: corsEnabled,
});
const copilotSingleRouteNodeHandler = createCopilotNodeHandler(copilotSingleRouteHandler);
const copilotMultiRouteNodeHandler = createCopilotNodeHandler(copilotMultiRouteHandler);

const server = createServer(async (req, res) => {
  const url = new URL(req.url || "/", `http://${req.headers.host || "localhost"}`);

  if (url.pathname === "/health") {
    res.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    res.end(
      JSON.stringify({
        status: "ok",
        basePath,
        agentId,
        agentUrl,
      }),
    );
    return;
  }

  if (url.pathname === basePath || url.pathname === `${basePath}/`) {
    copilotSingleRouteNodeHandler(req, res);
    return;
  }

  if (url.pathname.startsWith(`${basePath}/`)) {
    copilotMultiRouteNodeHandler(req, res);
    return;
  }

  res.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
  res.end(JSON.stringify({ error: "not_found" }));
});

server.listen(port, host, () => {
  console.log(`CopilotKit Runtime listening on http://${host}:${port}${basePath}`);
});
