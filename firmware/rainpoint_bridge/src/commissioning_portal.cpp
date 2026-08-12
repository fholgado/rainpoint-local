#include "commissioning_portal.h"

#include <ESPmDNS.h>
#include <Preferences.h>
#include <WiFi.h>
#include <esp_system.h>

#include <cctype>

#ifndef RAINPOINT_FIRMWARE_VERSION
#define RAINPOINT_FIRMWARE_VERSION "development"
#endif

#ifndef RAINPOINT_STATUS_LED_PIN
#error "RAINPOINT_STATUS_LED_PIN must identify the board status LED"
#endif

#ifndef RAINPOINT_CONFIRM_BUTTON_PIN
#error "RAINPOINT_CONFIRM_BUTTON_PIN must identify the physical confirmation button"
#endif

namespace rainpoint {
namespace {

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

bool validToken(const String& token) {
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

bool deadlineActive(std::uint32_t deadline) {
    return deadline != 0 &&
        static_cast<std::int32_t>(deadline - millis()) > 0;
}

}  // namespace

void CommissioningPortal::begin(
    const String& nodeId, bool wifiConfigured, bool adopted
) {
    nodeId_ = nodeId;
    pinMode(RAINPOINT_CONFIRM_BUTTON_PIN, INPUT_PULLUP);
    if (!wifiConfigured) {
        startAccessPoint();
    } else if (!adopted) {
        adoptionMode_ = true;
    }
}

void CommissioningPortal::startAccessPoint() {
    accessPointMode_ = true;
    WiFi.persistent(false);
    WiFi.mode(WIFI_AP);
    const String suffix = nodeId_.substring(nodeId_.length() - 6);
    const String ssid = "RainPoint Local Setup " + suffix;
    WiFi.softAP(ssid.c_str());
    dns_.start(53, "*", WiFi.softAPIP());
    configureRoutes();
    server_.begin();
    serverStarted_ = true;
    Serial.printf(
        "{\"type\":\"commissioning\",\"node_id\":\"%s\","
        "\"state\":\"wifi_setup\",\"ssid\":\"%s\"}\n",
        nodeId_.c_str(),
        ssid.c_str()
    );
}

void CommissioningPortal::onWifiConnected() {
    if (!adoptionMode_ || serverStarted_) {
        return;
    }
    startAdoptionServer();
}

void CommissioningPortal::onWifiUnavailable() {
    if (adoptionMode_ && !serverStarted_) {
        adoptionMode_ = false;
        startAccessPoint();
    }
}

void CommissioningPortal::startAdoptionServer() {
    configureRoutes();
    server_.begin();
    serverStarted_ = true;
    if (MDNS.begin(nodeId_.c_str())) {
        MDNS.addService("rainpoint-node", "tcp", 80);
        MDNS.addServiceTxt("rainpoint-node", "tcp", "id", nodeId_);
        MDNS.addServiceTxt(
            "rainpoint-node", "tcp", "firmware", RAINPOINT_FIRMWARE_VERSION
        );
        MDNS.addServiceTxt("rainpoint-node", "tcp", "state", "adoptable");
        mdnsStarted_ = true;
    }
    Serial.printf(
        "{\"type\":\"commissioning\",\"node_id\":\"%s\","
        "\"state\":\"adoptable\",\"ip_address\":\"%s\"}\n",
        nodeId_.c_str(),
        WiFi.localIP().toString().c_str()
    );
}

void CommissioningPortal::configureRoutes() {
    if (routesConfigured_) {
        return;
    }
    routesConfigured_ = true;
    server_.on("/", HTTP_GET, [this]() { handleRoot(); });
    server_.on(
        "/configure", HTTP_POST, [this]() { handleWifiConfiguration(); }
    );
    server_.on("/api/v1/info", HTTP_GET, [this]() { handleInfo(); });
    server_.on(
        "/api/v1/identify", HTTP_POST, [this]() { handleIdentify(); }
    );
    server_.on("/api/v1/adopt", HTTP_POST, [this]() { handleAdoption(); });
    server_.onNotFound([this]() { handleNotFound(); });
}

void CommissioningPortal::handleRoot() {
    if (!accessPointMode_) {
        handleInfo();
        return;
    }
    server_.send(
        200,
        "text/html",
        "<!doctype html><meta name=viewport content='width=device-width'>"
        "<title>RainPoint Local Setup</title><h1>RainPoint Local Setup</h1>"
        "<p>Connect this radio node to your home Wi-Fi. Home Assistant will "
        "discover it after it joins.</p><form method=post action=/configure>"
        "<label>Wi-Fi name<br><input name=ssid maxlength=32 required></label>"
        "<br><br><label>Password<br><input name=password type=password "
        "maxlength=63></label><br><br><button>Connect</button></form>"
    );
}

void CommissioningPortal::handleWifiConfiguration() {
    if (!accessPointMode_) {
        server_.send(409, "application/json", "{\"error\":\"not_in_setup\"}");
        return;
    }
    const String ssid = server_.arg("ssid");
    const String password = server_.arg("password");
    if (ssid.isEmpty() || ssid.length() > 32 || password.length() > 63) {
        server_.send(400, "text/plain", "Invalid Wi-Fi configuration");
        return;
    }
    Preferences preferences;
    preferences.begin("rainpoint", false);
    preferences.putString("ssid", ssid);
    preferences.putString("password", password);
    preferences.remove("host");
    preferences.remove("port");
    preferences.end();
    server_.send(
        200,
        "text/html",
        "<h1>Wi-Fi saved</h1><p>The node is restarting. Return to Home "
        "Assistant to adopt it.</p>"
    );
    scheduleRestart();
}

void CommissioningPortal::handleInfo() {
    String response = "{\"node_id\":\"" + nodeId_ +
        "\",\"firmware_version\":\"" RAINPOINT_FIRMWARE_VERSION "\","
        "\"state\":\"" +
        (adoptionMode_ ? "adoptable" : "wifi_setup") +
        "\",\"identify_active\":" +
        (deadlineActive(identifyUntilMs_) ? "true" : "false") +
        ",\"physically_confirmed\":" +
        (confirmationValid() ? "true" : "false") + "}";
    server_.send(200, "application/json", response);
}

void CommissioningPortal::handleIdentify() {
    if (!adoptionMode_) {
        server_.send(409, "application/json", "{\"error\":\"not_adoptable\"}");
        return;
    }
    identifyUntilMs_ = millis() + kIdentifyDurationMs;
    confirmedUntilMs_ = 0;
    lastLedToggleMs_ = millis();
    setLed(true);
    server_.send(
        200,
        "application/json",
        "{\"identify_active\":true,\"press_boot_to_confirm\":true}"
    );
}

void CommissioningPortal::handleAdoption() {
    if (!adoptionMode_ || !confirmationValid()) {
        server_.send(
            403, "application/json", "{\"error\":\"physical_confirmation_required\"}"
        );
        return;
    }
    const String host = server_.arg("host");
    const long port = server_.arg("port").toInt();
    const String token = server_.arg("token");
    if (!validHost(host) || port < 1 || port > 65535 || !validToken(token)) {
        server_.send(400, "application/json", "{\"error\":\"invalid_adoption\"}");
        return;
    }
    Preferences preferences;
    preferences.begin("rainpoint", false);
    preferences.putString("host", host);
    preferences.putUShort("port", static_cast<std::uint16_t>(port));
    preferences.putString("token", token);
    preferences.end();
    confirmedUntilMs_ = 0;
    identifyUntilMs_ = 0;
    setLed(false);
    server_.send(200, "application/json", "{\"state\":\"adopting\"}");
    scheduleRestart();
}

void CommissioningPortal::handleNotFound() {
    if (accessPointMode_) {
        server_.sendHeader("Location", "/", true);
        server_.send(302, "text/plain", "");
    } else {
        server_.send(404, "application/json", "{\"error\":\"not_found\"}");
    }
}

void CommissioningPortal::poll() {
    if (accessPointMode_) {
        dns_.processNextRequest();
    }
    if (serverStarted_) {
        server_.handleClient();
    }
    pollIdentification();
    pollFactoryReset();
    if (restartAtMs_ != 0 &&
        static_cast<std::int32_t>(millis() - restartAtMs_) >= 0) {
        ESP.restart();
    }
}

void CommissioningPortal::pollFactoryReset() {
    const bool pressed = digitalRead(RAINPOINT_CONFIRM_BUTTON_PIN) == LOW;
    if (!pressed) {
        resetButtonDownAtMs_ = 0;
        return;
    }
    if (resetButtonDownAtMs_ == 0) {
        resetButtonDownAtMs_ = millis();
        return;
    }
    if (millis() - resetButtonDownAtMs_ < kFactoryResetHoldMs) {
        return;
    }
    Preferences preferences;
    preferences.begin("rainpoint", false);
    preferences.clear();
    preferences.end();
    setLed(false);
    Serial.printf(
        "{\"type\":\"commissioning\",\"node_id\":\"%s\","
        "\"state\":\"factory_reset\"}\n",
        nodeId_.c_str()
    );
    ESP.restart();
}

void CommissioningPortal::pollIdentification() {
    const bool active = deadlineActive(identifyUntilMs_);
    if (!active) {
        if (identifyUntilMs_ != 0) {
            identifyUntilMs_ = 0;
            setLed(false);
        }
        previousButtonPressed_ = false;
        if (confirmedUntilMs_ != 0 && !confirmationValid()) {
            confirmedUntilMs_ = 0;
            setLed(false);
        }
        return;
    }
    const bool pressed = digitalRead(RAINPOINT_CONFIRM_BUTTON_PIN) == LOW;
    if (pressed && !previousButtonPressed_) {
        confirmedUntilMs_ = millis() + kConfirmationDurationMs;
        identifyUntilMs_ = 0;
        setLed(true);
    } else if (millis() - lastLedToggleMs_ >= kLedToggleMs) {
        lastLedToggleMs_ = millis();
        setLed(!ledOn_);
    }
    previousButtonPressed_ = pressed;
}

bool CommissioningPortal::confirmationValid() const {
    return deadlineActive(confirmedUntilMs_);
}

void CommissioningPortal::scheduleRestart() {
    restartAtMs_ = millis() + kRestartDelayMs;
}

void CommissioningPortal::setLed(bool on) {
    ledOn_ = on;
    digitalWrite(RAINPOINT_STATUS_LED_PIN, on ? HIGH : LOW);
}

}  // namespace rainpoint
