# Critical-path test depth

Status: repository-controlled source qualification. These controls increase evidence about deterministic source behavior; they do not create physical-device, provider, signing, store or release authority.

## Shared conformance vectors

`contracts/conformance/g1-packet-v1.json` is consumed by both Dart and an independent Python reference implementation. It fixes the command, total-frame and sequence offsets, exact binary output, metadata bytes, empty payload behavior, multi-frame ordering and UTF-8-as-opaque-bytes behavior. A vector is useful only when both implementations derive the committed bytes; copying production output into a second expected-value file is prohibited.

`contracts/conformance/mutation-authority-v1.json` binds one nested authorization request to its canonical argument digest, principal context, request fingerprint and exact server response. The Python control-plane test mints the response through the real durable authority, checks idempotent replay and persisted identity, while the Dart test decodes the same response through the mobile production decoder and rejects field drift.

These vectors are source interoperability evidence. They are not a production issuer signature, provider receipt, platform attestation or device trace.

## Deterministic parser and state testing

The packet suite exercises:

- exact golden-vector fragmentation and out-of-order reassembly;
- command, frame-count, sequence and metadata consistency;
- empty, binary and multi-frame payloads;
- byte and packet-size boundaries, including the 255-frame ceiling;
- 500 reproducible, fixed-seed round trips followed by deterministic malformed-frame mutations.

The fixed seed makes failures replayable. It is not presented as exhaustive formal verification or unbounded fuzzing.

The model-worker exhaustion test uses condition/event barriers rather than sleeps. Four provider workers must be observed inside the blocking operation before caller deadlines expire; a fifth dispatch is then rejected while the permits remain held. Releasing the four late workers must not commit any response. This verifies the bounded in-process custody contract but does not substitute for socket deadlines, process isolation, provider cancellation or deployed overload tests.

## Critical line-coverage contract

`contracts/conformance/critical-coverage-v1.json` contains reviewed per-file minimums for critical Dart sources. The Flutter job produces LCOV data and `services/qualification/critical_quality_gate.py coverage`:

1. parses source and line records with duplicate and path-traversal rejection;
2. requires each contracted source to exist as one regular repository file;
3. requires a minimum number of instrumented lines so a vacuous percentage cannot pass;
4. calculates covered instrumented lines and fails below the committed threshold.

A threshold change is a source change and requires ordinary review. Coverage is a floor, not a statement that uncovered behavior is safe or that a high percentage proves correctness.

## Semantic mutation gate

After the unmodified packet suite passes, the quality gate applies one semantic source mutation at a time to `lib/runtime/packet_codec.dart`:

- weaken the 255-frame ceiling;
- disable expected-command binding;
- disable cross-frame metadata binding.

Each mutant must make the focused packet suite fail. The source file is restored byte-for-byte after every attempt and rechecked by the job's final clean-worktree gate. A surviving mutant fails CI. The mutation list is deliberately small and reviewable; it demonstrates that critical assertions observe these boundaries, not that every possible mutation has been killed.

## Canonical workflow placement

All additions remain inside the existing seven-job workflow authority:

- Python vector, deterministic concurrency and gate-unit tests run in `repository-contracts`;
- Dart vectors, fixed-seed parser tests, LCOV thresholds and semantic mutations run in `flutter`;
- the other platform, sanitizer, scan and exact-head Artifact jobs remain unchanged.

No eighth required context, write credential, self-modifying workflow or alternate evidence authority is introduced.

## Remaining external qualification

The following roadmap items remain external and cannot be closed by these fixtures:

- Android/iOS signed install, upgrade, downgrade and rollback testing;
- physical Even G1 reconnect, latency, packet-loss, audio/display and long-soak HIL runs;
- production model, realtime, speech, OAuth and capability failure injection;
- KMS/HSM, platform attestation, vendor firmware/OTA and secure-boot evidence;
- independent security, privacy, accessibility, safety and release assurance.

Those facts require their real issuing environments and independently authenticated evidence bound to the exact release candidate.
