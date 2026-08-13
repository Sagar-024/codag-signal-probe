# Proposed fix: Rare Critical Preservation

A technical design + patch for `codag-drain` that stops rare CRITICAL/ERROR
lines from being folded into a dominant template when their unique tokens land
in already-masked `<*>` slot positions.

## Problem (verified)

`codag-drain` groups a window by message similarity (Drain-style), and the
`--format json` artifact only cites a line when it is sampled or is a group's
first member (`samples[].index`, `first_index`). A rare CRITICAL/ERROR line
whose distinctive fields happen to sit at token positions the surrounding
noise already varies is merged into that noise template: its unique value
(e.g. `error=signature_mismatch`) is dropped from slot summaries (which keep
only a handful of distinct values), and its source line is neither cited nor
individually retained.

Observed on the probe's boundary mini-check:

```
1..60 INFO  tool=payments status=ok|degraded error=none|timeout attempt=..
+     1 ERROR tool=payments status=failed error=signature_mismatch attempt=7777

before:  1 group, count=61, template "tool=payments status=<*> error=<*> attempt=<*>"
         signature_mismatch absent, rare line not citable
```

Level is parsed as metadata (`LogLine.level`) and is available before
clustering, but grouping currently ignores it.

## Design

Route high-severity lines through their own clustering lane so they can never
merge with lower-severity lines, while still deduplicating identical repeated
criticals (a crash loop of the same ERROR must stay one group).

Invariant preserved: a high-severity line may only be grouped with other
high-severity lines. This is strictly stronger than "do not merge a singleton"
because it also keeps a rare critical out of a noise group no matter how high
the similarity is, and it handles two rare criticals with different shapes
(arriving in the same noise window) without merging them with each other.

### Algorithm

```
if not preserve_high_severity:
    groups = drain_cluster(all lines)             # current behaviour
else:
    rest_lines  = lines where level not in {error, critical, fatal, crit}
    high_lines  = lines where level     in {error, critical, fatal, crit}
    groups = drain_cluster(rest_lines) ++ drain_cluster(high_lines)
emit groups in ascending first-member order          # unchanged ordering
```

- `drain_cluster` is the existing Drain loop, extracted so it can run per lane.
- Level-less lines (`level = None`, e.g. raw text with no recognizable level
  token) stay in the `rest` lane, so normal logs are unaffected.
- Group emission order stays deterministic: `finalize` sorts by first member.

### Config surface

New opt-in flag on `TemplaterConfig`:

- `preserve_high_severity: bool` (default `false`)

Defaulting to `false` keeps current behaviour byte-identical until the flag is
enabled (validated below), so published benchmarks are unaffected. The CLI
exposes it as `--preserve-high-severity`. A hosted/server flag would use the
same `TemplaterConfig` field.

Severity vocabulary is normalized to `parse_line`'s output (`input.rs`):
`error`, `critical`, `fatal`, `crit`.

## Patch

### 1. `codag-drain/src/compress.rs` — config field

```rust
pub struct TemplaterConfig {
    pub grouper: GrouperKind,
    pub drain_depth: usize,
    pub drain_sim_th: f64,
    pub drain_max_children: usize,
    pub template_clip: usize,
    pub min_static_chars: usize,
    pub sample_cap: usize,
    pub slot_sample_cap: usize,
    pub preserve_high_severity: bool,      // new
}
```

```rust
            sample_cap: DEFAULT_SAMPLE_CAP,
            slot_sample_cap: DEFAULT_SLOT_SAMPLE_CAP,
            preserve_high_severity: false, // new
```

### 2. `codag-drain/src/compress/grouper.rs` — two-lane grouping

`DrainGrouper` gains the flag (struct field, `Default`, and `make_grouper`
wiring for the `Drain`, `DrainStock`, `DrainDelimited` arms):

```rust
pub struct DrainGrouper {
    pub depth: usize,
    pub sim_th: f64,
    pub max_children: usize,
    mode: DrainTokenMode,
    /// Route ERROR/CRITICAL lines through their own clustering lane so a rare
    /// critical line is never folded into a dominant lower-severity template.
    pub preserve_high_severity: bool,
}
```

Core `group()` and helpers:

```rust
impl Grouper for DrainGrouper {
    fn group(&self, lines: &[LogLine]) -> Vec<Group> {
        if !self.preserve_high_severity {
            return finalize(drain_cluster(self, lines));
        }

        // Two lanes: high-severity lines cluster only among themselves, so a
        // rare CRITICAL/ERROR line can never be absorbed into a dominant
        // template of lower-severity lines. A pure crash-loop still dedups
        // because identical criticals land in the same high-lane group.
        let mut high_pos: Vec<usize> = Vec::new();
        let mut high_lines: Vec<LogLine> = Vec::new();
        let mut rest_pos: Vec<usize> = Vec::new();
        let mut rest_lines: Vec<LogLine> = Vec::new();
        for (idx, line) in lines.iter().enumerate() {
            if is_high_severity(line) {
                high_pos.push(idx);
                high_lines.push(line.clone());
            } else {
                rest_pos.push(idx);
                rest_lines.push(line.clone());
            }
        }

        let mut buckets: Vec<Vec<usize>> = drain_cluster(self, &rest_lines)
            .into_iter()
            .map(|bucket| bucket.into_iter().map(|j| rest_pos[j]).collect())
            .collect();
        buckets.extend(
            drain_cluster(self, &high_lines)
                .into_iter()
                .map(|bucket| bucket.into_iter().map(|j| high_pos[j]).collect()),
        );
        finalize(buckets)
    }
}

const HIGH_SEVERITIES: &[&str] = &["error", "critical", "fatal", "crit"];

fn is_high_severity(line: &LogLine) -> bool {
    line.level
        .as_deref()
        .map(|level| HIGH_SEVERITIES.contains(&level))
        .unwrap_or(false)
}

/// Drain clustering over the given lines, returning per-cluster index lists.
fn drain_cluster(cfg: &DrainGrouper, lines: &[LogLine]) -> Vec<Vec<usize>> {
    let mut drain = Drain::new(
        cfg.depth,
        cfg.sim_th,
        cfg.max_children,
        None,
        vec![],
        "<*>".into(),
        true,
    );
    let masker = LogMasker::new(default_masking_instructions());

    let mut by_cluster: BTreeMap<usize, Vec<usize>> = BTreeMap::new();
    for (idx, line) in lines.iter().enumerate() {
        let tokens = drain_tokens(&line.message, cfg.mode, &masker);
        let (cluster, _update) = drain.add_log_message_from_tokens(tokens);
        by_cluster.entry(cluster.cluster_id).or_default().push(idx);
    }
    by_cluster.into_values().collect()
}
```

New unit tests (in `grouper.rs` tests module):

```rust
#[test]
fn rare_critical_is_kept_out_of_dominant_noise() {
    let mut lines = lines_of(&[
        "tool=payments status=ok error=none attempt=1",
        "tool=payments status=ok error=none attempt=2",
        "tool=payments status=ok error=none attempt=3",
    ]);
    lines[0].level = Some("info".to_string());
    lines[1].level = Some("info".to_string());
    lines[2].level = Some("error".to_string());
    let cfg = TemplaterConfig {
        preserve_high_severity: true,
        ..TemplaterConfig::default()
    };
    let groups = make_grouper(&cfg).group(&lines);
    assert_eq!(groups.len(), 2);
    assert_eq!(groups[1].member_indices, vec![2]);
}

#[test]
fn identical_critical_loop_still_deduplicates() {
    let mut lines = lines_of(&["request denied", "request denied", "request denied"]);
    for line in &mut lines {
        line.level = Some("error".to_string());
    }
    let cfg = TemplaterConfig {
        preserve_high_severity: true,
        ..TemplaterConfig::default()
    };
    let groups = make_grouper(&cfg).group(&lines);
    assert_eq!(groups.len(), 1);
    assert_eq!(groups[0].member_indices.len(), 3);
}
```

### 3. `codag-drain/src/bin/codag-drain.rs` — CLI flag

```rust
let mut preserve_high_severity = false;

"--preserve-high-severity" => preserve_high_severity = true,

// after grouper / samples are applied to `config`:
if preserve_high_severity {
    config.preserve_high_severity = true;
}
```

## Behavior changes and invariants

- Output order, group emission, and per-member citations stay deterministic
  (`finalize` sorts by first member; member indices are preserved).
- `original_count` / `template_count` / stats are unaffected except the
  expected additional group when a mixed-severity window is separated.
- Slot statistics of the noise group no longer absorb the rare line's values
  (e.g. `attempt=7777` no longer inflates the noise `attempt` slot).
- Identical repeated criticals still deduplicate (one group, `count=N`).

## Validation (run against a locally built binary)

| scenario | without flag | with `--preserve-high-severity` |
| --- | --- | --- |
| boundary case (60 info + 1 error line) | 1 group `count=61`, `signature_mismatch` absent | 2 groups: noise `count=60`, error `count=1` with full text, cited `first_index`; `signature_mismatch` present |
| crash loop (5 identical ERROR) | 1 group | 1 group `count=5` (still deduped) |
| `retry_storm` probe case | unchanged | identical groups/templates |
| `tool_needle` probe case | unchanged | identical groups/templates |
| cargo test (unit) | — | 40 passed (2 new) |

Flag-off output is structurally identical to the pre-patch binary on both
probe cases (no regression when disabled).

## Trade-offs and open questions

- **Cost**: one extra cluster per high-severity lane, and high-severity lines
  no longer share the dominant template — a small compression-ratio cost in
  exchange for retention. Worth measuring via `line_cx`/`char_cx` on LogHub-2.0
  with the flag on.
- **Level reliability**: the heuristic trusts `parse_line`'s level extraction.
  Logs with no recognizable level token are unaffected (stayed in `rest`).
  If a real deployment feeds already-structured JSON, verify the `level`
  casing matches `input.rs`'s normalized vocabulary.
- **Fatal set**: `HIGH_SEVERITIES` is fixed; expose it via config if Codag
  wants `warn`/`alert` included.
- **Other groupers**: the patch covers the `Drain*` arms (the default path).
  `DrainFullSearchGrouper` / `StatisticalGrouper` can adopt the same two-lane
  split if Codag ships them behind a CLI.
- **Semantics**: this preserves rare criticals *at the cost of not merging*;
  it does not change the inference-based Codag Pro path.

## Alternatives considered

1. **Intercept at insertion inside `drain3_rust::Drain`.** Requires patching
   the vendored crate; severity is invisible to Drain's API; and merge-guard
   rules there are order-dependent (a critical arriving early merges into a
   still-small noise cluster). Rejected.
2. **Raise the similarity threshold for high-severity lines.** Useless for
   this failure: the absorbed line differs only at positions the template
   already masks, so similarity is already near 1.0. Rejected.
3. **Post-hoc eject after clustering.** Works, but re-clustering the ejected
   members is needed anyway, so the two-lane form is simpler and cheaper, and
   it never lets a critical pollute a noise profile in the first place.
4. **Pre-separate at ingest (never cluster criticals at all).** Loses crash-loop
   deduplication. Rejected.

## Next steps

- Run the LogHub-2.0 grouping/compression evals with the flag on to quantify
  the `GA`/`FGA`/compression deltas.
- Add a JSON-schema case to the probing artifact: mixed-severity window where
  the rare line differs only in masked slots, assert it survives with a
  citation.