#pragma once

#include <Arduino.h>
#include <DNSServer.h>
#include <WebServer.h>

#include <cstdint>

namespace rainpoint {

class CommissioningPortal {
public:
    void begin(const String& nodeId, bool wifiConfigured, bool adopted);
    void onWifiConnected();
    void onWifiUnavailable();
    void poll();

private:
    static constexpr std::uint32_t kIdentifyDurationMs = 30'000;
    static constexpr std::uint32_t kConfirmationDurationMs = 60'000;
    static constexpr std::uint32_t kLedToggleMs = 250;
    static constexpr std::uint32_t kRestartDelayMs = 1'500;
    static constexpr std::uint32_t kFactoryResetHoldMs = 10'000;

    void startAccessPoint();
    void startAdoptionServer();
    void configureRoutes();
    void handleRoot();
    void handleWifiConfiguration();
    void handleInfo();
    void handleIdentify();
    void handleAdoption();
    void handleNotFound();
    void pollIdentification();
    void pollFactoryReset();
    void scheduleRestart();
    bool confirmationValid() const;
    void setLed(bool on);

    DNSServer dns_;
    WebServer server_{80};
    String nodeId_;
    bool accessPointMode_ = false;
    bool adoptionMode_ = false;
    bool serverStarted_ = false;
    bool mdnsStarted_ = false;
    bool routesConfigured_ = false;
    bool ledOn_ = false;
    bool previousButtonPressed_ = false;
    std::uint32_t identifyUntilMs_ = 0;
    std::uint32_t confirmedUntilMs_ = 0;
    std::uint32_t lastLedToggleMs_ = 0;
    std::uint32_t restartAtMs_ = 0;
    std::uint32_t resetButtonDownAtMs_ = 0;
};

}  // namespace rainpoint
