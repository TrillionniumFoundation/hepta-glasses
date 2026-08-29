
# ADR-0003: incremental Dart edge runtime with a stable extraction seam

Status: Accepted — 2026-08-30

The imported application is Flutter/Dart with native Kotlin, Swift, C, and C++ device code. The
first runtime closure is implemented in pure Dart so it can be integrated and tested without a
second packaging system. Interfaces and JSON Schemas are versioned so security-critical runtime
components may later move to Rust without changing product semantics.

No future extraction may weaken journal-before-effect, idempotency, decision-lease, cancellation,
or receipt invariants.
