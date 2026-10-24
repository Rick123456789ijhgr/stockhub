"use client";

import { Monitor, Moon, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import {
  applyAppearance,
  nextTheme,
  type PriceColors,
  readPriceColors,
  readTheme,
  subscribeAppearance,
  type Theme,
} from "@/lib/appearance";
import { cn } from "@/lib/utils";
import { SEGMENTED_GROUP, segmentedOption } from "@/components/segmented-links";

const THEME_LABEL: Record<Theme, string> = { system: "跟隨系統", light: "淺色", dark: "深色" };
const THEME_ICON = { system: Monitor, light: Sun, dark: Moon } as const;
const PRICE_COLORS_LABEL: Record<PriceColors, string> = {
  tw: "紅漲綠跌（台股）",
  intl: "綠漲紅跌（國際）",
};

function useTheme(): Theme {
  return useSyncExternalStore(subscribeAppearance, readTheme, () => "system");
}

function usePriceColors(): PriceColors {
  return useSyncExternalStore(subscribeAppearance, readPriceColors, () => "tw");
}

/** Compact one-button theme switch for the sidebar and the mobile header. */
export function ThemeToggle({ className }: { className?: string }) {
  const theme = useTheme();
  const Icon = THEME_ICON[theme];
  const next = nextTheme(theme);
  return (
    <Button
      variant="ghost"
      size="icon-sm"
      className={className}
      aria-label={`主題：${THEME_LABEL[theme]}（切換為${THEME_LABEL[next]}）`}
      title={`主題：${THEME_LABEL[theme]}`}
      onClick={() => applyAppearance({ theme: next })}
    >
      <Icon aria-hidden />
    </Button>
  );
}

/** The theme switch as a sidebar row: icon in the rail, label when the sidebar is open. */
export function ThemeNavButton({ className }: { className?: string }) {
  const theme = useTheme();
  const Icon = THEME_ICON[theme];
  const next = nextTheme(theme);
  return (
    <button
      type="button"
      className={className}
      aria-label={`主題：${THEME_LABEL[theme]}（切換為${THEME_LABEL[next]}）`}
      title={`主題：${THEME_LABEL[theme]}`}
      onClick={() => applyAppearance({ theme: next })}
    >
      <Icon className="size-4 shrink-0" aria-hidden />
      <span className="nav-reveal">主題：{THEME_LABEL[theme]}</span>
    </button>
  );
}

/** Full settings on /admin: theme and price-color convention. */
export function AppearanceSettings() {
  const theme = useTheme();
  const priceColors = usePriceColors();
  return (
    <div className="space-y-4 text-sm">
      <Segmented
        label="主題"
        options={(Object.keys(THEME_LABEL) as Theme[]).map((t) => ({
          key: t,
          label: THEME_LABEL[t],
        }))}
        value={theme}
        onChange={(t) => applyAppearance({ theme: t })}
      />
      <Segmented
        label="漲跌配色"
        options={(Object.keys(PRICE_COLORS_LABEL) as PriceColors[]).map((p) => ({
          key: p,
          label: PRICE_COLORS_LABEL[p],
        }))}
        value={priceColors}
        onChange={(p) => applyAppearance({ priceColors: p })}
      />
      <p className="text-xs text-muted-foreground">設定存在這個瀏覽器，每台裝置各自設定。</p>
    </div>
  );
}

function Segmented<K extends string>({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: { key: K; label: string }[];
  value: K;
  onChange: (key: K) => void;
}) {
  return (
    <div role="radiogroup" aria-label={label} className="space-y-1.5">
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn(SEGMENTED_GROUP, "flex-wrap text-xs")}>
        {options.map((o) => (
          <button
            key={o.key}
            type="button"
            role="radio"
            aria-checked={value === o.key}
            className={segmentedOption(value === o.key)}
            onClick={() => onChange(o.key)}
          >
            {o.label}
          </button>
        ))}
      </div>
    </div>
  );
}
