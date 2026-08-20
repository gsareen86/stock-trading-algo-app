# web-shell

## ADDED Requirements

### Requirement: Themes are a surface of their own
The application MUST present current themes with the evidence that raised them, and MUST NOT
present a theme as a recommendation.

#### Scenario: A theme shows what evidenced it
- GIVEN a surfaced theme
- WHEN it is opened
- THEN the number of companies and periods behind it are shown, with their sources reachable

#### Scenario: No theme carries a stance
- GIVEN any displayed theme
- WHEN it is read
- THEN it carries no stance, conviction, score or suggested action

#### Scenario: No themes yet is distinct from no themes found
- GIVEN no theme run has completed
- WHEN the surface is opened
- THEN it says so and offers to run one
- AND it is distinguishable from a completed run that surfaced nothing

#### Scenario: A run's age is shown
- GIVEN the latest theme run is several days old
- WHEN themes are displayed
- THEN the run's date is shown alongside them

### Requirement: A chain is displayed as tiers a reader can disagree with
The chain MUST be displayed tier by tier with each link's reasoning visible, and each link MUST
be rejectable from the surface.

#### Scenario: Reasoning is visible without navigating away
- GIVEN a displayed chain
- WHEN a link is inspected
- THEN the reasoning for it is readable in place

#### Scenario: A link is attributed to the model that proposed it
- GIVEN a displayed link
- WHEN it is read
- THEN it names the model that proposed it and is not presented as a platform measurement

#### Scenario: Rejecting a link removes its candidates
- GIVEN a link a reader rejects
- WHEN the surface refreshes
- THEN candidates that came only from that link are absent

#### Scenario: A tier with no Indian exposure says so
- GIVEN a tier with no listed Indian suppliers
- WHEN it is displayed
- THEN it states that plainly and offers no substitute name

### Requirement: A theme candidate reaches the same reading as any other name
Every candidate a theme surfaces MUST link to its Stock surface, and MUST display the same
four verdicts as any other instrument.

#### Scenario: A candidate is one click from its verdicts
- GIVEN a theme candidate
- WHEN it is followed
- THEN the Stock surface for that instrument opens with all four verdicts

#### Scenario: Theme membership does not change what strategies say
- GIVEN an instrument surfaced by a theme
- WHEN its verdicts are displayed
- THEN they are identical to the verdicts shown for it elsewhere

#### Scenario: Exposure grade is shown as a category
- GIVEN a graded candidate
- WHEN it is displayed
- THEN the grade appears as a named category with what supports it
- AND no numeric exposure strength is rendered

#### Scenario: Candidates are not ordered by theme
- GIVEN a list of theme candidates
- WHEN it is ordered
- THEN the ordering is not derived from theme membership or exposure grade
