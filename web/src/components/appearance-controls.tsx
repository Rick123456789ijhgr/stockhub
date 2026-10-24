"use client";

import { Check, Monitor, Moon, Pipette, Sun } from "lucide-react";
import { useSyncExternalStore } from "react";

import { Button } from "@/components/ui/button";
import {
  applyAppearance,
  nextTheme,
  type PriceColors,
  readBrandColor,
  readPriceColors,
  readTheme,
  subscribeAppearance,
  type Theme,
} from "@/lib/appearance";
import { BRAND_PRESETS, type BrandColor, priceColorClash } from "@/lib/brand-color";
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

function useBrandColor(): BrandColor {
  return useSyncExternalStore(subscribeAppearance, readBrandColor, () => null);
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

/** Full settings on /admin: theme, price-color convention and interface color. */
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
      <BrandColorPicker />
      <p className="text-xs text-muted-foreground">設定存在這個瀏覽器，每台裝置各自設定。</p>
    </div>
  );
}

/**
 * Interface color (D-129): presets plus the native color picker. It changes selection,
 * focus, buttons and the session ring, never data, which keeps the price colors.
 */
function BrandColorPicker() {
  const brand = useBrandColor();
  const custom = brand !== null && !BRAND_PRESETS.some((p) => p.value === brand);
  const clash = brand ? priceColorClash(brand) : null;
  const swatch = "relative grid size-7 place-items-center rounded-full ring-offset-2 ring-offset-card transition-shadow duration-150";
  return (
    <div className="space-y-1.5">
      <div className="text-xs text-muted-foreground" id="brand-color-label">
        介面主色
      </div>
      <div role="radiogroup" aria-labelledby="brand-color-label" className="flex flex-wrap items-center gap-2">
        {BRAND_PRESETS.map((p) => {
          const on = brand === p.value;
          return (
            <button
              key={p.label}
              type="button"
              role="radio"
              aria-checked={on}
              aria-label={p.label}
              title={p.label}
              className={cn(swatch, on ? "ring-2 ring-foreground/70" : "hover:ring-2 hover:ring-border")}
              style={{ backgroundColor: p.swatch }}
              onClick={() => applyAppearance({ brand: p.value })}
            >
              {on ? <Check className="size-3.5 text-white" aria-hidden /> : null}
            </button>
          );
        })}
        {/* The native picker sits over a swatch; it shows the custom color once there is one. */}
        <label
          title="自訂顏色"
          className={cn(
            swatch,
            "cursor-pointer border border-dashed border-muted-foreground/60 has-focus-visible:ring-2 has-focus-visible:ring-ring",
            custom ? "border-0 ring-2 ring-foreground/70" : "hover:ring-2 hover:ring-border",
          )}
          style={custom ? { backgroundColor: brand } : undefined}
        >
          <input
            type="color"
            aria-label="自訂顏色"
            className="absolute inset-0 size-full cursor-pointer opacity-0"
            value={brand ?? BRAND_PRESETS[0]!.swatch}
            onChange={(event) => applyAppearance({ brand: event.target.value })}
          />
          {custom ? <Check className="size-3.5 text-white" aria-hidden /> : <Pipette className="size-3.5 text-muted-foreground" aria-hidden />}
        </label>
        {brand !== null ? (
          <span className="ml-1 flex items-center gap-2 text-xs text-muted-foreground tabular-nums">
            {brand}
            <button
              type="button"
              className="underline-offset-4 hover:text-foreground hover:underline"
              onClick={() => applyAppearance({ brand: null })}
            >
              還原預設
            </button>
          </span>
        ) : null}
      </div>
      {clash ? (
        <p role="status" className="text-xs text-muted-foreground">
          這個顏色接近{clash === "red" ? "紅色" : "綠色"}，可能和漲跌顏色混淆。
        </p>
      ) : null}
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
