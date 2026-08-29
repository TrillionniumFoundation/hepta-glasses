# Hepta Glasses canonical development plan

Revision: `2026-08-30-g2`
Supersedes: `2026-08-30-g1`

## 1. Mission

Convert the imported G1 companion demo into the edge component of a distributed AI-native glasses OS. The system must preserve the working device protocol while making identity, context, model use, tools, memory, Codex, physical qualification, and release evidence explicit and fail closed.

The current repository does not contain the G1 bootloader or firmware source. Consequently, â€œOSâ€ means a distributed product boundary until vendor firmware access exists: G1 device plane, mobile edge runtime, cloud control plane, capability adapters, and isolated Codex workers.

## 2. Non-negotiable invariants

1. Model, realtime model, MCP, Skill, and Codex output are proposals, never final execution authority.
2. The mobile bundle contains no permanent provider, OAuth, signing, or account credential.
3. Every mutation is journaled before effect and bound to an idempotency fingerprint.
4. Timeout, process death, or disconnect is indeterminate and requires authoritative reconciliation.
5. A decision lease is subject/device/task/action/exact-argument bound, short-lived, and normally single-use.
6. R4 capabilities remain unavailable in the consumer profile.
7. Untrusted notification, document, webpage, transcript, or tool content cannot grant authority.
8. Codex runs in isolated read-only or workspace-write workers; it does not own BLE, production credentials, release signing, or self-merge authority.
9. Memory requires explicit purpose and data-class consent; raw audio, credentials, and secrets are never long-term memory classes.
10. Source tests and digital twins cannot substitute for physical-device, production-credential, independent-review, pilot, or release evidence.

## 3. Gate sequence

### G0 â€” truth and governance

Deliver canonical truth, ADRs, Gap Ledger, evidence index, schemas, validators, CI, CODEOWNERS, PR controls, and an enforceable branch-protection contract.

Source gate: canonical files and validators pass. Product gate: GitHub reports the `main` protection contract as active.

### G1 â€” deterministic device substrate

Deliver HAL, packet codec, dual-leg coordinator, capability/version negotiation, digital twin, golden vectors, disconnect/NACK/timeout injection, and per-leg receipts.

Source gate: replay produces no duplicate logical write and partial success is explicit. Product gate: both Android and iOS physical traces pass the qualification scenario.

### G2 â€” edge execution authority

Deliver hash-chained audit, durable task state, restart recovery, cancellation, deadlines, idempotency, policy, exact leases, tool registry, journal-before-effect execution, and receipts.

Gate: corrupt journal, stale generation, mismatched replay, unknown tool, expired lease, and argument drift fail closed.

### G3 â€” identity and cloud control

Deliver device registration, attestation-verifier interface, key-ID signing ring, short-lived subject/device/session-bound tokens, rate limits, token/session/device/subject revocation, account recovery contract, and production deployment runbook.

Source gate: reference control-plane tests pass. Product gate: deployed KMS-backed issuer, platform attestation, key rotation, revoke, lost-device, and recovery drills produce signed evidence.

### G4 â€” realtime interaction

Deliver one-time realtime bootstrap tickets, server-side provider exchange boundary, bounded scopes, session state machine, privacy indicator truth, cancellation, barge-in generation fencing, network fallback, and physical SLO evaluator.

Source gate: ticket replay, stale generation, disallowed scope, and unauthorized provider profile fail closed. Product gate: physical Android and iOS traces meet wake, display, packet-loss, temperature, battery, and fault thresholds.

### G5 â€” capability tool OS

Deliver opaque OAuth credential handles, typed adapters, exact-argument lease admission, untrusted-content separation, schema validation, journal-before-effect, idempotency, authoritative reconciliation, approval UI contract, and mutation receipts.

Source gate: deterministic adapter and negative tests pass. Product gate: real calendar/reminder/notification/location adapters produce external receipts and timeout reconciliation evidence.

### G6 â€” Codex specialist lane

Deliver one-task/one-workspace/one-identity workers, fixed non-interactive invocation or supported SDK/App Server integration, bounded output/runtime/network, no device credentials, patch/test custody, maintainer review, and no self-merge.

Source gate: launcher and policy tests pass. Product gate: deployed worker isolation, short-lived identity, egress policy, credential boundary, and compromise-containment exercises pass.

### G7 â€” skills and memory

Deliver signed manifests, publisher trust roots, package digests, domain/capability/data-class admission, upgrade re-consent, revoke, purpose-bound memory, TTL, export, individual delete, purpose revoke, subject delete, and encrypted production storage contract.

Source gate: signature tampering, R4 manifest, unauthorized domains, missing consent, and revoked Skill fail closed. Product gate: production signing roots and encrypted storage complete independent review and deletion drills.

### G8 â€” qualification, pilot, and release

Deliver physical trace evaluator, fault matrix, source SBOM, provenance, release evidence bundle, product release gate, branch-protection verifier/applier, security/privacy/legal review templates, staged rollout, kill switch, rollback drill, signing evidence, and pilot telemetry.

Source gate: exact-head evidence artifact and source release gate pass. Product gate: the product release bundle passes without overrides.

## 4. Evidence levels

- E0 â€” \ÚYÛ‹ØÚ[XKÜˆİ]XÈÛÛ˜Xİ‚‹HLH8 %[š][™™YØ]]™H\İË‚‹HLˆ8 %YÚ][Ú[‹™\^K[™]\›Z[š\İXÈ˜][[š™Xİ[Û‹‚‹HLÈ8 %ØØ[[YÜ˜][Ûˆ[™^XİZXYÙ[™\˜]Y\Y˜XİË‚‹HM8 %^XİÚ]Xˆ‹ZXYÒH[™Ûİ\˜ÙH]šY[˜ÙH[™K‚‹HMH8 %\ÚXØ[Û™H\ÈÌH˜XÙH[™]]Üš]]]™H^\›˜[\Ş\İ[H™XÙZ\Ë‚‹HMˆ8 %[İ[[Y]KÚ[\İÚ]Ú^\˜Ú\ÙK›Û˜XÚÈš[İYÙY›Ûİ]‚‹HMÈ8 %Z[™\[™[ÙXİ\š]Kš]˜XŞKYØ[XØÙ\ÜÚXš[]KÜˆ™[™Üˆ™]šY]Ë‚‚“İÙ\ˆ]šY[˜ÙH™]™\ˆØ]\ÙšY\ÈHYÚ\ˆ]šY[˜ÙH™\]Z\™[Y[‚‚ˆÈÈKˆİ\œ™[XÚØYÙHØÛÜB‚˜K[˜]]™KY›İ[™][Û‹]ŒX\ÈÌËYÎ\Ûİ\˜ÙKXÛÜİ\™K]ŒX›İÈ›İšY\ÈH™\ÜÚ]ÜK\ÚYH[\[Y[][Ûˆ[™XØÙ\[˜ÙH\›™\ÜÈ›ÜˆÌ8 $Òˆ]Ù\È›İÛÛZ[ˆ›ÙXİ[Ûˆ[˜[˜ŞK]›Ü›H]\İ][ÛˆÜ™Y[X[Ë›İšY\ˆÜ™Y[X[Ë\ÚXØ[\™Ø\™H˜XÙ\Ë™[™Üˆš\›]Ø\™H]]Üš]K[Øš[HÚYÛš[™ÈY[]Y\Ë[™\[™[\›İ˜[ËÜˆ[İ[[Y]K‚‚ˆÈÈ‹ˆÛÜÙ[İ]İ]\Â‚‹HÓÔÑQÔÓÕTÑX8 %Ûİ\˜ÙHXØÙ\[˜ÙHÜš]\šXH[™^XİZXY\İÈ^\İ‚‹HÓÔÑQÕ‘T’Q’QQ8 %[™\]Z\™Y^\›˜[Ù]šXÙH]šY[˜ÙH^\İË‚‹H“ĞÒÑQÑVT“S8 %H˜[YY\™Ø\™KÜ™Y[X[\Ş[Y[™]šY]ËÜˆ[İ[œ]\ÈXœÙ[‚‹H“ĞÒÑQĞQRS—ÔÑUS‘8 %[ˆYZ[š\İ˜]Ü‹[Û›H™\ÜÚ]ÜHÙ][™È\ÈXœÙ[‚‹H“ĞÒÑQÕTÕ‘PST8 %™[™Üˆš\›]Ø\™KÚYÛš[™ËÜˆ›İØÛÛ]]Üš]H\ÈXœÙ[‚‹HÔS˜8 %Xİ[Û˜X›HÛİ\˜ÙHÛÜšÈ™[XZ[œË‚‚HXÚØYÙH\ÈÛİ\˜ÙKXÛÜÙYÛ›HÚ[ˆ›ÈÔS˜Ûİ\˜ÙH][H™[XZ[œËˆH›ÙXİ\È™[X\ÙKXÛÜÙYÛ›HÚ[ˆ]™\H™\]Z\™Y›ØÚÙ\ˆ\ÈÓÔÑQÕ‘T’Q’QQ[™ÛÛËÙ]˜[X]WÜ™[X\ÙWÙØ]KœHK[[ÙH›ÙXİ\ÜÙ\Ë‚