# Data sources and terms of use

Reviewed 2026-11-12. "Automated" means scheduled downloads by the minibook pipeline.

| Data | Source | Terms (summary) | Automated use in minibook |
|---|---|---|---|
| EUR AAA curve (Svensson), FX reference rates, €STR | ECB Data Portal API | ESCB reuse policy: free reuse, source must be quoted ([policy](https://www.ecb.europa.eu/stats/ecb_statistics/governance_and_quality_framework/html/usage_policy.en.html)) | Yes |
| US Treasury CMT par yields (DGS*) | FRED `fredgraph.csv` | Series are "Public Domain: Citation requested". FRED terms forbid data mining and scraping "that are disruptive" ([legal](https://fred.stlouisfed.org/legal/)) | Yes, one small request per series per day. Alternative: U.S. Treasury CSV (original source, see PROGRESS open issues) |
| JGB constant-maturity yields | Japan MoF CSVs | Public Data License 1.0 ([notice](https://www.mof.go.jp/about_mof/notice/index.html)) | Yes |
| Equity index closes | Yahoo Finance via yfinance | Yahoo terms restrict automated access and redistribution; index levels are licensed by the index providers | **Pending owner decision** |
| VSTOXX | STOXX `h_v2tx.txt` | View-only, no downloads, no automation, no AI use ([conditions](https://stoxx.com/legal/stoxx-conditions-of-use/)) | **No** (ADR-002) |
| SX5E dividend yield | STOXX factsheet | Same STOXX conditions | **No**: owner enters manually |
| CAC 40 dividend yield | Euronext factsheet | No robots/agents; personal non-commercial copy only ([terms](https://www.euronext.com/terms-use)) | **No**: owner enters manually |
| FTSE MIB dividend yield | FTSE Russell factsheet | LSEG terms: no bots/scripts, no AI tools ([terms](https://www.lseg.com/en/policies/website-disclaimer)) | **No**: owner enters manually |

Citations used in reports: "Source: ECB Data Portal", "Source: FRED, Federal Reserve Bank of
St. Louis; Board of Governors of the Federal Reserve System (H.15)", "Source: Ministry of
Finance Japan".
