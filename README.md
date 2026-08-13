# codag-signal-probe

A small probe testing whether rare critical debugging signals survive Codag compression.

**Question**
When 20,000 repetitive agent logs are compressed by `codag-drain`, can a single rare CRITICAL / ERROR event still be recovered, with its source citation?

**Test cases**
1. `retry_storm` — 20k WARN retry logs + 1 rare CRITICAL billing webhook failure (`CRITICAL_NEEDLE_8f3a`).
2. `tool_needle` — 20k INFO tool logs + 1 rare ERROR payments failure (`TOOL_NEEDLE_2c9d`).

**Method**
Generate logs, run them through `codag-drain --format json`, then verify recovery against the mechanism Codag documents: template groups where kept lines carry their original 0-based line index (`first_index`, `samples[].index`).

**Results**
Both rare lines survive as their own `count=1` template with full text and a cited line index. See `results.txt`.

**Run**
```
CODAG_DRAIN_BIN=/path/to/codag-drain ./run_probe.sh
```

**Limitations**
Preliminary probe, not a correctness audit. Two handcrafted cases. Covers the open-source deterministic engine behind `codag wrap`, not Codag Pro inference. See `notes/verification.md` for the observed mechanism boundary (a line that differs only at already-masked slot positions folds into the dominant template).
