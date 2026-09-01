#include "wifi_transport.h"

#include <Esp.h>
#include <esp_system.h>
#include <mbedtls/md.h>

#include <array>
#include <cctype>

#ifndef RAINPOINT_FIRMWARE_VERSION
#define RAINPOINT_FIRMWARE_VERSION "development"
#endif

namespace rainpoint {
namespace {

String stableNodeId() {
    const std::uint64_t identifier = ESP.getEfuseMac();
    char buffer[16];
    std::snprintf(
        buffer,
        sizeof(buffer),
        "rp-%04x%08x",
        static_cast<unsigned int>((identifier >> 32) & 0xffff),
        static_cast<unsigned int>(identifier & 0xffffffff)
    );
    return String(buffer);
}

String jsonString(const String& input, const char* key) {
    const String marker = String('"') + key + "\":\"";
    const int start = input.indexOf(marker);
    if (start < 0) {
        return String();
    }
    const int valueStart = start + marker.length();
    const int end = input.indexOf('"', valueStart);
    return end < 0 ? String() : input.substring(valueStart, end);
}

bool validHexToken(const String& token) {
    if (token.length() != 64) {
        return false;
    }
    for (std::size_t index = 0; index < token.length(); ++index) {
        if (!std::isxdigit(static_cast<unsigned char>(token[index]))) {
            return false;
        }
    }
    return true;
}

bool validHost(const String& host) {
    if (host.isEmpty() || host.length() > 253) {
        return false;
    }
    for (std::size_t index = 0; index < host.length(); ++index) {
        const char value = host[index];
        if (!(std::isalnum(static_cast<unsigned char>(value)) ||
              value == '.' || value == '-')) {
            return false;
        }
    }
    return true;
}

String hmacProof(
    const String& token,
    const String& nonce,
    const String& nodeId,
    const char* domain
) {
    const String message =
        String(domain) + "\n" + nonce + "\n" + nodeId;
    std::array<unsigned char, 32> digest{};
    const mbedtls_md_info_t* info =
        mbedtls_md_info_from_type(MBEDTLS_MD_SHA256);
    if (info == nullptr ||
        mbedtls_md_hmac(
            info,
            reinterpret_cast<const unsigned char*>(token.c_str()),
            token.length(),
            reinterpret_cast<const unsigned char*>(message.c_str()),
            message.length(),
            digest.data()
        ) != 0) {
        return String();
    }
    constexpr char digits[] = "0123456789abcdef";
    String output;
    output.reserve(digest.size() * 2);
    for (const unsigned char value : digest) {
        output += digits[value >> 4];
        output += digits[value & 0x0f];
    }
    return output;
}

bool constantTimeEqual(const String& left, const String& right) {
    if (left.length() != right.length()) {
        return false;
    }
    unsigned char difference = 0;
    for (std::size_t index = 0; index < left.length(); ++index) {
        difference |= static_cast<unsigned char>(left[index] ^ right[index]);
    }
    return difference == 0;
}

}  // namespace

void WifiTransport::begin() {
    nodeId_ = stableNodeId();
    loadConfiguration();
    ensureSetupToken();
    commissioningPortal_.begin(nodeId_, wifiConfigured_, configured_);
    if (wifiConfigured_) {
        startWifi();
    } else {
        reportNetworkState("unconfigured");
    }
}

void WifiTransport::ensureSetupToken() {
    if (validHexToken(token_)) {
        return;
    }
    std::array<unsigned char, 32> random{};
    esp_fill_random(random.data(), random.size());
    constexpr char digits[] = "0123456789abcdef";
    token_.clear();
    token_.reserve(random.size() * 2);
    for (const unsigned char value : random) {
        token_ += digits[value >> 4];
        token_ += digits[value & 0x0f];
    }
    preferences_.begin("rainpoint", false);
    preferences_.putString("token", token_);
    preferences_.end();
    loadConfiguration();
}

void WifiTransport::loadConfiguration() {
    preferences_.begin("rainpoint", true);
    ssid_ = preferences_.getString("ssid", "");
    password_ = preferences_.getString("password", "");
    gatewayHost_ = preferences_.getString("host", "");
    gatewayPort_ = preferences_.getUShort("port", 8790);
    token_ = preferences_.getString("token", "");
    preferences_.end();
    wifiConfigured_ = !ssid_.isEmpty();
    configured_ = !ssid_.isEmpty() && validHost(gatewayHost_) &&
                  gatewayPort_ > 0 && validHexToken(token_);
}

void WifiTransport::startWifi() {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.setHostname(nodeId_.c_str());
    WiFi.begin(ssid_.c_str(), password_.c_str());
    lastReconnectAttempt_ = millis();
    wifiStartedAtMs_ = millis();
    reportNetworkState("connecting_wifi");
}

void WifiTransport::poll() {
    commissioningPortal_.poll();
    if (!wifiConfigured_) {
        return;
    }
    if (WiFi.status() != WL_CONNECTED) {
        clearConnection();
        if (!configured_ && !wifiSetupFallbackStarted_ &&
            millis() - wifiStartedAtMs_ >= 120'000) {
            wifiSetupFallbackStarted_ = true;
            commissioningPortal_.onWifiUnavailable();
            reportNetworkState("wifi_setup_fallback");
            return;
        }
        if (wifiSetupFallbackStarted_) {
            return;
        }
        if (millis() - lastReconnectAttempt_ >= kReconnectIntervalMs) {
            WiFi.reconnect();
            ++wifiReconnects_;
            lastReconnectAttempt_ = millis();
            reportNetworkState("reconnecting_wifi");
        }
        return;
    }
    commissioningPortal_.onWifiConnected();
    if (!configured_) {
        return;
    }
    if (!client_.connected()) {
        authenticated_ = false;
        if (millis() - lastReconnectAttempt_ >= kReconnectIntervalMs) {
            connectGateway();
            lastReconnectAttempt_ = millis();
        }
        return;
    }
    while (client_.available()) {
        const char value = static_cast<char>(client_.read());
        ++networkBytesReceived_;
        if (value == '\n') {
            handleGatewayLine(inputLine_);
            inputLine_.clear();
        } else if (value != '\r') {
            if (inputLine_.length() >= kMaximumLineBytes) {
                reportNetworkState("protocol_error", "line_too_long");
                clearConnection();
                return;
            }
            inputLine_ += value;
        }
    }
}

void WifiTransport::connectGateway() {
    ++gatewayConnectAttempts_;
    reportNetworkState("connecting_gateway");
    if (!client_.connect(gatewayHost_.c_str(), gatewayPort_)) {
        reportNetworkState("gateway_unreachable");
        return;
    }
    client_.setNoDelay(true);
    reportNetworkState("awaiting_challenge");
}

void WifiTransport::handleGatewayLine(const String& line) {
    const String type = jsonString(line, "type");
    if (type == "node_challenge") {
        const String nonce = jsonString(line, "nonce");
        if (nonce.length() != 64) {
            reportNetworkState("protocol_error", "invalid_challenge");
            clearConnection();
            return;
        }
        challengeNonce_ = nonce;
        authenticate(nonce);
        return;
    }
    if (type == "node_authenticated") {
        const String serverProof = jsonString(line, "server_proof");
        const String expectedProof = hmacProof(
            token_, challengeNonce_, nodeId_, "rainpoint-gateway-v2"
        );
        if (jsonString(line, "node_id") != nodeId_ ||
            challengeNonce_.length() != 64 || serverProof.length() != 64 ||
            expectedProof.isEmpty() ||
            !constantTimeEqual(serverProof, expectedProof)) {
            reportNetworkState("protocol_error", "gateway_authentication_failed");
            clearConnection();
            return;
        }
        challengeNonce_.clear();
        authenticated_ = true;
        ++gatewayAuthentications_;
        reportNetworkState("authenticated");
        return;
    }
    if (type == "node_rejected") {
        reportNetworkState("authentication_failed");
        clearConnection();
        return;
    }
    if (authenticated_ &&
        (type == "pairing_start" || type == "pairing_cancel" ||
         type == "identify_start" || type == "rf_mode_set" ||
         type == "node_reboot"
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
         || type == "htv145_control_configure" ||
             type == "htv145_control_sync" ||
             type == "htv145_control_open" ||
             type == "htv145_control_close" ||
             type == "htv145_control_status"
#endif
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
         || type == "valve_control_configure" ||
             type == "valve_control_sync" ||
             type == "valve_control_open" ||
             type == "valve_control_close" ||
             type == "valve_control_status"
#endif
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
         || type == "routine_ack_configure" ||
             type == "routine_ack_revoke" ||
             type == "htv405_routine_ack_configure" ||
             type == "htv405_routine_ack_revoke"
#endif
#if RAINPOINT_OTA_CANDIDATE == 1
         || type == "firmware_update_start"
#endif
        )) {
        if (pendingCommandCount_ == pendingCommands_.size()) {
            reportNetworkState("protocol_error", "command_queue_full");
            return;
        }
        const std::size_t tail =
            (pendingCommandHead_ + pendingCommandCount_) %
            pendingCommands_.size();
        pendingCommands_[tail] = line;
        ++pendingCommandCount_;
    }
}

void WifiTransport::authenticate(const String& nonce) {
    const String proof = hmacProof(
        token_, nonce, nodeId_, "rainpoint-node-v2"
    );
    if (proof.isEmpty()) {
        reportNetworkState("protocol_error", "hmac_failed");
        clearConnection();
        return;
    }
    const int bytesSent = client_.printf(
        "{\"type\":\"node_hello\",\"protocol_version\":%u,"
        "\"node_id\":\"%s\",\"firmware_version\":\"%s\","
        "\"mode\":\"local_radio_node\","
        "\"hardware_profile\":\"esp32dev-cc1101-v1\","
        "\"firmware_variant\":\"%s\","
#if RAINPOINT_OTA_CANDIDATE == 1
        "\"firmware_channel\":\"experimental\","
#else
        "\"firmware_channel\":\"stable\","
#endif
        "\"gateway_host\":\"%s\","
        "\"capabilities\":[\"rx\",\"sensor_pairing_tx\",\"identify\","
        "\"configurable_rf_controller_identity\","
        "\"rf_maintenance\",\"node_reboot\""
#if RAINPOINT_SUPERVISED_HTV405_CONTROL == 1
        ",\"valve_control_tx_candidate\""
#endif
#if RAINPOINT_HTV145_TX_CANDIDATE == 1
        ",\"htv145_control_tx_candidate\""
#endif
#if RAINPOINT_VALVE_PAIRING_CANDIDATE == 1
        ",\"valve_pairing_tx_candidate\""
        ",\"htv405_auto_identity_pairing\""
#endif
#if RAINPOINT_HTV145_PAIRING_CANDIDATE == 1
        ",\"htv145_pairing_tx_candidate\""
#endif
#if RAINPOINT_ROUTINE_ACK_CANDIDATE == 1
        ",\"routine_sensor_ack_tx\""
        ",\"htv405_routine_ack_tx\""
#endif
#if RAINPOINT_OTA_CANDIDATE == 1
        ",\"firmware_update_trial\""
#endif
        "],"
        "\"tx_armed\":false,\"proof\":\"%s\"}\n",
        kProtocolVersion,
        nodeId_.c_str(),
        RAINPOINT_FIRMWARE_VERSION,
        RAINPOINT_FIRMWARE_VARIANT,
        gatewayHost_.c_str(),
        proof.c_str()
    );
    if (bytesSent > 0) {
        networkBytesSent_ += static_cast<std::uint64_t>(bytesSent);
    }
}

bool WifiTransport::takeCommand(String& command) {
    if (pendingCommandCount_ == 0) {
        return false;
    }
    command = pendingCommands_[pendingCommandHead_];
    pendingCommands_[pendingCommandHead_].clear();
    pendingCommandHead_ =
        (pendingCommandHead_ + 1) % pendingCommands_.size();
    --pendingCommandCount_;
    return true;
}

void WifiTransport::sendLine(const String& line) {
    if (!authenticated_ || !client_.connected()) {
        return;
    }
    networkBytesSent_ += client_.print(line);
    networkBytesSent_ += client_.print('\n');
}

bool WifiTransport::handleProvisioningCommand(const String& command) {
    if (command == "show_node") {
        String response =
            String("{\"type\":\"node_configuration\",\"node_id\":\"") +
            nodeId_ + "\",\"wifi_configured\":" +
            (configured_ ? "true" : "false") +
            ",\"gateway_host\":\"" +
            (configured_ ? gatewayHost_ : "") +
            "\",\"gateway_port\":" + gatewayPort_;
        if (!configured_) {
            response += ",\"setup_token\":\"" + token_ + "\"";
        }
        response += "}";
        Serial.println(response);
        return true;
    }
    if (command == "clear_wifi") {
        preferences_.begin("rainpoint", false);
        preferences_.clear();
        preferences_.end();
        configured_ = false;
        token_.clear();
        ensureSetupToken();
        clearConnection();
        WiFi.disconnect(true, true);
        reportNetworkState("configuration_cleared");
        return true;
    }
    if (!command.startsWith("configure_wifi\t")) {
        return false;
    }

    std::array<String, 5> fields;
    int start = String("configure_wifi\t").length();
    for (std::size_t index = 0; index < fields.size(); ++index) {
        const int separator = command.indexOf('\t', start);
        if (index + 1 == fields.size()) {
            fields[index] = command.substring(start);
            start = command.length();
        } else if (separator >= 0) {
            fields[index] = command.substring(start, separator);
            start = separator + 1;
        } else {
            reportNetworkState("configuration_error", "expected_five_fields");
            return true;
        }
    }
    const long port = fields[3].toInt();
    if (fields[0].isEmpty() || fields[0].length() > 32 ||
        fields[1].length() > 63 || !validHost(fields[2]) ||
        port < 1 || port > 65535 || !validHexToken(fields[4])) {
        reportNetworkState("configuration_error", "invalid_field");
        return true;
    }

    preferences_.begin("rainpoint", false);
    preferences_.putString("ssid", fields[0]);
    preferences_.putString("password", fields[1]);
    preferences_.putString("host", fields[2]);
    preferences_.putUShort("port", static_cast<std::uint16_t>(port));
    preferences_.putString("token", fields[4]);
    preferences_.end();
    loadConfiguration();
    reportNetworkState("configuration_saved", "restart_required");
    return true;
}

void WifiTransport::reportNetworkState(const char* state, const char* detail) {
    Serial.printf(
        "{\"type\":\"node_network\",\"node_id\":\"%s\","
        "\"state\":\"%s\"",
        nodeId_.c_str(),
        state
    );
    if (detail != nullptr) {
        Serial.printf(",\"detail\":\"%s\"", detail);
    }
    Serial.println("}");
}

void WifiTransport::clearConnection() {
    authenticated_ = false;
    inputLine_.clear();
    for (auto& command : pendingCommands_) {
        command.clear();
    }
    pendingCommandHead_ = 0;
    pendingCommandCount_ = 0;
    challengeNonce_.clear();
    client_.stop();
}

}  // namespace rainpoint
