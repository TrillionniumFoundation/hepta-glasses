# Critical protocol and authority test depth

Status: repository-source hardening for mutation authorization, G1 packet framing and deterministic model-worker exhaustion. It does not constitute provider, device, signing or production evidence.

## Mutation-authority wire custody

The mobile mutation-authority client no longer lets Dio decode the response into a `Map` before validation. `HttpMutationAuthorityProvider.authorize()` requests `ResponseBody`, consumes a bounded raw `Stream<Uint8List>`, and applies a strict JSON parser before any lease field is bound.

The parser enforces:

- a hard 64 KiB response limit while the stream is consumed;
- strict UTF-8 without a leading BOM;
- the complete JSON grammar, finite numbers, bounded nesting and bounded token count;
- duplicate-member rejection at every object depth, including equivalent escaped keys;
- no trailing bytes after the one JSON value.

The HTTP boundary additionally requires one `application/json` media type, permits at most one UTF-8 charset parameter, rejects ambiguous or malformed `Content-Length`, checks a declared length against the bytes actually read, disables redirects, accepts only HTTP 200, and treats adapter, token-provider, clock and stream failures as unavailable rather than allowing an exception to escape the authority boundary.

`test/runtime/mutation_authority_http_test.dart` exercises the actual `authorize()` path. It duplicates every authority-critical response field on the wire, injects nested duplicates, malformed UTF-8 and JSON, BOM, trailing data, streaming overflow, media-type and length ambiguity, non-200 responses and external dependency failures. A decoded in-memory `Map` test remains useful for semantic field binding but is not wire evidence because duplicate JSON members have already been collapsed by that point.

## G1 packet shared conformance

`contracts/conformance/g1-packet-v1.json` now carries the v2 closed-world packet contract while retaining the historical path used by both languages. It contains:

- four exact positive fragment/reassembly vectors;
- ten fixed negative vectors with an exact rejection message;
- seven deterministic generated families and immutable seeds;
- 512 generated cases in total.

The negative corpus includes zero declared count, header and metadata drift, expected-command mismatch, a same-cardinality sequence outside the declared range, and a same-cardinality duplicate sequence. The duplicate fixture is exactly three frames with sequences `[0, 1, 1]` and declared total `3`; sequence `2` is absent. Therefore it passes the cardinality gate and reaches the duplicate-occupancy branch rather than failing early on frame count.

Dart and Python load the contract with duplicate-key and non-finite rejection, require exact closed object shapes, exact identifier order, exact case counts and exact seeds, then independently execute every vector and generated family. Unknown fields, duplicate vector IDs, malformed hexadecimal data and metadata drift fail closed.

## Dedicated semantic mutation proof

The Dart packet test creates two temporary standalone programs outside the repository worktree:

1. the canonical `PacketCodec`;
2. a one-line semantic mutant replacing `if (ordered[sequence] != null)` with `if (false)`.

The canonical program must reject the same-cardinality duplicate vector with `Duplicate frame sequence.`. The mutant must fail the test and surface `Missing frame sequence.`. This proves that the duplicate-occupancy branch itself is required; deleting it cannot remain hidden behind the final missing-sequence check.

The proof uses the already qualified Dart SDK, writes only under the system temporary directory, and deletes the directory after the test. It does not mutate tracked source, add a second workflow or transfer evidence from an earlier head.

## Deterministic worker exhaustion

`services/model_gateway/test_bounded_worker_determinism.py` fills all four configured model workers with controlled blocking calls, waits for each worker to enter, proves the callers become indeterminate, verifies a fifth request is fenced before entering the provider, releases late workers and confirms no late result is committed. The test is deterministic and fixture-only; it does not claim live provider capacity or production timeout behavior.

## Formatter custody

Dart formatting is source normalization, not authority evidence. A formatter transport may run only from an isolated operations branch against an exact source commit and an exact changed-path set. It must use a lease-protected push and must not add a workflow to the pull-request tree. The formatting run receives no CI, Artifact or review credit. The final candidate must contain only the canonical `.github/workflows/ci.yml`, and its unchanged exact head must independently pass the canonical formatting check and all six remaining jobs. No diagnostic run or bot-authored intermediate commit transfers qualification evidence.

## Admission and claim ceiling

This source slice is admissible only after all seven canonical jobs succeed on one unchanged head, the exact-head source Artifact is downloaded twice and content-verified, all conversations are resolved, and an eligible non-pusher approves the exact object.

The following remain external gates:

- production identity issuer and mutation-authority service;
- Android/iOS attestation, biometric and device-binding evidence;
- physical Even G1 protocol traces and vendor confirmation;
- production model-provider capacity and reconciliation receipts;
- signing, stores, pilot, rollback and release authority.
