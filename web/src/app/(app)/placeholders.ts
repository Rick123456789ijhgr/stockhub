/** Copy for placeholder pages, kept in one place so later milestones can delete entries. */
export const PLACEHOLDERS = {
  market: {
    title: "市場",
    milestone: "M1 / M5",
    features: ["大盤與國際市場", "產業與題材熱力圖", "總經儀表板與事件行事曆"],
  },
  screener: {
    title: "篩選器",
    milestone: "M7",
    features: ["基本面、籌碼、技術條件組合", "手機版分步驟表單"],
  },
  backtest: {
    title: "回測",
    milestone: "M7",
    features: ["單一訊號與選股策略", "績效、回撤與交易明細", "策略與結果保存"],
  },
} as const;
