# O02 — Prospective state domain adapter (pre-cutover)

This is a preliminary, intentionally **not wired to scheduled writers**,
prospective namespace adapter using the existing GitStateStore. Schema 1
legacy observations stay immutable; schema 2 records require fixed code,
provider, calendar and config identity. No auto-initialize or silent fallback.

Read, append and controlled initialize live behind a strict metadata contract.
A per-session conflicting receipt fails, while an identical repeat is idempotent.
The underlying store owns fast-forward retry and preserves other namespaces.

**Not operationally migrated:** production scripts/prospective_archive.py
still writes legacy main. This work must remain a draft until the controlled
prospective bootstrap, writer quiescence and natural schedule gates can be
verified. #14 is independent. No trading orders or performance claims.
