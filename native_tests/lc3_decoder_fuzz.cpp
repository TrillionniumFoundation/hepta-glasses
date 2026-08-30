#include <cstddef>
#include <cstdint>
#include <cstdlib>
#include <vector>

#include "lc3_decoder_core.h"
#include "include/lc3.h"

extern "C" int LLVMFuzzerTestOneInput(
    const std::uint8_t* data,
    std::size_t size
) {
    const std::vector<std::uint8_t> decoded =
        hepta::audio::decodeLc3Payload(data, size);
    if (!decoded.empty()) {
        const int samplesPerFrame = lc3_frame_samples(
            hepta::audio::kFrameDurationUs,
            hepta::audio::kSampleRateHz
        );
        if (
            samplesPerFrame <= 0 ||
            !hepta::audio::isValidLc3PayloadLength(size)
        ) {
            std::abort();
        }
        const std::size_t expected =
            (size / hepta::audio::kEncodedFrameBytes) *
            static_cast<std::size_t>(samplesPerFrame) *
            sizeof(std::int16_t);
        if (decoded.size() != expected) {
            std::abort();
        }
    }
    return 0;
}
