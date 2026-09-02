# ADR-0004: Authenticate external closure evidence with an externally pinned Ed25519 registry

- Status: accepted for G9 source
- Date: 2026-09-02
- Extends: plan revision `2026-09-01-g8`
- Contract revision: `2026-09-02-g9-authenticated-1`

## Context

The twelve remaining product gaps cannot be closed by repository source alone. Their facts belong to physical-device labs, production providers, repository administrators, firmware vendors, independent reviewers, signing authorities, pilot operators, and stores. A repository writer can nevertheless edit JSON, artifact bytes, hashes, public keys, reviewer fields, and acceptance state. File hashes and self-declared identities therefore do not authenticate an external authority.

The initial G9 envelope verified artifact digests and structural claims but could still be forged by inventing different issuer and reviewer names and recomputing a bundle hash. That is unacceptable because a syntactically valid package could be mistaken for E5-E7 or administrative closure.

## Decision

G9 uses Ed25519 signatures over deterministic canonical JSON statements and an authority registry whose exact file SHA-256 is supplied through an out-of-band protected channel.

Each registry key binds:

- key ID and public-key digest;
- verified identity and organization;
- issuer or reviewer usage;
- authority class and permitted gap IDs;
- validity interval and revocation state.

Each submission signature covers the exact candidate, registry digest, gap, evidence level, issuer binding, environment, subjects, required claims, result, limitations, notes, and every artifact digest. Each acceptance signature covers the same candidate and registry, the complete evidence-set digest, reviewed gap IDs, decision, review artifact, and signing time.

Validation rejects unknown or substituted keys, invalid signatures, wrong usage/class/gap, expired or revoked keys, path escape, candidate drift, artifact drift, issuer/reviewer identity or key aliases, same-organization independence claims, missing per-gap approval coverage, and synthetic evidence for physical-only gaps.

The registry copy included with a custody package is reproducibility data, not its own trust anchor. Private keys never enter source, pull requests, ordinary CI artifacts, logs, or evidence packages.

## Alternatives rejected

- **Self-hashed bundle:** integrity without authority; any writer can recompute it.
- **Optional detached signature checked only by file hash:** proves neither signer nor signed subject.
- **Repository-committed public-key registry as sole root:** the submitter could replace evidence and trust root together.
- **One omnipotent repository key:** destroys authority separation and independent review.
- **Boolean `independent` field:** self-asserted metadata is not organizational independence.
- **Network lookup during validation:** weakens reproducibility and makes closure depend on mutable remote state.

## Consequences

Evidence collection now requires external key enrollment, proof of possession, narrow authorization, registry rotation/revocation procedures, protected digest distribution, and signed acceptance. This adds operational work but prevents repository code or a single maintainer from manufacturing closure. Source and CI can verify the mechanism only through E4; they cannot create the real-world evidence or authority behind E5-E7.

Any candidate, artifact, provider, firmware, binary, registry generation, key validity, or review change invalidates the affected statements and reopens the corresponding row.
