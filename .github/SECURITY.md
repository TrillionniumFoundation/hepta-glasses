# Security policy

## Supported security scope

Security fixes are prepared against the live source candidate identified by the active pull-request head and Git tree. The default branch may remain an older baseline until protected adoption is complete. Reports must therefore include the exact repository URL, branch or pull request, commit SHA, platform, build identity and affected component.

No source revision is represented as a released product unless the maturity and release gates explicitly say so.

## Reporting a vulnerability

Do not place exploit details, credentials, private keys, tokens, raw audio, sensitive transcripts, personal device identifiers, provider records, proprietary firmware or other confidential evidence in a public issue, pull request, Actions log or repository artifact.

Use GitHub private vulnerability reporting when that option is available for this repository. Otherwise contact a repository owner through an organization-approved private channel and provide only the minimum information needed to establish a private intake route. Do not paste secrets into chat or source to demonstrate access.

A useful initial report contains:

- exact commit, tree, binary or deployment identity;
- affected module and platform;
- preconditions and trust boundary crossed;
- minimal reproduction steps using non-sensitive fixtures;
- expected and observed behavior;
- whether an external or physical effect may already have occurred;
- impact, persistence and known containment;
- proposed disclosure constraints and contact method.

## High-priority classes

The project treats the following as high priority:

- credential, signing-key, KMS/HSM, attestation or OAuth compromise;
- bypass of policy, lease, user-presence, biometric, generation, pair or side authority;
- replay or duplicate external/device effects after an indeterminate result;
- audit-chain, checkpoint, revocation, idempotency or recovery bypass;
- stale callback, transcript, model result or display publication after cancellation;
- prompt injection or untrusted content obtaining mutation authority;
- package signature, dependency, sandbox, egress or workspace escape;
- source, workflow, artifact, reviewer or branch-protection identity substitution;
- exposure of raw audio, transcripts, notifications, calendar, location, accessibility data or credentials;
- unsafe physical behavior, distraction, thermal or power conditions;
- supply-chain substitution of vendored native code or release binaries.

## Triage and containment

Repository maintainers may prepare source containment, tests and documentation, but must not claim provider revocation, physical containment, firmware remediation, independent assurance or release closure without the corresponding authority-issued evidence.

When a possible external effect or credential use is uncertain:

1. stop new admission without deleting evidence;
2. preserve exact candidate, binary, deployment and provider identities;
3. rotate or revoke only through the owning authority;
4. reconcile through authoritative readback rather than replaying the mutation;
5. retain privacy-safe audit metadata and immutable artifact digests;
6. reopen every affected evidence and release gate;
7. obtain independent review before restoring authority.

Issue #86 owns the historical provider-credential incident closure. Issues #93 and #95 own independent assurance and final release acceptance. A public comment or closed issue is not incident evidence by itself.

## Disclosure and release

Coordinate disclosure with affected providers, hardware or firmware vendors, independent assurance and release owners. Do not publish sensitive exploit details before containment and disclosure approval. A security fix that changes source, dependencies, workflows, contracts, application identity, firmware compatibility or release binaries requires fresh qualification for every affected evidence axis.

There is no security-gate or release-gate override.
