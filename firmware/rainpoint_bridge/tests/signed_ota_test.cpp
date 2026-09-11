// Runs the production OTA class and Mbed TLS verifier with instrumented I/O.
#include "ota_trial.h"
#include <HTTPClient.h>
#include <Update.h>
#include <fstream>
#include <iostream>
#include <iterator>

std::string read(const char* path) {
    std::ifstream input(path, std::ios::binary);
    return {std::istreambuf_iterator<char>(input), std::istreambuf_iterator<char>()};
}

int main(int argc, char** argv) {
    if (argc != 3) return 2;
    rainpoint::SignedOtaRequest request;
    const bool parsed = rainpoint::parseSignedOtaRequest(read(argv[1]), request);
    downloadBytes = read(argv[2]);
    rainpoint::OtaTrial trial;
    WiFiClientSecure client;
    bool success = parsed && trial.install(request, "127.0.0.1", client);
    std::cout << "{\"parsed\":" << parsed << ",\"success\":" << success
              << ",\"downloads\":" << downloadStarts << ",\"begins\":" << Update.begins
              << ",\"writes\":" << Update.writes << ",\"ends\":" << Update.ends
              << ",\"aborts\":" << Update.aborts << ",\"pending\":" << pendingWrites
              << ",\"restart_pending\":" << trial.restartPending() << "}\n";
}
