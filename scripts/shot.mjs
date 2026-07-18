// Minimal CDP screenshotter (Node 22 global WebSocket/fetch). Works around
// pages that never go network-idle (our SSE stream) by waiting a fixed delay.
// Usage: node scripts/shot.mjs <url> <outPath> <waitMs> <width> <height>
const [, , url, out, waitMs = "6000", w = "1600", h = "1000"] = process.argv;
const base = "http://127.0.0.1:9222";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const target = await (await fetch(`${base}/json/new?${encodeURIComponent(url)}`, { method: "PUT" })).json();
const ws = new WebSocket(target.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const send = (method, params = {}) =>
  new Promise((res) => {
    const mid = ++id;
    pending.set(mid, res);
    ws.send(JSON.stringify({ id: mid, method, params }));
  });
ws.addEventListener("message", (e) => {
  const msg = JSON.parse(e.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg.result);
    pending.delete(msg.id);
  }
});
await new Promise((r) => ws.addEventListener("open", r));
await send("Page.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: Number(w),
  height: Number(h),
  deviceScaleFactor: 1,
  mobile: false,
});
await sleep(Number(waitMs));
const { data } = await send("Page.captureScreenshot", { format: "png", fromSurface: true });
const fs = await import("node:fs");
fs.writeFileSync(out, Buffer.from(data, "base64"));
console.log("wrote", out);
await send("Target.closeTarget", { targetId: target.id }).catch(() => {});
ws.close();
process.exit(0);
