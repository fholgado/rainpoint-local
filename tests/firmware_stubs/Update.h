#pragma once
#include "Arduino.h"
constexpr int U_FLASH = 0;
struct TestUpdate {
    unsigned begins = 0, writes = 0, ends = 0, aborts = 0;
    bool begin(std::size_t, int) { ++begins; return true; }
    std::size_t write(std::uint8_t*, std::size_t size) { ++writes; return size; }
    bool end(bool) { ++ends; return true; }
    void abort() { ++aborts; }
    bool canRollBack() { return false; }
    bool rollBack() { return false; }
};
inline TestUpdate Update;
