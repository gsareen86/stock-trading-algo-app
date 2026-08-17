# local-run-ergonomics

## Intent

Make the platform behave sensibly when it is run locally against a local model — which is how
it is actually being run.

## Why

Three things went wrong the first time someone started this on their own machine rather than
in a test, and none of them were bugs in a feature. They were all the platform being tuned for
a deployment it is not in yet.

- **Every narrative call timed out.** `LLM_TIMEOUT_SECONDS` defaults to 30, which is right for
  a hosted frontier model over the network and hopeless for a 12B model on consumer hardware
  writing prose from a dozen evidence rows. The feature reported "unavailable" and looked
  broken rather than slow — the expensive kind of wrong, because it sends you debugging the
  wrong thing.
- **`GET /` answered 404.** Correct FastAPI behaviour and useless: opening the base URL is the
  first thing anyone does with a new backend, and "Not Found" reads as *the server is broken*
  rather than *use a different path*.
- **The settings that make local routing work are environment variables**, so a server started
  without them silently loses narrative routing entirely. There was no supported way to start
  the stack, only a command to remember.

## In scope

- **`LLM_LOCAL_TIMEOUT_SECONDS`** (default 300), applied per rung when that rung is local
- **`GET /`** — a static index naming the service, version and the real endpoints
- **`run-local.ps1`** — the one place the local environment lives

## Out of scope

- **Raising the hosted timeout.** 30s is right there; a hosted request still running after it
  is hung, not slow, and waiting longer costs money.
- **Making `/` probe anything.** `GET /health` answers whether the seams are up. Two answers
  to one question is one too many.
- **A cross-platform launcher.** The machine this runs on is Windows. A `.sh` twin would be
  untested, and an untested launcher is worse than none.

## Risks

- **A 300-second timeout hides a genuinely hung local server** for five minutes. Accepted: the
  alternative is failing calls that would have succeeded, and a local model has no meter
  running. It is one setting away for anyone who disagrees.
