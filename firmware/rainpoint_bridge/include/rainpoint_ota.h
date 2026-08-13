#pragma once

#include <cstdint>

namespace rainpoint {

constexpr std::uint8_t kMaximumUnconfirmedBoots = 3;

struct OtaBootState {
    std::uint8_t unconfirmedBoots = 0;
    bool candidatePending = false;
    bool gatewayConfirmed = false;
};

inline void beginOtaCandidate(OtaBootState& state) {
    state.unconfirmedBoots = 0;
    state.candidatePending = true;
    state.gatewayConfirmed = false;
}

inline void recordCandidateBoot(OtaBootState& state) {
    if (state.candidatePending && !state.gatewayConfirmed &&
        state.unconfirmedBoots < 0xff) {
        ++state.unconfirmedBoots;
    }
}

inline bool shouldRollback(const OtaBootState& state) {
    return state.candidatePending && !state.gatewayConfirmed &&
           state.unconfirmedBoots >= kMaximumUnconfirmedBoots;
}

inline void confirmCandidate(OtaBootState& state) {
    state.candidatePending = false;
    state.gatewayConfirmed = true;
    state.unconfirmedBoots = 0;
}

}  // namespace rainpoint
