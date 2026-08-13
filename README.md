# Codag Signal Probe & Fix: Preserving Rare Critical Errors

A small, reproducible probe for [Codag](https://codag.ai)'s deterministic log-compression engine (`codag-drain`) — plus a validated patch that fixes the case where rare CRITICAL/ERROR lines get lost.

## The Problem

`codag-drain` groups a log window by message similarity and collapses each group into one template with `<*>` slots. There is a blind spot: if a rare CRITICAL/ERROR line's *unique* tokens fall into token positions the surrounding noise already varies (masked `<*>` slots), the line is folded into the dominant template. Its distinguishing value (e.g. `error=signature_mismatch`) is dropped from slot summaries — which keep only a handful of distinct values — and the line is no longer individually cited by its source index.

Reproduced in `notes/verification.md`: 60 INFO lines + 1 ERROR line with all values at masked positions collapsed into a single `count=61` template, `signature_mismatch` absent from the compressed artifact.

## The Fix: Two-Lane Clustering

Instead of a simple "don't merge a singleton" count guard, the patch separates lines by severity **before** clustering:

- ERROR/CRITICAL lines cluster only among themselves.
- They can never merge with lower-severity noise, no matter how high the similarity.
- Level-less lines and normal logs are untouched (stay in the lower-severity lane).

This is enabled by the `--preserve-high-severity` flag (**default `false`, zero regression** when off). Repeated criticals still deduplicate: a crash loop of 5 identical ERRORs becomes one `count=5` group.

## Validation Results

| scenario | without flag | with flag |
|---|---|---|
| boundary case (60 INFO + 1 ERROR at masked slots) | 1 group `count=61`, signature lost | 2 groups; error is `count=1`, `first_index` cited, `signature_mismatch` present |
| crash loop (5 identical ERROR) | 1 group | 1 group `count=5` (dedup preserved) |
| both official probe cases | unchanged | **byte-identical JSON** to committed results |
| `cargo test -p codag-drain` | — | 40 passed (2 new) |

Full design, edge cases, and trade-offs: [`PROPOSED_FIX.md`](PROPOSED_FIX.md).

## Design Rationale

Raising the similarity threshold does **not** fix this. The absorbed line differs only at positions the template already masks, so its similarity to the dominant template is already ~1.0 — a stricter threshold has nothing to separate on. Severity is the one dimension the grouping ignores, so a severity lane is the right shape of fix: it gives the rare line its own cluster (and therefore its own template, full text, and source citation) before similarity is ever consulted.

## How to Apply the Patch

```bash
# 1. Clone the open-source engine
git clone https://github.com/codag-megalith/codag-drain.git
cd codag-drain

# 2. Apply the patch
git apply /path/to/codag-signal-probe/patches/codag-drain-rare-critical-preservation.patch

# 3. Build and run the (new) unit tests
cargo test -p codag-drain
cargo build --release -p codag-drain

# 4. Run this probe with the fix enabled (default off = zero regression)
cd /path/to/codag-signal-probe
CODAG_DRAIN_BIN=/path/to/codag-drain/target/release/codag-drain \
  PRESERVE_HIGH_SEVERITY=1 ./run_probe.sh
```

The patch touches three files: `compress.rs` (config flag), `compress/grouper.rs` (two-lane clustering + tests), and the CLI (`--preserve-high-severity`).

## Limitations

Preliminary probe, not a correctness audit. Two handcrafted cases. Covers the open-source deterministic engine behind `codag wrap`, not Codag Pro inference. The fix is validated locally but not merged upstream.
