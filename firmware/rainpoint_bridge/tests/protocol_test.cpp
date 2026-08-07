#include <array>
#include <cassert>
#include <cstdint>
#include <string>

#include "rainpoint_protocol.h"

namespace {

std::array<std::uint8_t, rainpoint::kFrameBytes> fromHex(
    const std::string& value
) {
    assert(value.size() == rainpoint::kFrameBytes * 2);
    std::array<std::uint8_t, rainpoint::kFrameBytes> result{};
    for (std::size_t index = 0; index < result.size(); ++index) {
        result[index] = static_cast<std::uint8_t>(
            std::stoul(value.substr(index * 2, 2), nullptr, 16)
        );
    }
    return result;
}
}  // namespace

int main() {
    const auto heartbeat = fromHex(
        "79f4882f28c4e500243984028088c181000100000000000000000000000000000000000022e3"
    );
    assert(rainpoint::hasSync(heartbeat));
    assert(rainpoint::trailerResidual(heartbeat) == 0xc713);
    assert(rainpoint::hasOrdinaryTrailer(heartbeat));

    std::array<std::uint8_t, rainpoint::kRadioPayloadBytes> payload{};
    for (std::size_t index = 0; index < payload.size(); ++index) {
        payload[index] = heartbeat[index + rainpoint::kHardwareSyncBytes];
    }
    assert(rainpoint::reconstructFrame(payload) == heartbeat);

    auto corrupt = heartbeat;
    corrupt[20] ^= 0x01;
    assert(!rainpoint::hasOrdinaryTrailer(corrupt));
    return 0;
}
