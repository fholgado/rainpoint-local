#pragma once

#include <Arduino.h>
#include <Preferences.h>
#include <WiFi.h>

#include <cstdint>

namespace rainpoint {

class WifiTransport {
public:
    void begin();
    void poll();
    void sendLine(const String& line);
    bool takeCommand(String& command);
    bool handleProvisioningCommand(const String& command);

    const String& nodeId() const { return nodeId_; }
    bool configured() const { return configured_; }
    bool authenticated() const { return authenticated_; }
    String localIp() const { return WiFi.localIP().toString(); }
    int wifiRssiDbm() const { return WiFi.RSSI(); }
    std::uint64_t networkBytesSent() const { return networkBytesSent_; }
    std::uint64_t networkBytesReceived() const { return networkBytesReceived_; }
    std::uint32_t wifiReconnects() const { return wifiReconnects_; }
    std::uint32_t gatewayConnectAttempts() const {
        return gatewayConnectAttempts_;
    }
    std::uint32_t gatewayAuthentications() const {
        return gatewayAuthentications_;
    }

private:
    static constexpr std::uint16_t kProtocolVersion = 2;
    static constexpr std::uint32_t kReconnectIntervalMs = 5'000;
    static constexpr std::size_t kMaximumLineBytes = 1'024;

    void loadConfiguration();
    void ensureSetupToken();
    void startWifi();
    void connectGateway();
    void handleGatewayLine(const String& line);
    void authenticate(const String& nonce);
    void reportNetworkState(const char* state, const char* detail = nullptr);
    void clearConnection();

    Preferences preferences_;
    WiFiClient client_;
    String nodeId_;
    String ssid_;
    String password_;
    String gatewayHost_;
    String token_;
    String inputLine_;
    String pendingCommand_;
    String challengeNonce_;
    std::uint16_t gatewayPort_ = 8790;
    std::uint32_t lastReconnectAttempt_ = 0;
    std::uint64_t networkBytesSent_ = 0;
    std::uint64_t networkBytesReceived_ = 0;
    std::uint32_t wifiReconnects_ = 0;
    std::uint32_t gatewayConnectAttempts_ = 0;
    std::uint32_t gatewayAuthentications_ = 0;
    bool configured_ = false;
    bool authenticated_ = false;
};

}  // namespace rainpoint
