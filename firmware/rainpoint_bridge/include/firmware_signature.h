#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <mbedtls/pk.h>
#include <mbedtls/sha256.h>

namespace rainpoint {

struct FirmwareSigningKey { const char* id; const char* pem; };
struct SignedFirmware {
    std::string keyId;
    std::string version;
    std::string sha256;
    std::size_t size = 0;
};

inline bool lowerHex(std::string_view value) {
    for (char c : value) if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f'))) return false;
    return !value.empty();
}

inline bool decodeHex(std::string_view encoded, std::string& bytes, std::size_t maximum) {
    if (encoded.size() % 2 || encoded.size() > maximum * 2 || !lowerHex(encoded)) return false;
    auto nibble = [](char c) { return c <= '9' ? c - '0' : c - 'a' + 10; };
    bytes.clear(); bytes.reserve(encoded.size() / 2);
    for (std::size_t i = 0; i < encoded.size(); i += 2)
        bytes.push_back(static_cast<char>((nibble(encoded[i]) << 4) | nibble(encoded[i + 1])));
    return true;
}

inline bool signingLabel(std::string_view value, std::size_t maximum, bool dot = false) {
    if (value.empty() || value.size() > maximum) return false;
    for (char c : value)
        if (!((c >= 'a' && c <= 'z') || (c >= '0' && c <= '9') || c == '-' || (dot && c == '.'))) return false;
    return true;
}

inline bool signingVersion(std::string_view value) {
    if (value.empty() || value.size() > 48) return false;
    std::size_t position = 0;
    for (int part = 0; part < 3; ++part) {
        const auto start = position;
        while (position < value.size() && value[position] >= '0' && value[position] <= '9') ++position;
        if (position == start) return false;
        if (part != 2 && (position == value.size() || value[position++] != '.')) return false;
    }
    if (position == value.size()) return true;
    if ((value[position] != '-' && value[position] != '+') || ++position == value.size()) return false;
    for (; position < value.size(); ++position) {
        char c = value[position];
        if (!((c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') ||
              (c >= '0' && c <= '9') || c == '.' || c == '-')) return false;
    }
    return true;
}

inline bool parseFirmwareDescriptor(std::string_view bytes, SignedFirmware& output) {
    if (bytes.empty() || bytes.size() > 768) return false;
    std::array<std::string_view, 14> lines{};
    std::size_t position = 0;
    for (auto& line : lines) {
        const auto end = bytes.find('\n', position);
        if (end == std::string_view::npos) return false;
        line = bytes.substr(position, end - position); position = end + 1;
        for (char c : line) if (c < 0x20 || c > 0x7e) return false;
    }
    if (position != bytes.size() || lines[0] != "rainpoint-firmware-signature-v1") return false;
    constexpr std::array<std::string_view, 13> names = {"key_id=", "product=", "board=",
        "hardware_profile=", "environment=", "firmware_variant=", "channel=",
        "network_protocol_version=", "version=", "source_commit=", "release_id=", "size_bytes=", "sha256="};
    std::array<std::string_view, 13> values{};
    for (std::size_t i = 0; i < names.size(); ++i) {
        if (lines[i + 1].substr(0, names[i].size()) != names[i]) return false;
        values[i] = lines[i + 1].substr(names[i].size());
    }
    if (!signingLabel(values[0], 32) || values[1] != "rainpoint-radio-node" || values[2] != "esp32dev" ||
        values[3] != "esp32dev-cc1101-v1" || values[4] != "rainpoint_bridge" || values[5] != "unified" ||
        values[6] != "experimental" || values[7] != "2" || !signingVersion(values[8]) ||
        values[9].size() != 40 || !lowerHex(values[9]) || !signingLabel(values[10], 96, true) ||
        values[12].size() != 64 || !lowerHex(values[12])) return false;
    const auto sizeValue = values[11];
    if (sizeValue.empty() || sizeValue.size() > 7 || sizeValue[0] == '0') return false;
    std::size_t size = 0;
    for (char c : sizeValue) { if (c < '0' || c > '9') return false; size = size * 10 + c - '0'; }
    if (size < 65536 || size > 2 * 1024 * 1024) return false;
    output = {std::string(values[0]), std::string(values[8]), std::string(values[12]), size};
    return true;
}

inline bool verifyFirmwareSignature(std::string_view descriptorHex, std::string_view signatureHex,
        const FirmwareSigningKey* keys, std::size_t keyCount, SignedFirmware& output) {
    std::string descriptor, signature;
    SignedFirmware parsed;
    if (!decodeHex(descriptorHex, descriptor, 768) || !decodeHex(signatureHex, signature, 72) ||
        !parseFirmwareDescriptor(descriptor, parsed)) return false;
    const char* pem = nullptr;
    for (std::size_t i = 0; i < keyCount; ++i) if (parsed.keyId == keys[i].id) pem = keys[i].pem;
    if (!pem) return false;
    std::array<unsigned char, 32> digest{};
    if (mbedtls_sha256_ret(reinterpret_cast<const unsigned char*>(descriptor.data()),
            descriptor.size(), digest.data(), 0) != 0) return false;
    mbedtls_pk_context key; mbedtls_pk_init(&key);
    bool valid = mbedtls_pk_parse_public_key(&key, reinterpret_cast<const unsigned char*>(pem),
        std::char_traits<char>::length(pem) + 1) == 0 &&
        mbedtls_pk_can_do(&key, MBEDTLS_PK_ECDSA) && mbedtls_pk_get_bitlen(&key) == 256 &&
        mbedtls_pk_ec(key)->grp.id == MBEDTLS_ECP_DP_SECP256R1 &&
        mbedtls_pk_verify(&key, MBEDTLS_MD_SHA256, digest.data(), digest.size(),
            reinterpret_cast<const unsigned char*>(signature.data()), signature.size()) == 0;
    mbedtls_pk_free(&key);
    if (valid) output = parsed;
    return valid;
}

// Deliberately narrow OTA wire grammar. No escapes/nesting, duplicate keys,
// unknown fields, booleans-as-integers, or trailing JSON are accepted.
struct SignedOtaRequest {
    std::string commandId, url, version, sha256, descriptorHex, signatureHex;
    std::size_t size = 0;
};
inline bool parseSignedOtaRequest(std::string_view input, SignedOtaRequest& output) {
    if (input.size() > 3072) return false;
    std::size_t p = 0;
    auto space = [&]() { while (p < input.size() && (input[p] == ' ' || input[p] == '\t' || input[p] == '\r' || input[p] == '\n')) ++p; };
    auto token = [&](char c) { space(); if (p == input.size() || input[p] != c) return false; ++p; return true; };
    auto string = [&](std::string& value) {
        if (!token('"')) return false;
        const auto start = p;
        while (p < input.size() && input[p] != '"') {
            if (input[p] < 0x20 || input[p] > 0x7e || input[p] == '\\') return false;
            ++p;
        }
        if (p == input.size()) return false;
        value = std::string(input.substr(start, p++ - start)); return true;
    };
    if (!token('{')) return false;
    constexpr std::array<std::string_view, 8> names = {"type", "command_id", "url", "version", "sha256", "size_bytes", "signed_descriptor_hex", "signature_der_hex"};
    std::array<bool, 8> seen{};
    std::array<std::string, 8> values{};
    for (std::size_t field = 0; field < names.size(); ++field) {
        if (field && !token(',')) return false;
        std::string name;
        if (!string(name) || !token(':')) return false;
        std::size_t index = 0;
        while (index < names.size() && name != names[index]) ++index;
        if (index == names.size() || seen[index]) return false;
        seen[index] = true;
        if (index != 5) { if (!string(values[index])) return false; }
        else {
            space(); const auto start = p;
            while (p < input.size() && input[p] >= '0' && input[p] <= '9') ++p;
            values[index] = std::string(input.substr(start, p - start));
            if (values[index].empty() || values[index].size() > 7 || values[index][0] == '0') return false;
        }
    }
    if (!token('}')) return false;
    space(); if (p != input.size() || values[0] != "firmware_update_start" ||
        values[1].size() != 32 || !lowerHex(values[1]) || values[2].size() > 320 ||
        !signingVersion(values[3]) || values[4].size() != 64 || !lowerHex(values[4]) ||
        values[6].size() > 1536 || values[7].size() > 144) return false;
    std::size_t size = 0; for (char c : values[5]) size = size * 10 + c - '0';
    if (size < 65536 || size > 2 * 1024 * 1024) return false;
    output = {values[1], values[2], values[3], values[4], values[6], values[7], size};
    return true;
}

inline bool authenticateOtaRequest(const SignedOtaRequest& request,
        const FirmwareSigningKey* keys, std::size_t count) {
    SignedFirmware signedImage;
    return verifyFirmwareSignature(request.descriptorHex, request.signatureHex, keys, count, signedImage) &&
        signedImage.version == request.version && signedImage.sha256 == request.sha256 && signedImage.size == request.size;
}
} // namespace rainpoint
