import type { NextConfig } from "next";

// Env vars: package.json scripts run scripts/next.mjs, which loads the repo-root .env
// before Next starts (docs/DECISIONS.md D-010); on Vercel they come from project settings.

const nextConfig: NextConfig = {
  cacheComponents: true,
  // The floating "N" badge covers the sidebar; build errors still show in the overlay.
  devIndicators: false,
  partialPrefetching: true,
  experimental: {
    // Revisiting a page within 30 s shows the copy already in the browser (no request);
    // mutations call router.refresh(), which drops it, and quotes poll on their own (D-118).
    staleTimes: { dynamic: 30 },
  },
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
