"use client";

import { useMutation } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  DISCOUNT_MODE_LABEL,
  parseFeeSettings,
  ROUNDING_LABEL,
} from "@/lib/fee-settings";
import { formatInteger } from "@/lib/format";
import {
  brokerFee,
  type DiscountMode,
  type FeeSettings,
  type Rounding,
  taxRate,
  transactionTax,
} from "@/lib/portfolio";

const EXAMPLES = [
  { label: "1 張 × 100 元", amount: 100_000, quantity: 1000 },
  { label: "1 張 × 600 元", amount: 600_000, quantity: 1000 },
  { label: "零股 50 股 × 100 元", amount: 5_000, quantity: 50 },
];

const field =
  "h-8 rounded-md border bg-background px-2 text-sm text-foreground tabular-nums aria-invalid:border-destructive";

/** Edit the one-off fee profile (rate, discount, minimums, rebate mode, rounding). */
export function FeeSettingsForm({ initial }: { initial: FeeSettings }) {
  const router = useRouter();
  // Shown the way brokers quote them: rate in %, discount in 折 (10 = none).
  const [rate, setRate] = useState(String(Number((initial.rate * 100).toFixed(6))));
  const [discount, setDiscount] = useState(String(Number((initial.discount * 10).toFixed(4))));
  const [minFee, setMinFee] = useState(String(initial.minFee));
  const [minFeeOddLot, setMinFeeOddLot] = useState(String(initial.minFeeOddLot));
  const [discountMode, setDiscountMode] = useState<DiscountMode>(initial.discountMode);
  const [rounding, setRounding] = useState<Rounding>(initial.rounding);

  const settings = parseFeeSettings({
    rate: rate.trim() === "" ? null : Number(rate) / 100,
    discount: discount.trim() === "" ? 1 : Number(discount) / 10,
    minFee,
    minFeeOddLot,
    discountMode,
    rounding,
  });
  const save = useMutation({
    mutationFn: async (body: FeeSettings) => {
      const response = await fetch("/api/settings/fees", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
    },
    onSuccess: () => router.refresh(),
  });

  return (
    <form
      className="space-y-4 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        if (settings) save.mutate(settings);
      }}
    >
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <label className="grid gap-1 text-xs text-muted-foreground">
          費率（%）
          <input
            inputMode="decimal"
            value={rate}
            onChange={(e) => setRate(e.target.value)}
            aria-invalid={settings === null}
            className={field}
          />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          折扣（折，10 = 無）
          <input
            inputMode="decimal"
            value={discount}
            onChange={(e) => setDiscount(e.target.value)}
            className={field}
          />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          最低收費（元）
          <input
            inputMode="numeric"
            value={minFee}
            onChange={(e) => setMinFee(e.target.value)}
            className={field}
          />
        </label>
        <label className="grid gap-1 text-xs text-muted-foreground">
          零股最低收費（元）
          <input
            inputMode="numeric"
            value={minFeeOddLot}
            onChange={(e) => setMinFeeOddLot(e.target.value)}
            className={field}
          />
        </label>
      </div>
      <div className="flex flex-wrap gap-x-6 gap-y-3">
        <fieldset className="space-y-1">
          <legend className="text-xs text-muted-foreground">折扣方式</legend>
          <div className="flex flex-wrap gap-3">
            {(Object.keys(DISCOUNT_MODE_LABEL) as DiscountMode[]).map((mode) => (
              <label key={mode} className="flex items-center gap-1.5">
                <input
                  type="radio"
                  name="discountMode"
                  checked={discountMode === mode}
                  onChange={() => setDiscountMode(mode)}
                />
                {DISCOUNT_MODE_LABEL[mode]}
              </label>
            ))}
          </div>
        </fieldset>
        <label className="grid gap-1 text-xs text-muted-foreground">
          尾數處理
          <select
            value={rounding}
            onChange={(e) => setRounding(e.target.value as Rounding)}
            className="h-8 rounded-md border bg-background px-2 text-sm text-foreground"
          >
            {(Object.keys(ROUNDING_LABEL) as Rounding[]).map((r) => (
              <option key={r} value={r}>
                {ROUNDING_LABEL[r]}
              </option>
            ))}
          </select>
        </label>
      </div>

      {settings ? (
        <div className="rounded-md bg-muted/50 p-3 text-xs">
          <p className="mb-2 text-muted-foreground">試算（股票；ETF 證交稅 0.1%）</p>
          <ul className="grid gap-1 tabular-nums">
            {EXAMPLES.map((ex) => {
              const fee = brokerFee(ex.amount, ex.quantity, settings);
              const tax = transactionTax(ex.amount, taxRate("stock", "", "2026-01-01", false));
              return (
                <li key={ex.label}>
                  {ex.label}：手續費 {formatInteger(fee.fee)} 元
                  {fee.rebate > 0 ? `（事後退 ${formatInteger(fee.rebate)} 元）` : ""}
                  ；賣出另收證交稅 {formatInteger(tax)} 元
                </li>
              );
            })}
          </ul>
        </div>
      ) : (
        <p className="text-xs text-destructive">
          費率需大於 0、不超過 1%；折扣需在 0～10 折之間；最低收費為 0～1000 的整數。
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={!settings || save.isPending}>
          儲存
        </Button>
        {save.isSuccess ? <span className="text-xs text-muted-foreground">已儲存</span> : null}
        {save.isError ? <span className="text-xs text-destructive">儲存失敗</span> : null}
      </div>
      <p className="text-xs text-muted-foreground">
        只影響之後新增或修改（未手動改過費用）的交易；已存的交易不會被改寫。證交稅為固定稅率：股票
        0.3%（當沖 0.15%，至 2027 年底）、ETF 0.1%、債券 ETF 免徵（至 2026 年底）。
      </p>
    </form>
  );
}
