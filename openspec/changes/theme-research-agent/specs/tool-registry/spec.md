# tool-registry

## ADDED Requirements

### Requirement: The platform can search the public web through a declared tool
The system MUST provide a search tool with a declared contract, returning results that each
carry a title, a followable URL and an excerpt.

#### Scenario: Results are followable
- GIVEN a completed search
- WHEN a result is read
- THEN its URL and excerpt are present

#### Scenario: An unreachable provider degrades to empty
- GIVEN a search provider that cannot be reached
- WHEN a search runs
- THEN the result is empty and the failure is reported
- AND the surrounding run completes

#### Scenario: An exhausted allowance refuses rather than overspends
- GIVEN a search allowance that has been reached
- WHEN a search is requested
- THEN it is refused with that reason and no request is made

#### Scenario: No provider configured is an ordinary empty result
- GIVEN no search provider is configured
- WHEN a search is requested
- THEN the result is empty and names the missing configuration

### Requirement: Company proposals are returned through a schema, never as prose
A tool proposing companies for a theme MUST return them schema-validated, each with a name, a
rationale and its sources, and MUST report invalid output rather than passing it on.

#### Scenario: Proposals are structured
- GIVEN a completed proposal step
- WHEN it is read
- THEN each proposal carries a company name, a rationale and at least one source

#### Scenario: Unparseable output produces no proposals
- GIVEN model output that does not match the declared schema
- WHEN the tool returns
- THEN the invocation reports invalid output
- AND no proposal is produced

#### Scenario: Proposals name companies and never tickers
- GIVEN a set of proposals
- WHEN they are read
- THEN they identify companies by name, leaving symbol resolution to the platform

#### Scenario: A proposal carries no opinion
- GIVEN any proposal
- WHEN it is read
- THEN it carries no stance, conviction, target price or recommendation

### Requirement: The research conversation drives tools and produces no verdicts
The system MAY offer a conversational research surface, and it MUST reach data only through
declared tools and MUST NOT produce a stance, conviction, target or recommendation.

#### Scenario: Every claim is tool-derived
- GIVEN a research answer referring to a company or a document
- WHEN it is read
- THEN the tool result it came from is identifiable

#### Scenario: A request for a recommendation is declined
- GIVEN a request asking whether to buy an instrument
- WHEN it is answered
- THEN no stance or recommendation is produced
- AND the four strategies' verdicts are offered instead

#### Scenario: Nothing said in conversation reaches a verdict
- GIVEN any research conversation
- WHEN verdicts are produced afterwards
- THEN they are unchanged by it

#### Scenario: A conversation writes no trade
- GIVEN any research conversation
- WHEN it completes
- THEN no trade is recorded and no position changes

#### Scenario: The conversation is bounded
- GIVEN a research request
- WHEN its tool-calling loop runs
- THEN it is bounded by a declared limit rather than running until the model stops
