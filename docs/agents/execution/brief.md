# Task: build the Polymarket execution adapter

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Context

We are building a Polymarket market-making system for a small maker account. Read first:

- `/home/da/桌面/polymarketMM/.research/poly-platform.md` sections 3, 4, 5, 7, 9 (order mechanics, rate limits, heartbeat, CTF, traps)
- `/home/da/桌面/polymarketMM/.research/credentials.md` (access constraints and exactly why order placement is blocked today)

Key facts you must design around:

- The account's CLOB L2 API key, secret, passphrase and account address are supplied through the
  environment at runtime (`POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`). They are not
  reproduced here. Read them from the environment, never hardcode them, and never print them.
- The live CLOB now rejects every order shape we tried. The observed server responses are in `.research/credentials.md`. The exchange wants a version 2 order whose maker is a Deposit Wallet, and the signer must equal the API key address. The account's own funds sit in a proxy wallet `0x6F7D43A87aa0B5f1Fd3a0727228f48aE5dF56b2d`, whose owner EOA private key is not on this machine.
- Consequence: the adapter must build and sign orders correctly, and it must refuse to trade rather than place an order that cannot settle. It must also be able to run fully in a dry-run mode where it computes what it would send and writes it to disk, and a paper mode that tracks fills against the live book.

## What to build

You own exactly these files and no others:

- `src/pmm/execution/__init__.py`
- `src/pmm/execution/config.py`
- `src/pmm/execution/clob.py` — order placement, cancel, batch, heartbeat
- `src/pmm/execution/journal.py` — the fill and order journal, and the PnL accounting that reads it
- `src/pmm/execution/positions.py` — on-chain and off-chain position reads
- `tests/test_journal.py`
- `tests/test_config.py`
- `tools/paper_run.py`

Use `py_clob_client_v2` version 1.2.2, which is the client that speaks the current order format. It is not installed yet. Install it into a venv at `/home/da/桌面/polymarketMM/polymarket-mm/.venv` with:

```
cd /home/da/桌面/polymarketMM/polymarket-mm
python3 -m venv .venv
.venv/bin/pip install py_clob_client_v2==1.2.2 pytest
```

`py_clob_client_v2` requires `key=` (an EOA private key) to sign. The account owner key is not available. Your code must therefore:

1. Read the owner private key from the environment variable `POLY_OWNER_PK` (or the account's own deposit-wallet config), and never from a file in the repo.
2. When `POLY_OWNER_PK` is absent, refuse to place orders and run in dry-run mode.
3. When the private key is present, derive the funder and signature type from the account, and let the exchange's own error messages drive any correction.

## Requirements

### `config.py`
- `ExecutionConfig` dataclass built from environment variables with safe defaults: `POLY_HOST` (default `https://clob.polymarket.com`), `POLY_CHAIN_ID` (137), `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE`, `POLY_OWNER_PK` (optional), `POLY_FUNDER` (optional), `POLY_SIGNATURE_TYPE` (optional int), `POLY_DRY_RUN` (`1` by default when no owner key is present), `POLY_HEARTBEAT_SECONDS` (5), `POLY_POST_ONLY` (`1`), `POLY_MAX_BATCH` (15), `POLY_ORDER_TICKER_SECONDS` (1.0), `POLY_JOURNAL_PATH`.
- `from_env()` classmethod, `redacted()` method that returns a dict safe to log, with every secret replaced by a length-only marker such as `<secret:44>`. A test must assert that no secret value appears in `redacted()` output.

### `clob.py`
- `OrderExecutor` class wrapping the v2 client.
- `build_client(config)` returns the v2 `ClobClient` or raises `ExecutionError` explaining that the owner key is missing.
- `place_or_dry(order_payload: dict, config, reason: str) -> dict` — in dry-run, writes the payload plus a timestamp to the journal and returns `{"status": "dry_run", "payload": order_payload}`. In live mode, posts it.
- `place_batch(payloads: list[dict], config) -> list[dict]` — respects `POLY_MAX_BATCH` (15, the documented CLOB batch cap) and the per-signer order token bucket. On a 429 or a `Poly-RateLimit-Remaining` of zero, stop and return, never retry blindly.
- `cancel_all(config) -> dict`
- `cancel_order(order_id, config) -> dict`
- `Heartbeat` class — one instance per API key, sends `POST /v1/heartbeats` every 5 seconds, rotating the id from the response, tolerates a 400 that returns the expected id, and exposes `stop()` that stops sending. The first accepted send arms the server-side timeout cancellation for every open order on that key, so the class docstring must say so.
- Every network call has a timeout, retries only on 5xx, and raises `ExecutionError` with the status and body on other failures.

### `journal.py`
A JSON-lines journal, one file per day, at `POLY_JOURNAL_PATH`. Every line has `ts` (UTC ISO 8601), `kind`, and a payload. Kinds: `order_intent`, `order_ack`, `order_reject`, `fill`, `cancel`, `heartbeat`, `pnl_update`, `position`.
- `Journal.append(kind, **fields)` and `Journal.read_day(date)`.
- `compute_pnl(fills: list[dict], marks: dict[str, float]) -> dict` — the realized and unrealized PnL from a fill list, with the merge accounting: when both the up token and the down token are held, the pair is worth 1 pUSD, so the position value uses `min(up_shares, down_shares) * 1.0` plus the unpaired leg at its mark.
- `win_rate(fills: list[dict]) -> float` — the fraction of closed round trips that ended positive, counting a merged pair as one round trip.

### `positions.py`
- `read_positions(config, condition_id, token_ids) -> dict` — reads the CLOB balance and allowance endpoints, and the Data API positions endpoint, and returns a dict with `balance`, `allowances`, `api_positions`. It must work with the read-only L2 key, and must not raise when a field is missing.
- `read_onchain_pUSD(address) -> float` — reads the pUSD balance of an address over a Polygon RPC (`https://1rpc.io/matic` works; `polygon-rpc.com` and `polygon.drpc.org` return 403 from this network). Standard library only for this module.

### `tools/paper_run.py`
A CLI that builds two quote objects for one up/down market, records them as `order_intent` lines, and prints the resulting journal path. It must never place a live order unless `POLY_DRY_RUN=0` and `POLY_OWNER_PK` is set.

## Verification
```
cd /home/da/桌面/polymarketMM/polymarket-mm
.venv/bin/python -m pytest tests/test_journal.py tests/test_config.py -q
.venv/bin/python tools/paper_run.py --market btc-updown-5m --dry-run
```
The paper run must produce a journal file with real order intents for a real live market, using the live token ids from the Gamma API. The journal must contain no secret values. A test must feed a synthetic fill list through `compute_pnl` and assert the merged-pair accounting.

## Constraints
- Do not create or modify any file outside the list above. `src/pmm/data/`, `src/pmm/pricing/`, `src/pmm/risk/`, `src/pmm/monitor/`, `deploy/`, `tools/scan_pools.py` belong to other workers.
- Never hardcode a secret. Never print a secret. The journal and every log line must be free of them.
- `src/pmm/execution/config.py` must not import `pmm.data` or `pmm.pricing`, so the module stands alone.

## Report
Reply with the pytest result, the paper-run journal path with its first three lines, and the exact server response the live path produces when `POLY_OWNER_PK` is missing.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
