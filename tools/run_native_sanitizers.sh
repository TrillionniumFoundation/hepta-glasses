#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUTPUT="${1:-$ROOT/build/evidence/source-native-sanitizer.json}"
BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
CC_BIN="${CC:-clang}"

COMMON_FLAGS=(
  -std=c11
  -O1
  -g
  -fno-omit-frame-pointer
  -fsanitize=address,undefined
  -fno-sanitize-recover=all
  -Wall
  -Wextra
  -Wno-unused-parameter
)

compile_lc3() {
  local label="$1"
  local include_dir="$2"
  local source_dir="$3"
  local binary="$BUILD/$label"
  mapfile -t sources < <(find "$source_dir" -maxdepth 1 -type f -name '*.c' | sort)
  "$CC_BIN" "${COMMON_FLAGS[@]}" \
    -I"$include_dir" -I"$source_dir" \
    "$ROOT/tools/native/lc3_sanitizer_harness.c" \
    "${sources[@]}" -lm -o "$binary"
  ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
    UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
    "$binary"
}

android_digest="$(compile_lc3 \
  android-lc3 \
  "$ROOT/android/app/src/main/cpp/include" \
  "$ROOT/android/app/src/main/cpp/liblc3")"
ios_digest="$(compile_lc3 \
  ios-lc3 \
  "$ROOT/ios/Runner/lc3" \
  "$ROOT/ios/Runner/lc3")"

mapfile -t rnnoise_sources < <(
  find "$ROOT/android/app/src/main/cpp/rnnoise" \
    -maxdepth 1 -type f -name '*.c' ! -name 'rnn_reader.c' | sort
)
"$CC_BIN" "${COMMON_FLAGS[@]}" \
  -I"$ROOT/android/app/src/main/cpp/rnnoise" \
  -I"$ROOT/android/app/src/main/cpp/include" \
  "$ROOT/tools/native/rnnoise_sanitizer_harness.c" \
  "${rnnoise_sources[@]}" -lm -o "$BUILD/rnnoise"
ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
  UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  "$BUILD/rnnoise" >/dev/null

if [[ "$android_digest" != "$ios_digest" ]]; then
  echo "Android/iOS LC3 parity mismatch" >&2
  exit 1
fi
mkdir -p "$(dirname "$OUTPUT")"
python3 - "$OUTPUT" "$android_digest" "$ios_digest" <<'PYCODE'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
document = {
    "schema_version": 1,
    "sanitizers": ["address", "undefined"],
    "android_lc3": {"passed": True, "pcm_digest": sys.argv[2]},
    "ios_lc3": {"passed": True, "pcm_digest": sys.argv[3]},
    "lc3_cross_platform_parity": sys.argv[2] == sys.argv[3],
    "rnnoise": {"passed": True},
    "passed": True,
}
path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
print(json.dumps(document, separators=(",", ":")))
PYCODE
