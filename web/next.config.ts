import type { NextConfig } from "next";

const config: NextConfig = {
  output: "export",
  reactStrictMode: true,
  turbopack: { root: process.cwd() },
};

export default config;
