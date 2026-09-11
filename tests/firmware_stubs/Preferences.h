#pragma once
#include "Arduino.h"
inline unsigned pendingWrites = 0;
class Preferences {
public:
    void begin(const char*, bool) {}
    void end() {}
    bool getBool(const char*, bool value) { return value; }
    String getString(const char*, const char* value) { return value; }
    unsigned char getUChar(const char*, unsigned char value) { return value; }
    void putBool(const char*, bool) { ++pendingWrites; }
    void putString(const char*, const String&) {}
    void putUChar(const char*, unsigned char) {}
    void remove(const char*) {}
};
