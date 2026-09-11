#pragma once
#include <algorithm>
#include <cstdint>
#include <cstring>
#include <string>
using std::min;
class String : public std::string {
public:
    using std::string::string;
    using std::string::operator+=;
    String(const std::string& value) : std::string(value) {}
    bool isEmpty() const { return empty(); }
    bool startsWith(const String& prefix) const { return rfind(prefix, 0) == 0; }
    int indexOf(char c) const { auto p = find(c); return p == npos ? -1 : p; }
    bool equalsIgnoreCase(const String& other) const { return *this == other; }
    String& operator+=(unsigned long value) { append(std::to_string(value)); return *this; }
    String& operator+=(unsigned char value) { append(std::to_string(value)); return *this; }
};
inline unsigned long testClock = 0;
inline unsigned long millis() { return ++testClock; }
inline void delay(unsigned long milliseconds) { testClock += milliseconds; }
struct TestEsp { unsigned restarts = 0; void restart() { ++restarts; } };
inline TestEsp ESP;
