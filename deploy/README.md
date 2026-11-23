# Deploying the Polymarket maker on a small box

This is the deployment for a 1 vCPU / 960 MB Debian 12 host. The maker runs
as two units:

- `pmm-mm.service` — the quote loop.
- `pmm-selftune.service` + `pmm-selftune.timer` — the hourly self-tune tick.

The heartbeat lives inside the quote loop's process on purpose. The venue
cancels every resting order owned by an API key when that key's heartbeat
lapses, and there is no disarm endpoint. A separate heartbeat process that
dies leaves the book naked. One process, one heartbeat.

## What the service does

Each cycle it scores the reward markets, picks the ones the account's
capital can actually fund, builds a two-sided quote on each (a resting bid on
the UP token and a resting bid on the DOWN token), runs the gate stack, and
places what survives. Both legs are bids because the profit is the pair: a
complete set redeems for 1 pUSD, so a pair bought below 1 is profitable no
matter which way the market resolves.

The self-tune tick reads the journal once an hour, recomputes the metrics,
asks the monitor agent for at most one parameter change, and writes the
parameters back. The loop reads that file at the top of every cycle.

## Requirements

- Python 3.10 or newer (Debian 12 ships 3.11).
- `git`, `python3-venv`, `python3-pip`.
- Outbound HTTPS to `clob.polymarket.com`, `gamma-api.polymarket.com`, and
  `data-api.polymarket.com`.
- About 300 MB of disk for the venv, the journal, and the reports.

The box does not need a GPU, a websocket feed, or an exchange API key. The
public market data endpoints are enough to score candidates and quote them.

## Install

```sh
cd /opt
git clone <this repository> pmm-src
cd pmm-src/polymarket-mm
bash deploy/install.sh
```

`install.sh` creates the venv, installs the package, creates the runtime
directories, and installs the unit files. It writes no credentials and it
does not start anything. It prints the next command to run.

## Configure

The units read their environment from `/etc/pmm-mm/pmm.env`, which is not
created by the installer. Copy the example and fill it in:

```sh
install -m 640 -o root -g root /opt/pmm-src/polymarket-mm/deploy/pmm.env.example /etc/pmm-mm/pmm.env
$EDITOR /etc/pmm-mm/pmm.env
```

The variables that matter:

| Variable | Meaning |
|---|---|
| `POLY_API_KEY`, `POLY_API_SECRET`, `POLY_API_PASSPHRASE` | The CLOB L2 credentials. Without them the service still runs, but only in dry-run mode. |
| `POLY_OWNER_PK` | The EOA private key that signs orders. Without it the service refuses to place orders and stays in dry-run. The CLOB L2 key cannot sign an order. |
| `POLY_FUNDER`, `POLY_SIGNATURE_TYPE` | The account's maker address and signature type. The adapter derives them when they are not set. |
| `POLY_DRY_RUN` | `1` keeps the service from placing orders. Defaults to on when there is no owner key. |
| `POLY_JOURNAL_PATH` | Where the fills are journaled. |
| `POLY_PARAMS_PATH` | The parameter file the self-tune tick writes. |
| `POLY_REPORTS_DIR` | Where the hourly reports are written. |
| `POLY_HEARTBEAT_SECONDS` | Heartbeat interval. The venue expects 5. |
| `POLY_MAX_BATCH` | Orders per batch. The venue caps this at 15. |

## Run

```sh
systemctl daemon-reload
systemctl start pmm-mm.service
systemctl start pmm-selftune.timer
systemctl status pmm-mm.service
journalctl -u pmm-mm -f
```

## Stop

```sh
systemctl stop pmm-mm.service
```

Stopping the unit runs the shutdown path, which cancels the resting orders
first and stops the heartbeat second. The venue's server-side deadline stays
armed after the heartbeat stops, so the cancellations have to be in first.
Check the journal's last lines for the `cancel_all` record before restarting.

## Files

| Path | What |
|---|---|
| `/var/lib/pmm/journal/` | One JSON-lines file per UTC day: intents, fills, cycles, errors. |
| `/var/lib/pmm/reports/` | One Markdown report per self-tune tick. |
| `/var/lib/pmm/params.json` | The parameters the loop reads and the tick writes. |
| `/etc/pmm-mm/pmm.env` | The environment. Not created by the installer. |

## Memory

The loop holds one market snapshot per candidate and nothing else; the
journal is streamed, never loaded whole except by the hourly tick, which
reads the days it needs. The unit caps the service at 400 MB, which is well
inside the box's 960 MB.

## Running without credentials

`POLY_DRY_RUN=1` with no credentials at all is a supported mode. The loop
scores the live markets, builds the quotes, and journals what it would have
placed. This is how the strategy gets exercised before it is trusted with
real orders, and it is how the hourly tick gets a journal to learn from.

## Running in paper mode

`--paper` adds the fill watcher: the loop watches the live book and records
the fills its resting quotes would have produced. The fill is recorded at
our own price, which is the conservative choice, so the paper PnL never
flatters the strategy.
