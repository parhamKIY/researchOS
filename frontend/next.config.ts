import type { NextConfig } from "next";

const backend = process.env.API_INTERNAL_URL ?? "http://api:8000";
const config: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
export default config;
