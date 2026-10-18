import { cn } from "@/lib/utils";

export type Direction = "up" | "down" | "flat";

export function direction(value: number): Direction {
  if (value > 0) return "up";
  if (value < 0) return "down";
  return "flat";
}

const CLASS: Record<Direction, string> = {
  up: "text-up",
  down: "text-down",
  flat: "text-flat",
};

const SYMBOL: Record<Direction, string> = { up: "▲", down: "▼", flat: "" };

/**
 * A signed change colored by the semantic --color-up/--color-down tokens (red-up in
 * Taiwan by default). The arrow keeps direction readable without color.
 */
export function PriceChange({
  value,
  digits = 2,
  suffix = "",
  className,
}: {
  value: number | string;
  digits?: number;
  suffix?: string;
  className?: string;
}) {
  const num = Number(value);
  const dir = direction(num);
  const text = `${SYMBOL[dir]}${Math.abs(num).toFixed(digits)}${suffix}`;
  return (
    <span data-direction={dir} className={cn("tabular-nums", CLASS[dir], className)}>
      {text}
    </span>
  );
}
