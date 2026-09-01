#pragma once

#include <cstdint>

namespace rainpoint {

enum class RfOperatingMode : std::uint8_t {
    Normal,
    ReceiveOnly,
};

class RfMaintenanceState {
public:
    static constexpr std::uint32_t kMinimumReceiveOnlySeconds = 60;
    static constexpr std::uint32_t kMaximumReceiveOnlySeconds = 3'600;

    bool enterReceiveOnly(
        std::uint32_t nowMs,
        std::uint32_t durationSeconds
    ) {
        if (durationSeconds < kMinimumReceiveOnlySeconds ||
            durationSeconds > kMaximumReceiveOnlySeconds) {
            return false;
        }
        mode_ = RfOperatingMode::ReceiveOnly;
        changedAtMs_ = nowMs;
        expiresAtMs_ = nowMs + durationSeconds * 1'000U;
        return true;
    }

    void resumeNormal(std::uint32_t nowMs) {
        mode_ = RfOperatingMode::Normal;
        changedAtMs_ = nowMs;
        expiresAtMs_ = 0;
    }

    bool tick(std::uint32_t nowMs) {
        if (mode_ != RfOperatingMode::ReceiveOnly ||
            static_cast<std::int32_t>(nowMs - expiresAtMs_) < 0) {
            return false;
        }
        resumeNormal(nowMs);
        return true;
    }

    RfOperatingMode mode() const {
        return mode_;
    }

    bool transmitAllowed() const {
        return mode_ == RfOperatingMode::Normal;
    }

    std::uint32_t remainingSeconds(std::uint32_t nowMs) const {
        if (mode_ != RfOperatingMode::ReceiveOnly ||
            static_cast<std::int32_t>(nowMs - expiresAtMs_) >= 0) {
            return 0;
        }
        const std::uint32_t remainingMs = expiresAtMs_ - nowMs;
        return (remainingMs + 999U) / 1'000U;
    }

    std::uint32_t changedAtMs() const {
        return changedAtMs_;
    }

private:
    RfOperatingMode mode_ = RfOperatingMode::Normal;
    std::uint32_t changedAtMs_ = 0;
    std::uint32_t expiresAtMs_ = 0;
};

}  // namespace rainpoint
