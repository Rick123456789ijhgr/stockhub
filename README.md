# StockHub

個人自用的台股研究平台（基本面、籌碼、總經、新聞與社群情緒、持股追蹤、選股篩選與回測）。

- 規劃摘要：[docs/PLAN.md](docs/PLAN.md)
- 目前里程碑：[docs/M0.md](docs/M0.md)
- 決策紀錄：[docs/DECISIONS.md](docs/DECISIONS.md)

## 需求

- GNU make、[uv](https://docs.astral.sh/uv/)（會自動安裝 Python 3.12）、Node.js ≥ 20.9、pnpm

## 快速開始

```bash
make py-install web-install
make py-test
make web-check
```

（完整的本機環境、遷移、登入與部署說明會在 M0 的 T9 補齊。）
