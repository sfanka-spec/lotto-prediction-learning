# Lottery AI V1.6.2 — Current Draw Clarity & Diagnostic Label Hardening

V1.6.2 is a presentation/integrity-label refinement on top of V1.6.1. It does not change Production ranking weights, candidate generation, freeze contents, model learning, or automatic spending behavior.

## Current Draw clarity
- Tied best-hit tickets are now displayed as **Tied best-hit ranks** with one explicitly labelled example ticket, avoiding the implication that every tied ticket has identical numbers.
- `winner coverage` is renamed to **portfolio winning-number coverage** so 7/7 cannot be confused with one ticket hitting 7/7.
- Champion placement and whole-portfolio score-vs-hit Spearman correlation are shown separately.
- Spearman receives a descriptive correlation label (`NEUTRAL`, `WEAK_POSITIVE`, `WEAK_NEGATIVE`, `POSITIVE`, `NEGATIVE`) without implying statistical significance.

## Evidence display
- Bayesian research leaders with effective sample size below 30 now display an explicit **LOW SAMPLE** warning.
- `NO_FREEZE` is rendered as **NOT CREATED YET (target YYYY-MM-DD)** when a valid next target exists, reducing false alarm wording.

## Data-status wording
- `Raw integrity` is renamed **Raw audit pass ratio** and is explicitly described as the share of stored rows not flagged invalid, unverified-off-calendar, or conflicted. It is not presented as a probability that the archive is correct.
- Existing quarantine behavior is unchanged: unverified off-calendar rows remain excluded from model-ready history until independently verified.
