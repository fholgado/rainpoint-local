#pragma once
#include "WiFiClientSecure.h"
constexpr int HTTP_CODE_OK = 200;
inline unsigned downloadStarts = 0;
class HTTPClient {
    WiFiClientSecure* client = nullptr;
public:
    void setConnectTimeout(int) {}
    void setTimeout(int) {}
    bool begin(WiFiClientSecure& value, const String&) { ++downloadStarts; client = &value; return true; }
    int GET() { return HTTP_CODE_OK; }
    std::size_t getSize() { return downloadBytes.size(); }
    void end() {}
    bool connected() { return client->available() > 0; }
    WiFiClient* getStreamPtr() { return client; }
};
