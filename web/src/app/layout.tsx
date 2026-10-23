import type { Metadata, Viewport } from "next";
import { Inter } from "next/font/google";

import { Providers } from "@/components/providers";
import { APPEARANCE_SCRIPT } from "@/lib/appearance";

import "./globals.css";

/** Latin text and digits (D-125); CJK uses the system face via --app-font-sans. */
const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });

export const metadata: Metadata = {
  title: { default: "StockHub", template: "%s · StockHub" },
  description: "個人台股研究平台",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    // data-price-colors: "tw" = red up / green down (default), "intl" swaps them. The head
    // script applies the stored theme and colors before first paint, so <html> differs
    // from the server render on purpose.
    <html
      lang="zh-Hant-TW"
      data-price-colors="tw"
      className={`${inter.variable} h-full antialiased`}
      suppressHydrationWarning
    >
      <head>
        <script dangerouslySetInnerHTML={{ __html: APPEARANCE_SCRIPT }} />
      </head>
      <body className="min-h-full">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
