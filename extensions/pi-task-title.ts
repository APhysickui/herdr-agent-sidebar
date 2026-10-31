/** Publish the current request as a sidebar label without an extra model call. */
import { createConnection } from "node:net";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.on("input", async (event, ctx) => {
    const path = process.env.HERDR_SOCKET_PATH;
    const pane = process.env.HERDR_PANE_ID;
    if (process.env.HERDR_ENV !== "1" || !path || !pane) return;
    const text = event.text.replace(/\s+/g, " ").trim();
    if (!text || text.startsWith("/") || /^(hi|hello|hey|你好|您好|在吗|谢谢|好的|可以|继续|ok+|resume|continue)$/i.test(text)) return;
    const task = Array.from(text).slice(0, 480).join("");
    const session = ctx.sessionManager.getSessionId();
    const file = ctx.sessionManager.getSessionFile();
    await new Promise<void>((resolve) => {
      const socket = createConnection(path);
      const done = () => { socket.destroy(); resolve(); };
      socket.setTimeout(500, done);
      socket.on("error", done);
      socket.on("data", done);
      socket.on("connect", () => socket.write(JSON.stringify({
        id: `local.pi-task:${Date.now()}`,
        method: "pane.report_metadata",
        params: { pane_id: pane, source: "local.pi-input", seq: Date.now() * 1_000_000,
          tokens: { live_task: task, task_agent: "pi", task_session: session,
                    ...(file ? { task_file: file } : {}) } },
      }) + "\n"));
    });
  });
}
