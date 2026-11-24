# Decision 0003 — The maker runs as a paper-mode service on the VPS, not as a live trader

Date: 2026-11-21
Status: accepted

## What was decided

The system is deployed to the VPS (`155.254.60.38`, `/opt/pmm`) and runs as
two systemd units in **paper mode**: it quotes the live markets, records the
order intents it would place, and watches the live book for the fills those
quotes would have produced. It places no real orders.

## Why

Two independent blockers make a live run impossible today, and neither is a
code problem.

**The balance is too small.** A two-sided quote of size `S` reserves about
`S` pUSD of the account's collateral, because the exchange reserves every
resting buy and the two legs of a binary are complementary. The account holds
**3.402804 pUSD**, and the venue's minimum order size is **5 shares**, so the
smallest legal pair needs about 4.6 to 4.9 pUSD. The account cannot post a
venue-legal pair today. See `0001-capital-constraint.md`.

**The order cannot be signed.** The exchange now requires a version 2 order
whose maker is a deposit wallet and whose signer is the API key's address.
The account's owner key is not on this machine and the account is a legacy
`POLY_PROXY` wallet, which the deposit-wallet flow does not accept. See
`.research/credentials.md`.

Running the paper mode anyway is not a placeholder. It is the only way to
answer the questions P5 and P6 need answered, and it is the only way to
produce the evidence the plan's own acceptance criteria call for:

- the realized pair margin, per fill, in basis points;
- the single-sided exposure rate, which is the risk that decides whether
  Lane A works at all;
- the reward score the quotes actually earn, which depends on the spread and
  the competition, both of which the paper journal measures.

## What the deployment is

| Unit | What it does |
|---|---|
| `pmm-mm.service` | The quote loop. One process, so the heartbeat cannot outlive the order placement. Paper mode, 15 second cycle. |
| `pmm-selftune.timer` | The hourly tick: recompute the metrics, apply at most one parameter change, write the parameters back atomically, write the Markdown report. |

The service reads its environment from `/etc/pmm-mm/pmm.env`. The installer
does not create credentials and does not start anything.

## What was verified on the VPS

- `python -m pytest tests -q` → **190 passed**.
- `tools/run_mm.py --dry-run --once` → 20 markets scanned, 1 selected, 2
  post-only bid intents with real token ids.
- The hourly tick → widened `half_spread_cents` from 1.0 to 2.0, because the
  maker was quoting and nothing filled.
- The next cycle quoted at the new spread, inside the venue's 4.5 cent reward
  band, and the journal recorded the pair's price sum at 0.91, so the pair
  still merges for more than it costs.

## What was wrong on the first deployment, and what it taught

The first deployed run failed with `PermissionError` on the journal: the
service account could not write a file that a manual root run had created.
Two fixes went in: the installer now creates the runtime directories owned by
the service account, and the manual runs that create files under
`/var/lib/pmm` are the thing that has to change, not the permissions.

The second failure was a logic error that only showed up in the report: the
self-tune tick's state carried a fabricated one-second time to expiry, which
tripped the expiry gate on every tick, and the agent therefore never widened
a spread that had not filled. The state now carries a full hour, and the
agent distinguishes "we quoted and did not fill" from "we never quoted" by
counting the order intents in the journal. Without that second fix the
first fix would have hidden the problem: the agent would have widened the
spread every hour on the strength of no evidence at all.
