# Verification notes

## What was verified (Phase 0)

Target: Codag (codag.ai, YC S26), deterministic engine `codag-drain`
(open source, MIT, github.com/codag-megalith/codag-drain).

Sources inspected: codag.ai homepage + docs, codag-cli README, codag-drain
README, and the codag-drain source (`compress.rs`, `input.rs`, CLI in
`src/bin/codag-drain.rs`). The probe was then run against a locally built
`codag-drain` binary.

### Input / output contract (confirmed)

- Input: any line-oriented text via stdin. `codag-drain` heuristically
  strips a leading ISO-8601/epoch timestamp and a level token; the remainder
  is the message. Grouping is done on the message only.
- Output: `--format json` renders the full `TemplateResult`:
  `groups[]`, each with `first_index`, `count`, `template` (with `<*>`
  slots), `samples[]` (up to 3 raw member lines, each with its 0-based
  input `index`, `text`, `level`, `timestamp`), and `slots[]` summaries.
  `--format text` renders `[xN] template [slot summaries] samples: ...`.
- The free/deterministic path is this engine; it runs fully local, no
  account, no network.

### Recovery mechanism selected

The artifact advertises line-number citations: the codag.ai homepage shows
`refs=412847,+311` and a `ctx near 412847` block with literal source line
numbers, and states "every kept line cites a real log line number". In
`codag-drain --format json` the equivalent mechanism is the per-group
sample line indexes (`samples[].index`, `first_index`): a retained line is
recoverable when its input index is cited and its full text is present.

The verifier therefore does NOT use naive exact-string matching. It checks
the index-citation mechanism first, then whether the rare line's own
signals (needle, error, status, tool, level) are present in the artifact.

## Probe design decisions

- Case 1 (`retry_storm`): rare CRITICAL line is structurally distinct from
  the WARN retry noise (longer, extra fields), like a real webhook failure
  surfacing inside a retry loop.
- Case 2 (`tool_needle`): rare ERROR line keeps the same field layout as
  the INFO tool noise (`tool=.. status=.. error=.. attempt=..`), like a
  payment failure that looks like every other call from the outside.

## Results observed

Both rare lines were retained as their own `count=1` template group with
full text and a cited line index. Notably, `tool=payments` vs `tool=gateway`
is treated as static template text (not a masked slot), so the 20k noise
split into per-tool groups; this made the value-bearing rare line distinct
enough to form its own group.

## Mechanism boundary (observational mini-check, not an official case)

A line whose differing fields fall only at token positions the noise
already varies (masked `<*>` slots) is folded into the dominant template:
a synthetic `tool=payments status=failed error=signature_mismatch` line
inside `tool=payments status=<*> error=<*> attempt=<*>` noise produced a
single `count=61` template and `signature_mismatch` was absent from the
compressed artifact. This is consistent with documented behavior: the
templater groups by message and slot summaries keep at most a few distinct
values per slot. It is an observation about the mechanism, not a bug claim.

## Caveats

- Probe covers the open-source deterministic engine, not Codag Pro's
  inference-based compaction.
- Two handcrafted cases; not a correctness audit.
