/**
 * Custom HTTPS dev server for Next.js.
 * Serves the frontend over HTTPS and proxies /api/* and /ws/* to the backend
 * with self-signed certificate support.
 */
import { createServer } from "node:https";
import { request as httpsRequest } from "node:https";
import { readFileSync } from "node:fs";
import { parse } from "node:url";
import { connect as tlsConnect } from "node:tls";
import next from "next";

const dev = process.env.NODE_ENV !== "production";
const hostname = "localhost";
const port = parseInt(process.env.PORT || "3000", 10);
const backendPort = parseInt(process.env.BACKEND_PORT || "8000", 10);

const sslOptions = {
  key: readFileSync("../certs/localhost-key.pem"),
  cert: readFileSync("../certs/localhost.pem"),
};

const app = next({ dev, hostname, port });
const handle = app.getRequestHandler();

function proxyRequest(req, res) {
  const options = {
    hostname,
    port: backendPort,
    path: req.url,
    method: req.method,
    headers: { ...req.headers, host: `${hostname}:${backendPort}` },
    rejectUnauthorized: false,
  };

  const proxyReq = httpsRequest(options, (proxyRes) => {
    res.writeHead(proxyRes.statusCode, proxyRes.headers);
    proxyRes.pipe(res);
  });

  proxyReq.on("error", (err) => {
    console.error("Proxy error:", err.message);
    if (!res.headersSent) {
      res.writeHead(502, { "Content-Type": "text/plain" });
      res.end("Bad Gateway");
    }
  });

  req.pipe(proxyReq);
}

function proxyWebSocket(req, socket, head) {
  const backendSocket = tlsConnect(
    { host: hostname, port: backendPort, rejectUnauthorized: false },
    () => {
      // Reconstruct the HTTP upgrade request to the backend
      const reqLine = `${req.method} ${req.url} HTTP/1.1\r\n`;
      const headers = Object.entries({ ...req.headers, host: `${hostname}:${backendPort}` })
        .map(([k, v]) => `${k}: ${v}`)
        .join("\r\n");
      backendSocket.write(reqLine + headers + "\r\n\r\n");
      if (head.length > 0) backendSocket.write(head);
      backendSocket.pipe(socket);
      socket.pipe(backendSocket);
    }
  );

  backendSocket.on("error", (err) => {
    console.error("WebSocket proxy error:", err.message);
    socket.destroy();
  });

  socket.on("error", () => backendSocket.destroy());
}

function shouldProxy(pathname) {
  return pathname.startsWith("/api/") || pathname.startsWith("/ws/");
}

app.prepare().then(() => {
  const server = createServer(sslOptions, (req, res) => {
    const parsedUrl = parse(req.url, true);
    if (shouldProxy(parsedUrl.pathname)) {
      proxyRequest(req, res);
    } else {
      handle(req, res, parsedUrl);
    }
  });

  // Handle WebSocket upgrades (tick streaming, etc.)
  server.on("upgrade", (req, socket, head) => {
    const { pathname } = parse(req.url, true);
    if (shouldProxy(pathname)) {
      proxyWebSocket(req, socket, head);
    }
    // Non-proxied upgrades (HMR) are handled by Next.js internally
  });

  server.listen(port, () => {
    console.log(`  ▲ Ready on https://${hostname}:${port}`);
    console.log(`  ↳ Proxying /api/* and /ws/* → https://${hostname}:${backendPort}`);
  });
});
