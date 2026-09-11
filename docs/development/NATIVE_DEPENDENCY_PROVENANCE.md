# Native audio dependency provenance and local delta custody

Status: source-custody hardening for the `native-dependencies` module.  
Machine record: `third_party/native-import-provenance.json`.  
Validator: `tools/native/validate_provenance.py`.  
Regression: `services/qualification/test_native_provenance.py`.

## 1. Provenance statement

The repository inherited its native LC3 and RNNoise source through the recorded Even Realities demo snapshot:

- repository: `even-realities/EvenDemoApp`;
- commit: `3899aac2b39ce969582cf6eb96ecb36be3e0e9e6`;
- root tree: `bc593f9b23ce9a49ead8b5652181639157032572`;
- commit time: `2026-06-09T08:27:17Z`;
- GitHub signature state: unsigned/unverified.

The commit/root-tree pair was observed through the upstream GitHub Git Data API and is also recorded in `UPSTREAM.md`. Those two external objects are **not present** in the current repository object database, so an offline local validator cannot honestly re-derive their commit-to-tree binding. The manifest records that limitation explicitly and requires live external revalidation during an independent supply-chain review.

The imported component subtrees and blobs listed below are present in the current repository object database. Those are recomputed locally and form the enforceable repository-custody boundary.

The exact snapshot is an import anchor, not a claim that Even Realities authored the underlying codecs. The direct projects remain `google/liblc3` and `xiph/rnnoise`, with declared licenses and suppliers recorded in `third_party/native-components.json`.

The exact direct-upstream commit/tag used by the demo import was not preserved. The repository therefore retains `version=NOASSERTION` and `revision=NOASSERTION` for those direct components. Similarity to a current or historical upstream file is not sufficient to invent a revision. A direct revision may be added only after a separately reviewed forensic match proves every imported object, or after a controlled upgrade replaces the custody baseline with a known direct-upstream release.

## 2. Exact repository object map

The machine manifest verifies the following locally available directory objects against Git rather than trusting prose:

| Unit | Import object | Current object | Exact local delta |
|---|---|---|---|
| Android public native headers | `c873a86171fb0c5434651ec7fcc2fe5b98cac887` | same | none |
| Android liblc3 source | `8f1326133bcc16bec8a368f39e66bc3c318bb960` | `8977a0943379248387ce7e8a5cbd96278a98d1af` | `bits.c` only |
| Android RNNoise source | `368ecd589aea5b42cc54bc27b342ef52b99f527b` | `83c8effe984615c5b4dbcd68fa8a1300a9dba509` | `denoise.c`, `rnn.c` |
| iOS liblc3 source | `f87a7d9e6da0db4e219754f482b17bf061286f2d` | `38f6f03eb2cd1e521286c6e20098af1772564e5e` | `bits.c` only |

The validator runs `git diff-tree --raw --no-renames` over each exact tree pair and requires the status, modes and old/new blob IDs to equal the manifest. Adding, removing, renaming, mode-changing or modifying any file without updating the reviewed manifest fails closed.

The local platform glue is separately bound:

| File | Import blob | Current blob | Status |
|---|---|---|---|
| `android/app/src/main/cpp/CMakeLists.txt` | `394b4dafe5580accb2f68534c5c0efe485dc8bf8` | same | unchanged |
| `android/app/src/main/cpp/liblc3.cpp` | `fd34bf16a328bcfddaa0bed68c02bcd61608fa3d` | `0a3f0d44951ed98d3f8a861ebc2927afc3a97dda` | local integration delta |
| `ios/Runner/PcmConverter.h` | `cfb6d66245fd0d21cd07d3364867759e14faf6ec` | `032f2cdaad48de92b07210eede61f9e12a6aa895` | local integration delta |
| `ios/Runner/PcmConverter.m` | `00745d79760f747cf8b29c2886c34fa5aa6d2865` | `cae05470c2313980fc535a0b2d6ca4c1e40e6c4f` | local integration delta |
| `ios/Runner/Runner-Bridging-Header.h` | `4754a9fdc22deba7de475615aa89c1d185cafee9` | same | unchanged |

These blob identities establish exactly which integration files moved after import. They do not establish that the local changes are correct, vulnerability-free, legally approved, bit-identical across compilers, or physically qualified.

## 3. Validation contract

`tools/native/validate_provenance.py` enforces:

1. strict UTF-8 JSON with duplicate-key and non-finite-number rejection;
2. a closed manifest shape and fixed repository/import identity;
3. truthful separation between the externally observed commit/root tree and the locally available imported subtrees/blobs;
4. a unique `UPSTREAM.md` binding for the external repository, commit and root tree;
5. exact direct-component IDs without invented versions or revisions;
6. canonical repository paths with no symlink traversal;
7. availability and type of every locally claimed Git tree/blob object;
8. equality between each declared current object and `HEAD:<path>`;
9. complete recomputation of every tree delta, including mode and blob IDs;
10. exact current/import identity for every integration file;
11. consistency between the component inventory and provenance manifest;
12. an explicit evidence ceiling that preserves external revalidation, supplier, legal, vulnerability, binary and physical qualification as separate work.

Run:

```bash
python3 tools/native/validate_provenance.py
python3 -m unittest services.qualification.test_native_provenance -v
```

The full repository `repository-contracts` job also discovers the regression suite. Native sanitizer, Android and iOS jobs remain separate and mandatory.

## 4. Change and upgrade protocol

A native source or integration change must:

1. identify the exact current base objects before editing;
2. update the manifest with every new tree/blob object and exact delta;
3. explain the purpose, security impact, ABI impact and expected PCM behavior;
4. run malformed-input tests, ASAN/UBSAN and cross-platform PCM parity;
5. update the source SBOM/provenance and relevant licenses/notices;
6. preserve Android/iOS build locks and release binary inspection;
7. obtain native-tooling and applicable mobile owner review;
8. run all seven canonical jobs on one unchanged final head;
9. regenerate binary-level provenance for a release candidate;
10. perform physical audio/latency/power/thermal qualification before product claims.

A direct-upstream upgrade additionally requires:

- exact upstream repository, commit/tag and archive or source-tree digest;
- verified license and notice changes;
- an explicit patch series from the chosen upstream object to the repository tree;
- API/ABI and bitstream compatibility review;
- rollback to a retained reviewed source/binary candidate;
- vulnerability disposition for both the old and new baselines.

## 5. Remaining limits

This source increment does **not** close the external `native-dependencies` gates. Remaining work includes:

- independent live revalidation of the external EvenDemoApp commit/root-tree anchor;
- recovering or replacing the unknown direct-upstream revisions;
- independent license/legal review;
- operated vulnerability monitoring and response timelines;
- reproducible release builds and binary-level dependency evidence;
- signed Android/iOS binaries;
- physical G1 speech/audio quality, latency, power, thermal and soak evidence;
- independent security, privacy and safety assurance.

The truthful improvement is narrower: the project now has exact local Git-object custody for imported component subtrees and a mechanically complete local-delta inventory, while keeping the unavailable external and direct-upstream facts visibly unproven.
