#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "lc3.h"

static uint64_t digest_bytes(uint64_t value, const void *data, size_t size) {
  const uint8_t *bytes = (const uint8_t *)data;
  for (size_t index = 0; index < size; ++index) {
    value ^= bytes[index];
    value *= UINT64_C(1099511628211);
  }
  return value;
}

int main(void) {
  const int duration_us = 10000;
  const int sample_rate_hz = 16000;
  const int encoded_bytes = 20;
  const int samples = lc3_frame_samples(duration_us, sample_rate_hz);
  const unsigned decoder_size = lc3_decoder_size(duration_us, sample_rate_hz);
  if (samples <= 0 || decoder_size == 0) {
    return 10;
  }
  void *memory = calloc(1, decoder_size);
  if (memory == NULL) {
    return 11;
  }
  lc3_decoder_t decoder = lc3_setup_decoder(
      duration_us, sample_rate_hz, 0, memory);
  if (decoder == NULL) {
    free(memory);
    return 12;
  }

  uint8_t encoded[3][20];
  memset(encoded[0], 0, sizeof(encoded[0]));
  for (size_t index = 0; index < sizeof(encoded[1]); ++index) {
    encoded[1][index] = (uint8_t)(index * 13U + 7U);
  }
  memset(encoded[2], 0xff, sizeof(encoded[2]));

  int16_t *pcm = (int16_t *)calloc((size_t)samples, sizeof(int16_t));
  if (pcm == NULL) {
    free(memory);
    return 13;
  }
  uint64_t digest = UINT64_C(1469598103934665603);
  for (size_t frame = 0; frame < 3; ++frame) {
    memset(pcm, 0, (size_t)samples * sizeof(int16_t));
    const int result = lc3_decode(
        decoder,
        encoded[frame],
        encoded_bytes,
        LC3_PCM_FORMAT_S16,
        pcm,
        1);
    if (result < 0) {
      free(pcm);
      free(memory);
      return 20;
    }
    digest = digest_bytes(digest, pcm, (size_t)samples * sizeof(int16_t));
  }
  printf("%016llx\n", (unsigned long long)digest);
  free(pcm);
  free(memory);
  return 0;
}
