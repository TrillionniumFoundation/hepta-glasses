#include <math.h>
#include <stddef.h>
#include <stdio.h>

#include "rnnoise.h"

int main(void) {
  DenoiseState *state = rnnoise_create(NULL);
  if (state == NULL) {
    return 10;
  }
  float input[480];
  float output[480];
  for (size_t index = 0; index < 480; ++index) {
    input[index] = (float)((int)(index % 17) - 8) * 4.0f;
    output[index] = 0.0f;
  }
  const float probability = rnnoise_process_frame(state, output, input);
  if (!isfinite(probability)) {
    rnnoise_destroy(state);
    return 11;
  }
  for (size_t index = 0; index < 480; ++index) {
    if (!isfinite(output[index])) {
      rnnoise_destroy(state);
      return 12;
    }
  }
  rnnoise_destroy(state);
  puts("rnnoise-ok");
  return 0;
}
