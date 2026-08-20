# Recorded provider responses

Captured from the live providers, not written by hand. They exist so the data-source tests run
offline and deterministically, and so a provider changing shape is caught by a failing test
rather than by a silently empty result in production.

| Directory | Source | Captured |
|---|---|---|
| `nse/` | NSE `/api/allIndices` | index levels, trailing returns, advance/decline breadth |
| `indianapi/` | Indian API `/stock` and `/historical_stats` | company metrics, statements, shareholding |
| `screener/` | A company page's document sections | concall and annual-report links |

**Trimmed, and here is exactly how.** `indianapi/stock.json` arrived at 732 KB, three quarters
of it two duplicate copies of a financial-statement history nothing reads. Everything the
parser and the tests touch — `keyMetrics`, `shareholding`, `companyProfile.peerCompanyList`,
company identity — is recorded **whole and unedited**. Lists that nothing reads keep their
first element, so their shape is still on record if a caller ever needs them. No value was
altered.

**Do not regenerate casually.** The Indian API free tier allows 500 requests a *month*, and
capturing this set costs six. If a shape needs re-recording, capture once and reuse.
