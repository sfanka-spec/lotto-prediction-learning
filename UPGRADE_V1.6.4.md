# Upgrade to V1.6.4

Drop-in upgrade from V1.6.3. Reuse the same data directory and SQLite database; no migration is required.

V1.6.4 changes Learning Center diagnostic wording and Champion post-draw diagnostic schema only. Frozen pre-draw predictions remain immutable. When legacy Champion diagnostics are backfilled/refreshed, they are recomputed only from the original freeze plus the official result; this does not create an extra statistical sample.
