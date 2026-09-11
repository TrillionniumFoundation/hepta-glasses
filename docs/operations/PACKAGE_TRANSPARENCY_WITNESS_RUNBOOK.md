# Package transparency consistency and witness operating runbook

Scope: verifier-side admission only. Design:
`docs/development/PACKAGE_TRANSPARENCY_CONSISTENCY.md`. Contract:
`contracts/signed-skill-transparency-v1.json`. This runbook does not create an
operated Log, independent Witness organizations or a product-release approval.

## Configure authority

Obtain Log roots and Witness public keys from independently controlled,
authenticated administration. Record the exact Log ID, floor tree size/root,
Witness identity, key ID, DER public key, validity window and quorum. A key from
the Skill package, HTTP response body or caller JSON is never authority.

Use a floor that was externally accepted and retained. Replacing a floor or
Witness policy changes the verifier binding; perform a reviewed registry policy
migration with execution disabled. Do not lower the floor, reduce quorum or swap
a key to recover from an outage.

Multiple keys for one Witness identity may overlap during rotation, but that
identity contributes one vote. Confirm that the configured organizations are
actually independent; source validation only verifies signatures and identity
labels.

## Acquire and admit evidence

Use a separate bounded authenticated client to obtain:

1. the exact canonical checkpoint and Log signature;
2. the exact manifest inclusion path;
3. the RFC6962 consistency path from the configured floor; and
4. enough canonical Witness statements and signatures for the fixed quorum.

Pass those bytes unchanged to the verifier. Do not recanonicalize a remote
statement after signature, infer a missing consistency node, ignore a bad extra
Witness, or count two keys from one identity twice. Keep proof acquisition and
verification time bounded; expiry is checked again by the registry at final
installation commit.

A smaller tree, same-size root conflict, invalid consistency proof, missing
quorum, expired key/statement or binding mismatch stops installation. Keep the
previously accepted registry and execution state unchanged. A failed admission
is not proof the remote Log or Witness is malicious; preserve the exact external
records for incident review.

## Continuity, gossip and incident handling

The configured root is a fixed floor, not the latest observed checkpoint.
Operate a separate authenticated checkpoint service to publish the latest accepted
view, compare clients and detect out-of-order or split views. Do not represent a
local successful floor proof as global monotonicity.

On conflicting checkpoint or Witness observations:

- stop new Skill installation and affected execution admission;
- preserve checkpoint, consistency path, Witness statements, network provenance
  and externally authenticated timestamps;
- compare independent client and Witness views through the real incident process;
- revoke compromised Log/Witness keys through the external trust authority; and
- resume only with a reviewed policy migration and independently accepted state.

The local Signed Skill audit chain and registry continuity checkpoint are not the
remote Log or Witness record.

## Validation and acceptance

Run the package-transparency, signed-registry-schema and full Signed Registry
suites, then all repository validators, services/adapters discovery, compile
checks and seven canonical CI jobs on one unchanged head. Download and verify the
exact-head artifact and obtain eligible independent review.

Before product use, independently test real Log submission/proof retrieval,
Witness availability and rotation, expiry, quorum loss, split-view response,
checkpoint publication, backup/restore and key compromise. Keep HG-0087/skills
OPEN until those operations plus arbitrary-code isolation, actual egress controls,
task termination, package-vault and deployment requirements are satisfied.
