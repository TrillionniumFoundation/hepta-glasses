#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_ROOT="$ROOT/android/app/src/main/cpp"
TEST_ROOT="$ROOT/native_tests"
BUILD_ROOT="$ROOT/build/native-sanitizers"

: "${CC:=clang}"
: "${CXX:=clang++}"
command -v "$CC" >/dev/null
command -v "$CXX" >/dev/null

rm -rf "$BUILD_ROOT"
mkdir -p "$BUILD_ROOT/objects"

SANITIZER_FLAGS=(
  -O1
  -g
  -fno-omit-frame-pointer
  -fsanitize=address,undefined
)
INCLUDES=(
  "-I$SOURCE_ROOT"
  "-I$SOURCE_ROOT/include"
  "-I$SOURCE_ROOT/liblc3"
)
LC3_SOURCES=(
  attdet.c
  bits.c
  bwdet.c
  energy.c
  lc3.c
  ltpf.c
  mdct.c
  plc.c
  sns.c
  spec.c
  tables.c
  tns.c
)

objects=()
for source in "${LC3_SOURCES[@]}"; do
  object="$BUILD_ROOT/objects/${source%.c}.o"
  "$CC" \
    -std=gnu11 \
    -w \
    "${SANITIZER_FLAGS[@]}" \
    "${INCLUDES[@]}" \
    -c "$SOURCE_ROOT/liblc3/$source" \
    -o "$object"
  objects+=("$object")
done

"$CXX" \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  "${SANITIZER_FLAGS[@]}" \
  "${INCLUDES[@]}" \
  -c "$SOURCE_ROOT/lc3_decoder_core.cpp" \
  -o "$BUILD_ROOT/objects/lc3_decoder_core.o"
objects+=("$BUILD_ROOT/objects/lc3_decoder_core.o")

"$CXX" \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  "${SANITIZER_FLAGS[@]}" \
  "${INCLUDES[@]}" \
  "$TEST_ROOT/lc3_decoder_core_test.cpp" \
  "${objects[@]}" \
  -lm \
  -o "$BUILD_ROOT/lc3_decoder_core_test"

ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  "$BUILD_ROOT/lc3_decoder_core_test"

"$CXX" \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  -O1 \
  -g \
  -fno-omit-frame-pointer \
  -fsanitize=fuzzer,address,undefined \
  "${INCLUDES[@]}" \
  "$TEST_ROOT/lc3_decoder_fuzz.cpp" \
  "${objects[@]}" \
  -lm \
  -o "$BUILD_ROOT/lc3_decoder_fuzz"

ASAN_OPTIONS=detect_leaks=1:halt_on_error=1 \
UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
  "$BUILD_ROOT/lc3_decoder_fuzz" \
    -runs=2000 \
    -max_len=4100 \
    -print_final_stats=1
