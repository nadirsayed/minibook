# minibook

A mini multi-asset derivatives book (EUR IRS, FX forwards, index options), valued every
TARGET business day from real public market data, with Greeks, P&L explain, 99% historical
VaR / 97.5% ES, and a PDF risk report.

> **Status: under construction (M0 scaffold).** See [PROGRESS.md](PROGRESS.md).
> Full README (methodology, sign conventions, limitations) lands in M9.

```bash
uv sync
uv run minibook --help
uv run pytest
```

License: MIT.
