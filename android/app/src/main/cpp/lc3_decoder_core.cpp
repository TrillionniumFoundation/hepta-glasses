#include "lc3_decoder_core.h"

#include <algorithm>
#include <cstring>
#include <limits>
#include <new>

#include "include/lc3.h"

namespace hepta::audio {

bool isValidLc3PayloadLength(std::size_t encodedLength) noexcept {
    return encodedLength > 0 &&
        encodedLength <= kMaximumEncodedPayloadBytes &&
        encodedLength % kEncodedFrameBytes == 0;
}

std::vector<std::uint8_t> decodeLc3Payload(
    const std::uint8_t* encoded,
    std::size_t encodedLength
) noexcept {
    if (encoded == nullptr || !isValidLc3PayloadLength(encodedLength)) {
        return {};
    }

    try {
        const unsigned decoderSize =
            lc3_decoder_size(kFrameDurationUs, kSampleRateHz);
        const int samplesPerFrame =
            lc3_frame_samples(kFrameDurationUs, kSampleRateHz);
        if (decoderSize == 0 || samplesPerFrame <= 0) {
            return {};
        }

        const std::size_t frameCount =
            encodedLength / kEncodedFrameBytes;
        const std::size_t decodedFrameBytes =
            static_cast<std::size_t>(samplesPerFrame) *
            sizeof(std::int16_t);
        if (
            decodedFrameBytes == 0 ||
            frameCount >
                std::numeric_limits<std::size_t>::max() /
                    decodedFrameBytes
        ) {
            return {};
        }
        const std::size_t decodedLength =
            frameCount * decodedFrameBytes;

        std::vector<std::uint8_t> decoderMemory(decoderSize, 0);
        std::vector<std::int16_t> frameBuffer(
            static_cast<std::size_t>(samplesPerFrame),
            0
        );
        std::vector<std::uint8_t> decoded(decodedLength, 0);
        lc3_decoder_t decoder = lc3_setup_decoder(
            kFrameDurationUs,
            kSampleRateHz,
            0,
            decoderMemory.data()
        );
        if (decoder == nullptr) {
            return {};
        }

        for (std::size_t frame = 0; frame < frameCount; frame++) {
            const auto* input =
                encoded + frame * kEncodedFrameBytes;
            const int status = lc3_decode(
                decoder,
                input,
                static_cast<int>(kEncodedFrameBytes),
                LC3_PCM_FORMAT_S16,
                frameBuffer.data(),
                1
            );
            if (status < 0) {
                return {};
            }
            std::memcpy(
                decoded.data() + frame * decodedFrameBytes,
                frameBuffer.data(),
                decodedFrameBytes
            );
            std::fill(
                frameBuffer.begin(),
                frameBuffer.end(),
                static_cast<std::int16_t>(0)
            );
        }
        return decoded;
    } catch (const std::bad_alloc&) {
        return {};
    } catch (...) {
        return {};
    }
}

}  // namespace hepta::audio
