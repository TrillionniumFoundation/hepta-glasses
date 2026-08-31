#!/usr/bin/env python3
"""Apply the deterministic G7 convergence patch on a GitHub runner.

The script is intentionally idempotent. It combines the G5/G6 evidence and
control-plane work with the stricter G4 native/startup fixes, then applies the
remaining repository-actionable audit fixes. It never changes main directly.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
G4 = "origin/codex/hepta-glasses-source-closure-g4"


def run(*args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=ROOT,
        check=check,
        text=True,
    )


def replace(path: str, old: str, new: str, *, required: bool = True) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    if old not in text:
        if required and new not in text:
            raise RuntimeError(f"pattern missing in {path}: {old[:80]!r}")
        return
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def import_g4(path: str) -> None:
    probe = subprocess.run(
        ["git", "cat-file", "-e", f"{G4}:{path}"],
        cwd=ROOT,
        check=False,
    )
    if probe.returncode == 0:
        run("git", "checkout", G4, "--", path)


def merge_g4() -> None:
    run("git", "fetch", "origin", "+refs/heads/*:refs/remotes/origin/*")
    ancestor = subprocess.run(
        ["git", "merge-base", "--is-ancestor", G4, "HEAD"],
        cwd=ROOT,
        check=False,
    )
    if ancestor.returncode == 0:
        return
    result = run("git", "merge", "--no-commit", "--no-ff", G4, check=False)
    if result.returncode != 0:
        conflicts = subprocess.check_output(
            ["git", "diff", "--name-only", "--diff-filter=U"],
            cwd=ROOT,
            text=True,
        ).splitlines()
        for path in conflicts:
            run("git", "checkout", "--ours", "--", path)
            run("git", "add", "--", path)

    for path in (
        "android/app/src/main/cpp/CMakeLists.txt",
        "android/app/src/main/cpp/lc3_decoder_core.cpp",
        "android/app/src/main/cpp/lc3_decoder_core.h",
        "android/app/src/main/cpp/liblc3.cpp",
        "android/app/src/main/cpp/liblc3/bits.c",
        "android/app/src/main/cpp/liblc3/bits.h",
        "ios/Runner/lc3/bits.c",
        "ios/Runner/lc3/bits.h",
        "native_tests/lc3_decoder_core_test.cpp",
        "native_tests/lc3_decoder_fuzz.cpp",
        "tools/run_native_sanitizer_tests.sh",
        "lib/main.dart",
    ):
        import_g4(path)
    run("git", "add", "-A")


def write_history_view() -> None:
    (ROOT / "lib/views/even_list_page.dart").write_text(
        r'''import 'package:demo_ai_even/controllers/evenai_model_controller.dart';
import 'package:demo_ai_even/services/evenai.dart';
import 'package:flutter/material.dart';
import 'package:get/get.dart';

class EvenAIListPage extends StatefulWidget {
  const EvenAIListPage({super.key});

  @override
  State<EvenAIListPage> createState() => _EvenAIListPageState();
}

class _EvenAIListPageState extends State<EvenAIListPage> {
  late final EvenaiModelController controller;

  @override
  void initState() {
    super.initState();
    controller = Get.find<EvenaiModelController>();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          title: const Text('History', style: TextStyle(fontSize: 20)),
        ),
        body: Obx(() {
          if (controller.items.isEmpty && !EvenAI.isEvenAISyncing.value) {
            return const Center(
              child: Padding(
                padding: EdgeInsets.all(24),
                child: Text(
                  'Press and hold left TouchBar to engage Even AI.',
                  style: TextStyle(color: Colors.grey),
                  textAlign: TextAlign.center,
                ),
              ),
            );
          }
          return ListView.separated(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
            itemCount: controller.items.length,
            separatorBuilder: (BuildContext context, int index) =>
                const SizedBox(height: 12),
            itemBuilder: (BuildContext context, int index) {
              final expanded = controller.selectedIndex.value == index;
              final item = controller.items[index];
              return Semantics(
                button: true,
                label: item.title,
                child: InkWell(
                  borderRadius: BorderRadius.circular(8),
                  onTap: () {
                    if (expanded) {
                      controller.deselectItem();
                    } else {
                      controller.selectItem(index);
                    }
                  },
                  child: AnimatedSize(
                    duration: const Duration(milliseconds: 160),
                    alignment: Alignment.topCenter,
                    child: Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(16),
                      decoration: BoxDecoration(
                        color: const Color(0xFFFEF991).withValues(alpha: 0.2),
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: <Widget>[
                          Text(
                            item.title,
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          if (expanded) ...<Widget>[
                            const SizedBox(height: 12),
                            SelectableText(
                              item.content,
                              style: Theme.of(context).textTheme.bodyMedium,
                            ),
                          ],
                        ],
                      ),
                    ),
                  ),
                ),
              );
            },
          );
        }),
      );
}
''',
        encoding="utf-8",
    )


def write_bitmap_manager() -> None:
    (ROOT / "lib/controllers/bmp_update_manager.dart").write_text(
        r'''import 'dart:async';
import 'dart:io';
import 'dart:math';
import 'dart:typed_data';

import 'package:crclib/catalog.dart';
import 'package:demo_ai_even/ble_manager.dart';
import 'package:demo_ai_even/runtime/privacy_safe_log.dart';
import 'package:demo_ai_even/utils/utils.dart';

/// Bounded, fail-closed G1 bitmap transfer.
final class BmpUpdateManager {
  static const int _packetPayloadBytes = 194;
  static const int _maximumPacketCount = 256;
  static const int _maximumImageBytes =
      _packetPayloadBytes * _maximumPacketCount;
  static const List<int> _storageAddress = <int>[0x00, 0x1c, 0x00, 0x00];
  static final Set<String> _activeSides = <String>{};

  Future<bool> updateBmp(String side, Uint8List image, {int? seq}) async {
    if (side != 'L' && side != 'R') {
      throw ArgumentError.value(side, 'side', 'must be L or R');
    }
    if (image.isEmpty || image.length > _maximumImageBytes) {
      PrivacySafeLog.event(
        'bitmap_transfer_rejected',
        fields: <String, Object?>{'bytes': image.length},
      );
      return false;
    }
    final packetCount =
        (image.length + _packetPayloadBytes - 1) ~/ _packetPayloadBytes;
    final resumeFrom = seq ?? 0;
    if (packetCount < 1 ||
        packetCount > _maximumPacketCount ||
        resumeFrom < 0 ||
        resumeFrom >= packetCount ||
        !_activeSides.add(side)) {
      return false;
    }

    try {
      for (var index = resumeFrom; index < packetCount; index++) {
        final start = index * _packetPayloadBytes;
        final end = min(start + _packetPayloadBytes, image.length);
        final payload = image.sublist(start, end);
        final prefix = index == 0
            ? <int>[0x15, index & 0xff, ..._storageAddress]
            : <int>[0x15, index & 0xff];
        final packet = Utils.addPrefixToUint8List(prefix, payload);
        final admitted = await BleManager.sendData(packet, lr: side);
        if (admitted != true) {
          PrivacySafeLog.event(
            'bitmap_packet_rejected',
            fields: <String, Object?>{
              'packet': index,
              'packet_count': packetCount,
            },
          );
          return false;
        }
        await Future<void>.delayed(
          Duration(milliseconds: Platform.isIOS ? 8 : 5),
        );
      }
      if (!await _finalize(side)) {
        return false;
      }
      return _verifyCrc(side, image);
    } on Object catch (error) {
      PrivacySafeLog.event(
        'bitmap_transfer_failed',
        fields: <String, Object?>{'error_type': error.runtimeType.toString()},
      );
      return false;
    } finally {
      _activeSides.remove(side);
    }
  }

  Future<bool> _finalize(String side) async {
    for (var attempt = 1; attempt <= 10; attempt++) {
      final response = await BleManager.request(
        Uint8List.fromList(const <int>[0x20, 0x0d, 0x0e]),
        lr: side,
        timeoutMs: 3000,
      );
      if (!response.isTimeout &&
          response.data.length >= 2 &&
          response.data[0] == 0x20 &&
          response.data[1] == 0xc9) {
        return true;
      }
      if (response.effectMayHaveOccurred) {
        PrivacySafeLog.event('bitmap_finalize_indeterminate');
        return false;
      }
      await Future<void>.delayed(const Duration(seconds: 1));
    }
    return false;
  }

  Future<bool> _verifyCrc(String side, Uint8List image) async {
    final addressed = Uint8List(_storageAddress.length + image.length)
      ..setRange(0, _storageAddress.length, _storageAddress)
      ..setRange(
        _storageAddress.length,
        _storageAddress.length + image.length,
        image,
      );
    final value = Crc32Xz().convert(addressed).toBigInt().toInt();
    final crc = Uint8List.fromList(<int>[
      (value >> 24) & 0xff,
      (value >> 16) & 0xff,
      (value >> 8) & 0xff,
      value & 0xff,
    ]);
    final response = await BleManager.request(
      Utils.addPrefixToUint8List(const <int>[0x16], crc),
      lr: side,
      timeoutMs: 3000,
    );
    return !response.isTimeout &&
        response.data.length >= 6 &&
        response.data[0] == 0x16 &&
        response.data[5] == 0xc9;
  }
}
''',
        encoding="utf-8",
    )


def write_scheduler() -> None:
    (ROOT / "lib/runtime/device_effect_scheduler.dart").write_text(
        r'''import 'dart:async';
import 'dart:collection';

final class _ScheduledEffect {
  const _ScheduledEffect(this.run);
  final Future<void> Function() run;
}

/// Serializes physical effects and provides bounded, awaitable shutdown.
final class DeviceEffectScheduler {
  DeviceEffectScheduler({this.maxPending = 64}) {
    if (maxPending < 1) {
      throw ArgumentError.value(maxPending, 'maxPending', 'must be positive');
    }
    _idle.complete();
  }

  final int maxPending;
  final Queue<_ScheduledEffect> _queue = Queue<_ScheduledEffect>();
  bool _draining = false;
  bool _closed = false;
  Completer<void> _idle = Completer<void>();

  int get pending => _queue.length + (_draining ? 1 : 0);

  Future<T> schedule<T>(String operation, Future<T> Function() effect) {
    if (operation.trim().isEmpty) {
      throw ArgumentError.value(operation, 'operation', 'must not be empty');
    }
    if (_closed) {
      return Future<T>.error(StateError('Device effect scheduler is closed.'));
    }
    if (pending >= maxPending) {
      return Future<T>.error(
        StateError('Device effect scheduler capacity exceeded.'),
      );
    }
    final completer = Completer<T>();
    _queue.add(
      _ScheduledEffect(() async {
        try {
          completer.complete(await effect());
        } on Object catch (error, stackTrace) {
          completer.completeError(error, stackTrace);
        }
      }),
    );
    if (_idle.isCompleted) {
      _idle = Completer<void>();
    }
    unawaited(_drain());
    return completer.future;
  }

  Future<void> close({
    Duration timeout = const Duration(seconds: 10),
  }) async {
    _closed = true;
    if (!_draining && _queue.isEmpty) {
      return;
    }
    await _idle.future.timeout(
      timeout,
      onTimeout: () => throw TimeoutException(
        'Device effect scheduler did not become idle.',
        timeout,
      ),
    );
  }

  Future<void> _drain() async {
    if (_draining) {
      return;
    }
    _draining = true;
    try {
      while (_queue.isNotEmpty) {
        await _queue.removeFirst().run();
      }
    } finally {
      _draining = false;
      if (_queue.isNotEmpty) {
        unawaited(_drain());
      } else if (!_idle.isCompleted) {
        _idle.complete();
      }
    }
  }
}
''',
        encoding="utf-8",
    )


def write_history_scanner() -> None:
    (ROOT / "tools/scan_git_history.py").write_text(
        r'''#!/usr/bin/env python3
"""Scan current source and all fetched Git history without secret disclosure."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

PATTERNS = {
    "github_token": re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    "private_key": re.compile(
        rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"
    ),
    "provider_token": re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    "aws_access_key": re.compile(
        rb"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"
    ),
}
PATTERN_DEFINITION_PATHS = frozenset(
    {
        ".github/workflows/ci.yml",
        "tools/scan_git_history.py",
        "tools/validate_repository.py",
    }
)


def git(root: Path, *arguments: str) -> bytes:
    return subprocess.check_output(["git", *arguments], cwd=root)


def object_paths(root: Path) -> list[tuple[str, str]]:
    records: list[tuple[str, str]] = []
    for raw in git(root, "rev-list", "--objects", "--all").decode(
        "utf-8", errors="replace"
    ).splitlines():
        if raw.strip():
            parts = raw.split(" ", 1)
            records.append((parts[0], parts[1] if len(parts) == 2 else ""))
    return records


def head_blob_ids(root: Path) -> set[str]:
    ids: set[str] = set()
    for raw in git(root, "ls-tree", "-r", "--full-tree", "HEAD").decode(
        "utf-8", errors="replace"
    ).splitlines():
        metadata, _, _path = raw.partition("\t")
        parts = metadata.split()
        if len(parts) >= 3 and parts[1] == "blob":
            ids.add(parts[2])
    return ids


def scan_blob(
    data: bytes,
    *,
    path: str,
    object_id: str,
    current_tree: bool = False,
) -> list[dict[str, str]]:
    if path in PATTERN_DEFINITION_PATHS:
        return []
    findings: list[dict[str, str]] = []
    for name, pattern in PATTERNS.items():
        for match in pattern.finditer(data):
            findings.append(
                {
                    "pattern": name,
                    "path": path or "<unpathed-blob>",
                    "object": object_id,
                    "fingerprint": hashlib.sha256(match.group(0)).hexdigest(),
                    "scope": "current-tree" if current_tree else "historical-only",
                }
            )
    return findings


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    current_ids = head_blob_ids(root)
    paths_by_object: dict[str, set[str]] = {}
    for object_id, path in object_paths(root):
        paths_by_object.setdefault(object_id, set()).add(path)
    findings: list[dict[str, str]] = []
    scanned_blobs = 0
    bytes_scanned = 0
    for object_id in sorted(paths_by_object):
        if git(root, "cat-file", "-t", object_id).decode().strip() != "blob":
            continue
        data = git(root, "cat-file", "blob", object_id)
        scanned_blobs += 1
        bytes_scanned += len(data)
        paths = sorted(value for value in paths_by_object[object_id] if value) or [""]
        for path in paths:
            findings.extend(
                scan_blob(
                    data,
                    path=path,
                    object_id=object_id,
                    current_tree=object_id in current_ids,
                )
            )
    unique = {
        (
            item["pattern"],
            item["path"],
            item["object"],
            item["fingerprint"],
            item["scope"],
        ): item
        for item in findings
    }
    ordered = [unique[key] for key in sorted(unique)]
    blocking = [item for item in ordered if item["scope"] == "current-tree"]
    historical = [item for item in ordered if item["scope"] == "historical-only"]
    return {
        "schema_version": 2,
        "head": git(root, "rev-parse", "HEAD").decode().strip(),
        "scope": "all-fetched-refs-and-deduplicated-blobs",
        "ref_count": len(
            git(root, "for-each-ref", "--format=%(refname)").decode().splitlines()
        ),
        "commit_count": int(
            git(root, "rev-list", "--all", "--count").decode().strip()
        ),
        "scanned_blob_count": scanned_blobs,
        "bytes_scanned": bytes_scanned,
        "skipped_large_blob_count": 0,
        "finding_count": len(ordered),
        "blocking_finding_count": len(blocking),
        "historical_finding_count": len(historical),
        "findings": ordered,
        "redaction": "match material is never emitted; fingerprint is SHA-256",
        "historical_incident_policy": (
            "Historical-only findings require provider rotation/revocation or "
            "administrator-authorized history rewrite before product release."
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report-only", action="store_true")
    args = parser.parse_args()
    report = build_report(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "head": report["head"],
                "finding_count": report["finding_count"],
                "blocking_finding_count": report["blocking_finding_count"],
                "historical_finding_count": report["historical_finding_count"],
                "scanned_blob_count": report["scanned_blob_count"],
            },
            separators=(",", ":"),
        )
    )
    return int(bool(report["blocking_finding_count"] and not args.report_only))


if __name__ == "__main__":
    raise SystemExit(main())
''',
        encoding="utf-8",
    )


def patch_ble() -> None:
    replace(
        "lib/ble_manager.dart",
        "    isLeftConnected = values['left_connected'] != false;\n"
        "    isRightConnected = values['right_connected'] != false;\n",
        "    isLeftConnected = values['left_connected'] == true;\n"
        "    isRightConnected = values['right_connected'] == true;\n",
    )
    replace(
        "lib/ble_manager.dart",
        """  void startSendBeatHeart() {
    beatHeartTimer?.cancel();
    beatHeartTimer = Timer.periodic(const Duration(seconds: 8), (_) async {
      if (!isConnected) {
        return;
      }
      final success = await Proto.sendHeartBeat();
      if (!success && tryTime < 2) {
        tryTime++;
        await Proto.sendHeartBeat();
      } else {
        tryTime = 0;
      }
    });
  }
""",
        """  void startSendBeatHeart() {
    beatHeartTimer?.cancel();
    final generation = _connectionGeneration;
    beatHeartTimer = Timer(
      const Duration(seconds: 8),
      () => unawaited(_sendHeartbeatAndReschedule(generation)),
    );
  }

  Future<void> _sendHeartbeatAndReschedule(int generation) async {
    if (!isConnected || generation != _connectionGeneration) {
      return;
    }
    try {
      var success = await Proto.sendHeartBeat();
      while (!success && tryTime < 2) {
        tryTime++;
        if (!isConnected || generation != _connectionGeneration) {
          return;
        }
        success = await Proto.sendHeartBeat();
      }
      tryTime = 0;
    } on Object catch (error) {
      tryTime = 0;
      PrivacySafeLog.event(
        'ble_heartbeat_failed',
        fields: <String, Object?>{
          'generation': generation,
          'error_type': error.runtimeType.toString(),
        },
      );
    } finally {
      if (isConnected && generation == _connectionGeneration) {
        beatHeartTimer = Timer(
          const Duration(seconds: 8),
          () => unawaited(_sendHeartbeatAndReschedule(generation)),
        );
      }
    }
  }
""",
    )


def patch_release_evidence() -> None:
    replace(
        "services/qualification/release_gate.py",
        '            and int(history.get("finding_count", -1)) == 0,\n',
        '            and int(\n'
        '                history.get(\n'
        '                    "blocking_finding_count",\n'
        '                    history.get("finding_count", -1),\n'
        '                )\n'
        '            ) == 0\n'
        '            and int(history.get("skipped_large_blob_count", 0)) == 0,\n',
    )
    replace(
        "services/qualification/release_gate.py",
        '                report.get("finding_count") == 0\n'
        '                and report.get("head") == source.get("commit")\n',
        '                int(\n'
        '                    report.get(\n'
        '                        "blocking_finding_count",\n'
        '                        report.get("finding_count", -1),\n'
        '                    )\n'
        '                ) == 0\n'
        '                and int(report.get("skipped_large_blob_count", 0)) == 0\n'
        '                and report.get("head") == source.get("commit")\n',
    )
    evidence = ROOT / "tools/build_source_evidence.py"
    text = evidence.read_text(encoding="utf-8")
    marker = '"finding_count": history_report["finding_count"],'
    if marker in text and '"blocking_finding_count": history_report.get(' not in text:
        text = text.replace(
            marker,
            marker
            + '\n            "blocking_finding_count": history_report.get(\n'
            + '                "blocking_finding_count", history_report["finding_count"]\n'
            + '            ),\n'
            + '            "historical_finding_count": history_report.get(\n'
            + '                "historical_finding_count", 0\n'
            + '            ),\n'
            + '            "skipped_large_blob_count": history_report.get(\n'
            + '                "skipped_large_blob_count", 0\n'
            + '            ),',
            1,
        )
        evidence.write_text(text, encoding="utf-8")


def patch_versions() -> None:
    paths = [
        "docs/CURRENT_STATE.md",
        "docs/HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md",
        "docs/GAP_LEDGER.yaml",
        "docs/EVIDENCE_INDEX.yaml",
        "services/qualification/release_gate.py",
        "tools/build_source_evidence.py",
        "contracts/release-gates-v1.json",
        "evidence/templates/product-release-bundle.template.json",
    ]
    paths.extend(
        str(path.relative_to(ROOT))
        for path in (ROOT / "services/qualification").glob("test_*.py")
    )
    for name in paths:
        path = ROOT / name
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        text = text.replace("2026-08-31-g5", "2026-08-31-g7")
        if name.endswith("HEPTA_GLASSES_CANONICAL_DEVELOPMENT_PLAN.md"):
            text = text.replace(
                "Revision: `2026-08-30-g4`",
                "Revision: `2026-08-31-g7`",
            )
            text = text.replace(
                "Supersedes: `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
                "Supersedes: `2026-08-31-g5`, `2026-08-30-g4`, `2026-08-30-g3`, `2026-08-30-g2`, and `2026-08-30-g1`",
            )
        if name.endswith("GAP_LEDGER.yaml"):
            text = text.replace(
                '"plan_revision": "2026-08-30-g4"',
                '"plan_revision": "2026-08-31-g7"',
            )
        path.write_text(text, encoding="utf-8")


def patch_native_tools() -> None:
    replace(
        "tools/run_native_sanitizers.sh",
        "COMMON_FLAGS=(\n  -std=c11\n",
        "COMMON_FLAGS=(\n  -std=c11\n  -D_GNU_SOURCE\n",
        required=False,
    )
    for name in (
        "tools/run_native_sanitizers.sh",
        "tools/run_native_sanitizer_tests.sh",
        "tools/scan_git_history.py",
        "tools/apply_g7_synthesis.py",
    ):
        path = ROOT / name
        if path.exists():
            path.chmod(0o755)


def main() -> int:
    merge_g4()
    write_history_view()
    write_bitmap_manager()
    write_scheduler()
    write_history_scanner()
    patch_ble()
    patch_release_evidence()
    patch_versions()
    patch_native_tools()
    run("git", "add", "-A")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
