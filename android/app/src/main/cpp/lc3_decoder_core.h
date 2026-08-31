#pragma once

#include <cstddef>
#include <cstdint>
#include <vector>

namespace hepta::audio {

inline constexpr int kFrameDurationUs = 10000;
inline constexpr int kSampleRateHz = 16000;
inline constexpr std::size_t kEncodedFrameBytes = 20;
inline constexpr std::size_t kMaximumEncodedPayloadBytes = 4096;

[[nodiscard]] bool isValidLc3PayloadLength(std::size_t encodedLength) noexcept;

[[nodiscard]] std::vector<std::uint8_t> decodeLc3Payload(
    const std::uint8_t* encoded,
    std::size_t encodedLength
) noexcept;

}  // namespace hepta::audio
