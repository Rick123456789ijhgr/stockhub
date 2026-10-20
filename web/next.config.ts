import type { NextConfig } from "next";

// Env vars: package.json scripts run scripts/next.mjs, which loads the repo-root .env
// before Next starts (docs/DECISIONS.md D-010); on Vercel they come from project settings.

const nextConfig: NextConfig = {
  cacheComponents: true,
  // The floating "N" badge covers the sidebar; build errors still show in the overlay.
  devIndicators: false,
  partialPrefetching: true,
  poweredByHeader: false,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
