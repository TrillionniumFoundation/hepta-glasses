
# ADR-0002: Codex is a specialist, not execution authority

Status: Accepted — 2026-08-30

Codex may diagnose, plan, generate patches and skills, and run tests inside an isolated workspace.
It may not directly own BLE handles, permanent credentials, release signing, production deploy,
or final capability decisions. A deterministic Tool Gateway admits every real mutation.

The product worker permits only read-only or workspace-write sandboxes, uses ephemeral runs,
disables network unless a separately reviewed profile enables it, and rejects full-access or
sandbox-bypass flags.
