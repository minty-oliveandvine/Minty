import type { NextConfig } from "next";
import path from "node:path";

const nextConfig: NextConfig = {
  turbopack: {
    // Pin the workspace root to this folder so Next.js doesn't infer the
    // parent repo as the root (multiple lockfiles exist in the monorepo).
    root: path.join(__dirname),
  },
};

export default nextConfig;
