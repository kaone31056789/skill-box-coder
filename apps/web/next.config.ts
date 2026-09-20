import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Railway/Docker: emit a self-contained server bundle.
  output: "standalone",
  /* config options here */
};

export default nextConfig;
