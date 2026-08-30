#include <cassert>
#include <cstddef>
#include <cstdint>
#include <vector>

#include "lc3_decoder_core.h"
#include "include/lc3.h"

namespace {

std::uint32_t nextRandom(std::uint32_t& state) {
    state ^= state << 13;
    state ^= state >> 17;
    state ^= state << 5;
    return state;
}

void assertResultShape(
    const std::vector<std::uint8_t>& decoded,
    std::size_t encodedLength
) {
    if (decoded.empty()) {
        return;
    }
    const int samplesPerFrame = lc3_frame_samples(
        hepta::audio::kFrameDurationUs,
        hepta::audio::kSampleRateHz
    );
    assert(samplesPerFrame > 0);
    const std::size_t expected =
        (encodedLength / hepta::audio::kEncodedFrameBytes) *
        static_cast<std::size_t>(samplesPerFrame) *
        sizeof(std::int16_t);
    assert(decoded.size() == expected);
}

}  // namespace

int main() {
    using hepta::audio::decodeLc3Payload;
    using hepta::audio::isValidLc3PayloadLength;

    assert(!isValidLc3PayloadLength(0));
    assert(!isValidLc3PayloadLength(19));
    assert(isValidLc3PayloadLength(20));
    assert(!isValidLc3PayloadLength(21));
    assert(isValidLc3PayloadLength(4000));
    assert(!isValidLc3PayloadLength(4100));

    assert(decodeLc3Payload(nullptr, 20).empty());
    const std::vector<std::uint8_t> empty;
    assert(decodeLc3Payload(empty.data(), empty.size()).empty());

    for (std::size_t length : {1U, 19U, 21U, 4097U, 4100U}) {
        std::vector<std::uint8_t> input(length, 0);
        assert(decodeLc3Payload(input.data(), input.size()).empty());
    }

    std::uint32_t state = 0x6a09e667U;
    for (int iteration = 0; iteration < 2000; iteration++) {
        const std::size_t frames =
            static_cast<std::size_t>((nextRandom(state) % 200U) + 1U);
        const std::size_t length =
            frames * hepta::audio::kEncodedFrameBytes;
        std::vector<std::uint8_t> input(length);
        for (auto& byte : input) {
            byte = static_cast<std::uint8_t>(nextRandom(state));
        }
        const auto decoded =
            decodeLc3Payload(input.data(), input.size());
        assertResultShape(decoded, input.size());
    }

    return 0;
}
