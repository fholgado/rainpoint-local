#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

namespace rainpoint {

constexpr std::size_t kFrameBytes = 38;
constexpr std::size_t kHardwareSyncBytes = 2;
constexpr std::size_t kRadioPayloadBytes = kFrameBytes - kHardwareSyncBytes;
constexpr std::array<std::uint8_t, 5> kSync = {0x79, 0xf4, 0x88, 0x2f, 0x28};

inline std::uint16_t crcCcittZero(
    const std::uint8_t* data,
    std::size_t length
) {
    std::uint16_t crc = 0;
    for (std::size_t index = 0; index < length; ++index) {
        crc ^= static_cast<std::uint16_t>(data[index]) << 8;
        for (std::uint8_t bit = 0; bit < 8; ++bit) {
            crc = static_cast<std::uint16_t>(
                (crc & 0x8000) ? (crc << 1) ^ 0x1021 : crc << 1
            );
        }
    }
    return crc;
}

inline bool hasSync(const std::array<std::uint8_t, kFrameBytes>& frame) {
    for (std::size_t index = 0; index < kSync.size(); ++index) {
        if (frame[index] != kSync[index]) {
            return false;
        }
    }
    return true;
}

inline std::uint16_t trailerResidual(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    const auto computed = crcCcittZero(frame.data(), kFrameBytes - 2);
    const auto observed = static_cast<std::uint16_t>(
        static_cast<std::uint16_t>(frame[kFrameBytes - 2]) << 8
        | frame[kFrameBytes - 1]
    );
    return computed ^ observed;
}

inline bool hasOrdinaryTrailer(
    const std::array<std::uint8_t, kFrameBytes>& frame
) {
    const auto residual = trailerResidual(frame);
    return residual == 0xc713 || residual == 0x4f03;
}

inline void writeTrailer(
    std::array<std::uint8_t, kFrameBytes>& frame,
    std::uint16_t residual
) {
    const auto computed = crcCcittZero(frame.data(), kFrameBytes - 2);
    const auto trailer = static_cast<std::uint16_t>(computed ^ residual);
    frame[kFrameBytes - 2] = static_cast<std::uint8_t>(trailer >> 8);
    frame[kFrameBytes - 1] = static_cast<std::uint8_t>(trailer & 0xff);
}

inline std::array<std::uint8_t, kFrameBytes> reconstructFrame(
    const std::array<std::uint8_t, kRadioPayloadBytes>& payload
) {
    std::array<std::uint8_t, kFrameBytes> frame{};
    frame[0] = kSync[0];
    frame[1] = kSync[1];
    for (std::size_t index = 0; index < payload.size(); ++index) {
        frame[index + kHardwareSyncBytes] = payload[index];
    }
    return frame;
}

inline bool prepareRadioPayload(
    const std::array<std::uint8_t, kFrameBytes>& frame,
    std::array<std::uint8_t, kRadioPayloadBytes>& payload
) {
    if (!hasSync(frame) || !hasOrdinaryTrailer(frame)) {
        return false;
    }
    for (std::size_t index = 0; index < payload.size(); ++index) {
        payload[index] = frame[index + kHardwareSyncBytes];
    }
    return true;
}

}  // namespace rainpoint
