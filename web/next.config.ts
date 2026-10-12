import type { NextConfig } from "next";

// A static export: FastAPI on the VPS serves web/out next to /api/v1, so there is no Node server (docs/handoffs/web.md).
const nextConfig: NextConfig = {
  output: "export",
  trailingSlash: true,
  images: { unoptimized: true },
  poweredByHeader: false,
  agentRules: false, // next dev would otherwise write AGENTS.md + CLAUDE.md into web/
};

export default nextConfig;
