import type { NextConfig } from "next";

// In development the browser talks only to Next.js (port 3000); /api/* is forwarded to FastAPI (port 8000).
// In production Caddy routes /api/* straight to the API container, so this rewrite is only a dev convenience.
const API_URL = process.env.API_URL ?? "http://localhost:8000";

const config: NextConfig = {
  output: "standalone",          // a self-contained server bundle for a small Docker image
  compress: false,               // gzip would buffer the Server-Sent Events stream
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/:path*` }];
  },
};

export default config;
