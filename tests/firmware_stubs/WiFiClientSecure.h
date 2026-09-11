#pragma once
#include "Arduino.h"
inline std::string downloadBytes;
class WiFiClient {
public:
    std::size_t position = 0;
    int available() { return downloadBytes.size() - position; }
    int readBytes(std::uint8_t* target, std::size_t size) {
        size = std::min(size, downloadBytes.size() - position);
        std::memcpy(target, downloadBytes.data() + position, size); position += size; return size;
    }
};
class WiFiClientSecure : public WiFiClient {};
