#pragma once

#include <Arduino.h>
#include <Preferences.h>

#include <cstddef>
#include <cstdint>

namespace rainpoint {

// Hardware trial only. This class is excluded from normal firmware until the
// signed-manifest path and rollback behavior have passed on a disposable node.
class OtaTrial {
public:
    void begin();
    bool install(
        const String& commandId,
        const String& url,
        const String& version,
        const String& expectedSha256,
        std::size_t expectedSize,
        const String& gatewayHost
    );
    void confirmHealthy(bool gatewayAuthenticated, bool radioHealthy);
    String status(const String& nodeId) const;
    bool restartPending() const { return restartPending_; }

private:
    static constexpr std::uint8_t kMaximumUnconfirmedBoots = 3;
    static constexpr std::uint32_t kHealthyConfirmationDelayMs = 60'000;

    void savePending(const String& version);
    void clearPending();
    bool validateRequest(
        const String& url,
        const String& version,
        const String& expectedSha256,
        std::size_t expectedSize,
        const String& gatewayHost
    );
    void fail(const char* detail);

    Preferences preferences_;
    String commandId_;
    String candidateVersion_;
    String state_ = "idle";
    String detail_ = "none";
    std::size_t receivedBytes_ = 0;
    std::size_t totalBytes_ = 0;
    std::uint8_t bootAttempts_ = 0;
    bool candidatePending_ = false;
    bool restartPending_ = false;
};

}  // namespace rainpoint
