#include "ota_trial.h"

#if RAINPOINT_OTA_CANDIDATE == 1

#include <HTTPClient.h>
#include <Update.h>
#include <esp_system.h>
#include <mbedtls/sha256.h>

#include <array>
#include <cctype>

namespace rainpoint {
namespace {

bool validHexDigest(const String& value) {
    if (value.length() != 64) {
        return false;
    }
    for (std::size_t index = 0; index < value.length(); ++index) {
        if (!std::isxdigit(static_cast<unsigned char>(value[index]))) {
            return false;
        }
    }
    return true;
}

bool validVersion(const String& value) {
    if (value.isEmpty() || value.length() > 48) {
        return false;
    }
    for (std::size_t index = 0; index < value.length(); ++index) {
        const char character = value[index];
        if (!(std::isalnum(static_cast<unsigned char>(character)) ||
              character == '.' || character == '-' || character == '+')) {
            return false;
        }
    }
    return true;
}

String digestHex(const std::array<unsigned char, 32>& digest) {
    constexpr char digits[] = "0123456789abcdef";
    String result;
    result.reserve(64);
    for (const unsigned char value : digest) {
        result += digits[value >> 4];
        result += digits[value & 0x0f];
    }
    return result;
}

}  // namespace

void OtaTrial::begin() {
    preferences_.begin("rainpoint-ota", true);
    candidatePending_ = preferences_.getBool("pending", false);
    candidateVersion_ = preferences_.getString("version", "");
    bootAttempts_ = preferences_.getUChar("attempts", 0);
    preferences_.end();
    if (!candidatePending_) {
        return;
    }
    if (bootAttempts_ < 0xff) {
        ++bootAttempts_;
    }
    preferences_.begin("rainpoint-ota", false);
    preferences_.putUChar("attempts", bootAttempts_);
    preferences_.end();
    state_ = "awaiting_health_confirmation";
    detail_ = "candidate_boot";
    if (bootAttempts_ < kMaximumUnconfirmedBoots) {
        return;
    }
    state_ = "rolling_back";
    detail_ = "maximum_unconfirmed_boots";
    if (Update.canRollBack() && Update.rollBack()) {
        clearPending();
        delay(100);
        ESP.restart();
    }
    state_ = "failed";
    detail_ = "rollback_partition_unavailable";
}

bool OtaTrial::validateRequest(
    const String& url,
    const String& version,
    const String& expectedSha256,
    std::size_t expectedSize,
    const String& gatewayHost
) {
    if (!validVersion(version) || !validHexDigest(expectedSha256)) {
        return false;
    }
    if (expectedSize < 64 * 1024 || expectedSize > 2 * 1024 * 1024) {
        return false;
    }
    const String requiredPrefix = String("http://") + gatewayHost + ":";
    return !gatewayHost.isEmpty() && url.startsWith(requiredPrefix) &&
           url.length() <= 320 && url.indexOf(' ') < 0;
}

bool OtaTrial::install(
    const String& commandId,
    const String& url,
    const String& version,
    const String& expectedSha256,
    std::size_t expectedSize,
    const String& gatewayHost
) {
    commandId_ = commandId;
    receivedBytes_ = 0;
    totalBytes_ = expectedSize;
    restartPending_ = false;
    if (candidatePending_ || state_ == "downloading") {
        fail("update_already_pending");
        return false;
    }
    if (!validateRequest(
            url, version, expectedSha256, expectedSize, gatewayHost
        )) {
        fail("invalid_update_request");
        return false;
    }

    WiFiClient downloadClient;
    HTTPClient request;
    request.setConnectTimeout(5'000);
    request.setTimeout(10'000);
    if (!request.begin(downloadClient, url)) {
        fail("download_initialization_failed");
        return false;
    }
    state_ = "downloading";
    detail_ = "none";
    const int response = request.GET();
    if (response != HTTP_CODE_OK || request.getSize() != expectedSize) {
        request.end();
        fail("download_metadata_mismatch");
        return false;
    }
    if (!Update.begin(expectedSize, U_FLASH)) {
        request.end();
        fail("ota_partition_unavailable");
        return false;
    }

    mbedtls_sha256_context sha;
    mbedtls_sha256_init(&sha);
    if (mbedtls_sha256_starts_ret(&sha, 0) != 0) {
        Update.abort();
        request.end();
        mbedtls_sha256_free(&sha);
        fail("sha256_initialization_failed");
        return false;
    }
    WiFiClient* stream = request.getStreamPtr();
    std::array<std::uint8_t, 1024> buffer{};
    std::uint32_t lastProgressAt = millis();
    bool success = true;
    while (receivedBytes_ < expectedSize) {
        const int available = stream->available();
        if (available <= 0) {
            if (!request.connected() || millis() - lastProgressAt > 10'000) {
                success = false;
                detail_ = "download_interrupted";
                break;
            }
            delay(1);
            continue;
        }
        const std::size_t remaining = expectedSize - receivedBytes_;
        const std::size_t requested = min(
            static_cast<std::size_t>(available),
            min(buffer.size(), remaining)
        );
        const int read = stream->readBytes(buffer.data(), requested);
        if (read <= 0 ||
            mbedtls_sha256_update_ret(&sha, buffer.data(), read) != 0 ||
            Update.write(buffer.data(), read) != static_cast<std::size_t>(read)) {
            success = false;
            detail_ = "flash_write_failed";
            break;
        }
        receivedBytes_ += static_cast<std::size_t>(read);
        lastProgressAt = millis();
    }
    std::array<unsigned char, 32> digest{};
    if (success && mbedtls_sha256_finish_ret(&sha, digest.data()) != 0) {
        success = false;
        detail_ = "sha256_finalization_failed";
    }
    mbedtls_sha256_free(&sha);
    request.end();
    if (!success || receivedBytes_ != expectedSize ||
        !digestHex(digest).equalsIgnoreCase(expectedSha256)) {
        Update.abort();
        if (success) {
            detail_ = "sha256_mismatch";
        }
        state_ = "failed";
        return false;
    }
    if (!Update.end(false)) {
        fail("firmware_validation_failed");
        return false;
    }
    savePending(version);
    state_ = "ready_to_reboot";
    detail_ = "verified_sha256";
    restartPending_ = true;
    return true;
}

void OtaTrial::savePending(const String& version) {
    preferences_.begin("rainpoint-ota", false);
    preferences_.putBool("pending", true);
    preferences_.putString("version", version);
    preferences_.putUChar("attempts", 0);
    preferences_.end();
    candidatePending_ = true;
    candidateVersion_ = version;
    bootAttempts_ = 0;
}

void OtaTrial::clearPending() {
    preferences_.begin("rainpoint-ota", false);
    preferences_.remove("pending");
    preferences_.remove("version");
    preferences_.remove("attempts");
    preferences_.end();
    candidatePending_ = false;
    candidateVersion_.clear();
    bootAttempts_ = 0;
}

void OtaTrial::confirmHealthy(bool gatewayAuthenticated, bool radioHealthy) {
    if (!candidatePending_ || millis() < kHealthyConfirmationDelayMs ||
        !gatewayAuthenticated || !radioHealthy) {
        return;
    }
    clearPending();
    state_ = "confirmed";
    detail_ = "gateway_and_radio_healthy";
}

void OtaTrial::fail(const char* detail) {
    state_ = "failed";
    detail_ = detail;
}

String OtaTrial::status(const String& nodeId) const {
    String line = "{\"type\":\"firmware_update_status\",\"node_id\":\"";
    line += nodeId;
    line += "\",\"command_id\":\"";
    line += commandId_;
    line += "\",\"state\":\"";
    line += state_;
    line += "\",\"detail\":\"";
    line += detail_;
    line += "\",\"candidate_version\":\"";
    line += candidateVersion_;
    line += "\",\"received_bytes\":";
    line += static_cast<unsigned long>(receivedBytes_);
    line += ",\"total_bytes\":";
    line += static_cast<unsigned long>(totalBytes_);
    line += ",\"boot_attempts\":";
    line += bootAttempts_;
    line += ",\"candidate_pending\":";
    line += candidatePending_ ? "true" : "false";
    line += "}";
    return line;
}

}  // namespace rainpoint

#endif  // RAINPOINT_OTA_CANDIDATE == 1
