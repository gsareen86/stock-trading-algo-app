# sector-coverage

## Intent

Give every listed company a sector index that describes its business, following NSE's own
industry classification, so sector-relative measurements stop failing for a tenth of the market.

## Why

82 of the 750 Total Market names — every Chemicals, Services and Telecommunication company, plus
JK Paper and Godrej Industries — resolved to no sector index. Brahma-Vishnu-Mahesh therefore
failed its sector-rank criterion on all of them, always, and the discovery funnel could not place
them in a sector. Separately, yfinance's "Utilities" sector resolved to IT, because the term "it"
matched inside "utilities".

## In scope

- **NIFTY COMMODITIES** (`^CNXCMDT`) added as the index for NSE's Commodities macro-sector:
  Chemicals (including fertilisers and agrochemicals) and Forest Materials. NIFTY CHEMICALS
  itself has no usable provider history (recorded in the mapping file's verification note).
- **Telecommunication → NIFTY INFRASTRUCTURE**, whose eligible sectors include telecom and of
  which Bharti Airtel is a top constituent.
- **Services → NIFTY INFRASTRUCTURE** by default: NSE's Services names are mostly ports,
  shipping, airports, aviation and logistics.
- **Symbol overrides**, each with a stated reason, for names whose business has a closer index
  than their industry's default (BPO and IT distribution → IT; bank cash management → financial
  services; flexible office space → realty; jewellery certification → consumption; metals
  trading and e-auctions → metal).
- **Utilities → Energy.**
- **`python -m app.data.verify_sector_indices`**, the history check the mapping file's rule
  requires, runnable on any machine that can reach the provider.

## Out of scope

- **A conglomerate's sector.** Godrej Industries spans consumer, property, agri and chemicals;
  no one index describes it, so it stays unmapped rather than guessed.
- **Composite sector indices built from constituents.** A better answer for Chemicals than
  NIFTY COMMODITIES, and a strategy change.
