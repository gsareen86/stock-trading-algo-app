# tool-registry

## ADDED Requirements

### Requirement: Management commentary is retrievable as research
The system MUST provide a tool that returns the text of a company's most recent earnings-call
transcript or management commentary document, with the document's own date and its source URL.

#### Scenario: The latest document is returned with its provenance
- GIVEN a company with a published transcript
- WHEN commentary is requested
- THEN the extracted text is returned with the document date and the URL it came from

#### Scenario: No document available
- GIVEN a company with no published transcript
- WHEN commentary is requested
- THEN the result is empty and says so
- AND no exception escapes the tool

#### Scenario: An unreadable document is reported, not guessed at
- GIVEN a document whose text cannot be extracted
- WHEN commentary is requested
- THEN the failure is reported with the document URL
- AND no partial or reconstructed text is returned

#### Scenario: Commentary is never a measurement
- GIVEN commentary returned for an instrument
- WHEN a verdict is produced for that instrument
- THEN no evidence row cites the commentary as a measured value

#### Scenario: Anything quoting commentary names it as reported
- GIVEN an insight or narrative drawing on commentary
- WHEN it is read
- THEN it names the document as the reporter and is not presented as a platform measurement

### Requirement: Long documents are returned in addressable sections
The commentary tool MUST return a document as ordered, individually addressable sections rather
than as a single block of text.

#### Scenario: Sections are individually retrievable
- GIVEN a retrieved document
- WHEN a specific section is requested
- THEN that section is returned without the rest of the document

#### Scenario: A section fits a local model's context
- GIVEN a document longer than a local model's context window
- WHEN its sections are read
- THEN each section is within the configured section size

#### Scenario: Ordering is preserved
- GIVEN a document returned as sections
- WHEN they are read in order
- THEN they reconstruct the document's own order

### Requirement: A document is fetched once and cached
The commentary tool MUST cache each retrieved document by its source URL and MUST NOT re-fetch
a document it already holds.

#### Scenario: A repeat request serves the cached document
- GIVEN a document already retrieved
- WHEN the same document is requested again
- THEN the cached copy is used and no download occurs

#### Scenario: A newer document is fetched
- GIVEN a cached document and a newer one published since
- WHEN the latest commentary is requested
- THEN the newer document is fetched

### Requirement: Commentary has one seam and more than one provider
The commentary capability MUST be defined by a provider seam, MUST prefer a licensed API
provider where one serves the company, MUST fall back to the document pipeline where it does
not, and MUST record which provider served each document.

#### Scenario: The API provider is preferred
- GIVEN a company the API provider covers
- WHEN commentary is requested
- THEN the API provider serves it and no document is scraped

#### Scenario: An uncovered company falls back
- GIVEN a company the API provider does not cover
- WHEN commentary is requested
- THEN the document pipeline serves it

#### Scenario: The serving provider is recorded
- GIVEN any returned document
- WHEN it is read
- THEN the provider that served it is identifiable

#### Scenario: Every provider degrades to empty
- GIVEN both providers unavailable
- WHEN commentary is requested
- THEN the result is empty and says so
- AND the surrounding cycle completes

### Requirement: A third-party target or forecast is never a platform level
A price target, forecast or recommendation obtained from an external provider MUST NOT be used
as an entry, stop or target in any plan, and MUST be presented as an attributed third-party
opinion wherever it is shown.

#### Scenario: A vendor target is not a plan level
- GIVEN a vendor-supplied price target for an instrument
- WHEN a plan is produced for that instrument
- THEN no plan level derives from the vendor target

#### Scenario: A vendor target is attributed where displayed
- GIVEN a vendor-supplied target being displayed
- WHEN it is read
- THEN it names the provider and is not presented as a platform measurement

#### Scenario: A vendor target is never evidence
- GIVEN a vendor-supplied target
- WHEN a verdict is produced
- THEN no evidence row cites it

### Requirement: An aggregator is used politely and resolved past where possible
A tool reading a third-party aggregator MUST bound its request rate, identify itself in its
user agent, and MUST prefer the exchange-hosted document URL when the aggregator's link
resolves to one.

#### Scenario: Requests are rate-bounded
- GIVEN a batch of companies to retrieve commentary for
- WHEN the tool runs
- THEN its requests to the aggregator are spaced to the configured rate

#### Scenario: An exchange-hosted document is fetched from the exchange
- GIVEN an aggregator link that resolves to an exchange-hosted PDF
- WHEN the document is downloaded
- THEN it is fetched from the exchange rather than through the aggregator

#### Scenario: A blocked aggregator degrades to empty
- GIVEN an aggregator that refuses the request
- WHEN commentary is requested
- THEN the result is empty and the refusal is reported
- AND the surrounding cycle completes
