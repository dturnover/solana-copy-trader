# solana-copy-trader

Phase 1 (current): detect tracked wallets' Pump.fun buys/sells and log them
with latency. No keypair, no execution yet -- this phase exists to validate
signal quality before any capital is at risk. See `.claude`-style plan
history for the full phased roadmap (detection -> pump.fun execution ->
PumpSwap -> mirrored sells -> risk hardening -> Jito/TPU).

Two interchangeable detection engines, picked via `config.json`'s `"engine"`
field -- both feed the same parser/logging path, so switching later doesn't
touch any other code:

- **`poll`** (default): free, polls Shyft's plain RPC every few seconds via
  `getSignaturesForAddress`/`getTransaction`. Multi-second latency -- fine for
  proving the pipeline and a wallet's activity, not for live trading.
- **`geyser`**: real-time Yellowstone gRPC streaming, sub-second latency.
  Requires a paid gRPC plan (Shyft's is $199/mo minimum as of writing -- no
  free/trial tier exists for mainnet streaming from any provider we checked).

## One-time environment setup (WSL2 Ubuntu)

grpc/protobuf are unreliable to build natively on Windows/MSVC via vcpkg, so
this project builds inside WSL2. Run these yourself in a WSL terminal (they
need `sudo`, which needs your password interactively):

```bash
sudo apt update
sudo apt install -y build-essential cmake ninja-build git curl zip unzip tar pkg-config

# Bootstrap vcpkg (skip if you already have one)
git clone https://github.com/microsoft/vcpkg.git ~/vcpkg
~/vcpkg/bootstrap-vcpkg.sh
echo 'export VCPKG_ROOT=$HOME/vcpkg' >> ~/.bashrc
echo 'export PATH=$VCPKG_ROOT:$PATH' >> ~/.bashrc
source ~/.bashrc
```

The project lives on the Windows filesystem (`/mnt/c/Users/muggs/Desktop/Projects/solana-copy-trader`
from WSL). Building there works but is slower than native Linux filesystem I/O;
if first builds feel painfully slow, `cp -r` the project into `~/solana-copy-trader`
and build from there instead.

## Build

```bash
cd /mnt/c/Users/muggs/Desktop/Projects/solana-copy-trader
cmake -B build -S . -DCMAKE_TOOLCHAIN_FILE=$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake
cmake --build build -j
```

First build compiles grpc + protobuf from source via vcpkg -- expect this to
take a while (commonly 20-60+ minutes) even on Linux. Subsequent builds reuse
vcpkg's binary cache and are fast. Adding `curl` for the poll engine on top of
an already-built tree only builds that one new dependency, not everything
again.

## Configure

```bash
cp config/config.example.json config/config.json
```

Edit `config/config.json`:
- `engine`: `"poll"` to start (free) or `"geyser"` once you're paying for
  real-time streaming.
- `rpc.endpoint`: only used by the `poll` engine -- your Shyft REST endpoint,
  e.g. `https://rpc.shyft.to?api_key=YOUR_KEY` (free tier is enough for this).
- `geyser.endpoint` / `geyser.x_token`: only used by the `geyser` engine.
- `tracked_wallets`: replace the placeholder with the actual wallet pubkey(s)
  you want to mirror -- this is not something to guess or hardcode from a
  public label, get it directly from a block explorer/leaderboard.

`config/config.json` is gitignored since it holds your provider token (and,
from Phase 2 on, wallet key material).

## Run

```bash
./build/copytrader config/config.json
```

Expect one log line per detected Pump.fun buy/sell from a tracked wallet,
including `parse_latency_us` (detection -> parse-complete; with the `poll`
engine this reflects poll-cycle timing, not real trade latency). Cross-check
a few against a block explorer for the same wallet/time window to confirm
signal quality before moving on to Phase 2 (live execution) or upgrading to
the `geyser` engine for real-time speed.

## Lag-cost experiment

Before spending money on real-time streaming or live execution, measure
whether copy-trading lag eats the edge:

```bash
./build/lag_experiment config/config.json
```

With `lag_experiment.firehose: true` (recommended) it polls the pump.fun
program itself and samples **any** fresh buy -- lag cost doesn't depend on
who traded, so this gets a large sample fast with no wallet-picking. For
each sampled buy it reads the bonding curve's live reserves immediately
("baseline") and again after each configured lag (e.g. 500ms/2000ms), then
reports the per-sample and running median/mean price change a copier would
have eaten. `max_tx_age_ms` drops transactions detected too late for the
baseline to be meaningful; `csv_path` appends every sample for offline
analysis.

Interpretation rule of thumb: if the median price change at your realistic
execution lag exceeds a couple percent (before fees and priority tips),
naive copy-buying on these curves is structurally unprofitable no matter
which wallet you follow.
