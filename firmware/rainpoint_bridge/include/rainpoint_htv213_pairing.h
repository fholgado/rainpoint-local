#pragma once

#include "rainpoint_pairing.h"
#include "rainpoint_valve_configuration.h"

namespace rainpoint::htv213 {

// Isolated dry-canary enrollment. No water-control builder, implicit identity,
// boot/rejoin handler, fixed transcript cursor, or production runtime binding.
constexpr const char* kCapability = "htv213_pairing_experiment";
using Frame = std::array<std::uint8_t, kFrameBytes>;
using Endpoint = std::array<std::uint8_t, 4>;
using Context = valveConfiguration::ReportContext;
enum class State { Disarmed, Armed, Observed, Failed };
enum class Failure { None, Timeout, Transmit, Disconnected, Cancelled, ReplyLimit, Receiver };

struct Profile {
    Endpoint factory{}, controller{}, companion{};
    std::uint8_t address = 0, selector = 0, notificationPhase = 0;
    std::uint16_t timingRaw = 0;
    // Programmed selector-12 reference (including this node's measured trim).
    // Request selector, not the newly assigned selector, picks the 81 carrier.
    std::uint32_t initialHz = 0, routineHz = 0;
    std::uint32_t replyDelayUs = 0, notificationDelayMs = 0;
    std::array<std::uint8_t, 14> settings{};
};

inline std::uint32_t assignmentReplyHz(const Profile& p, std::uint8_t requestedSelector) {
    // Only the two captured announcement selectors are qualified here.
    if (requestedSelector != 11 && requestedSelector != 12) return 0;
    const std::int64_t hz = static_cast<std::int64_t>(p.initialHz) +
        (static_cast<std::int64_t>(requestedSelector) - 12) * 110000;
    return hz >= 433000000 && hz <= 435000000 ? static_cast<std::uint32_t>(hz) : 0;
}

inline bool valid(const Profile& p) {
    auto controller = p.companion;
    controller[0] |= 128;
    return valveConfiguration::nonzero(p.factory) && !(p.factory[0] & 128) &&
        valveConfiguration::nonzero(p.companion) &&
        !(p.companion[0] & 128) && controller == p.controller &&
        p.address > 0 && p.selector > 0 && p.selector <= 15 && p.timingRaw > 0 &&
        p.notificationPhase > 0 && p.notificationPhase <= 63 &&
        assignmentReplyHz(p,11) != 0 && assignmentReplyHz(p,12) != 0 &&
        p.routineHz >= 433000000 && p.routineHz <= 435000000 &&
        p.replyDelayUs >= 20000 && p.replyDelayUs <= 150000 &&
        p.notificationDelayMs >= 500 && p.notificationDelayMs <= 5000;
}

inline std::array<std::uint8_t, 32> native(const Frame& f) {
    std::array<std::uint8_t, 32> p{};
    for (std::size_t i=0; i<p.size(); ++i)
        p[i] = static_cast<std::uint8_t>((f[i+4] << 1U) | (f[i+5] >> 7U));
    return p;
}

// Produce the same legacy window as the stock native CRC (seed A8A8).
// The existing radio transport owns the physical tail. Its omitted last CRC
// bit and RF timing still require SDR qualification on the new canary.
inline bool encode(const Profile& p, std::uint8_t command, std::uint8_t phase,
                   const std::uint8_t* data, std::size_t length, Frame& frame) {
    if (!valid(p) || phase > 63 || length > 20) return false;
    frame = {};
    for (std::size_t i=0; i<kSync.size(); ++i) frame[i] = kSync[i];
    auto paired = p.factory; paired[0] |= 128;
    for (std::size_t i=0; i<4; ++i) {
        frame[5+i] = paired[i]; frame[9+i] = p.companion[i];
    }
    frame[13] = 128; // Stock controller-originated envelope direction bit.
    std::array<std::uint8_t, 23> body{};
    body[0] = phase; body[1] = command; body[2] = length;
    for (std::size_t i=0; i<length; ++i) body[3+i] = data[i];
    for (std::size_t i=0; i<body.size(); ++i) {
        frame[13+i] = (frame[13+i] & 128) | (body[i] >> 1);
        frame[14+i] = (frame[14+i] & 127) | ((body[i] & 1) << 7);
    }
    const auto payload = native(frame);
    std::uint16_t crc = 0xa8a8;
    for (auto value : payload) {
        crc ^= static_cast<std::uint16_t>(value) << 8;
        for (unsigned bit=0; bit<8; ++bit)
            crc = static_cast<std::uint16_t>((crc << 1) ^ ((crc & 0x8000) ? 0x1021 : 0));
    }
    frame[36] = (frame[36] & 128) | (crc >> 9);
    frame[37] = static_cast<std::uint8_t>(crc >> 1);
    return hasOrdinaryTrailer(frame);
}

struct Transmission {
    Frame frame{};
    std::uint32_t centerHz = 0;
    std::uint16_t wakeSymbols = 320;
    std::uint8_t command = 0, port = 0;
};

class Session {
public:
    bool arm(const Profile& p, std::uint32_t now, std::uint32_t durationMs) {
        if (state_ == State::Armed || !valid(p) || durationMs < 10000 || durationMs > 300000)
            return false;
        *this = Session{}; profile_ = p; started_ = now; duration_ = durationMs;
        state_ = State::Armed; return true;
    }
    void cancel(Failure why = Failure::Cancelled) {
        if (state_ == State::Armed) { state_ = State::Failed; failure_ = why; pending_ = false; }
    }
    void tick(std::uint32_t now, bool connected = true) {
        if (state_ != State::Armed) return;
        if (!connected) cancel(Failure::Disconnected);
        else if (now - started_ >= duration_) cancel(Failure::Timeout);
    }
    State state() const { return state_; }
    Failure failure() const { return failure_; }
    const Profile& profile() const { return profile_; }
    unsigned reports() const { return reports_; }
    unsigned settingsSent() const { return settings_; }
    unsigned plansSent() const { return plans_; }
    unsigned repliesSent() const { return replies_; }
    bool notificationAccepted() const { return notificationAccepted_; }
    bool notificationResponseWindow(std::uint32_t now) const {
        return state_ == State::Armed && notificationSent_ && !notificationAccepted_ &&
            now - notificationSentMs_ < 750;
    }

    bool claim(const Frame& frame, const Context& context, std::uint32_t now, Transmission& out) {
        tick(now);
        if (state_ != State::Armed || pending_ || !hasSync(frame) || !hasOrdinaryTrailer(frame)) return false;
        const auto n = native(frame);
        if (n[0] != 0x51 || (n[11] & 31) > 20) return false;
        const auto command = n[10];
        auto paired = profile_.factory; paired[0] |= 128;
        const Endpoint broadcast{{128,0,0,0}};
        const bool factory = routes(frame, broadcast, profile_.factory);
        const bool addressed = routes(frame, profile_.controller, paired);
        valveConfiguration::Reply reply{};
        if (factory && command == 1 && (n[11] & 31) == 8 && reports_ == 0) {
            // Exact observed explicit-pairing variants, not a universal flag
            // mask. Repeat long-press after stock association changed both the
            // selector and final byte. Retained-rejoin byte 03 stays separate.
            const std::array<std::uint8_t,8> shape{{12,255,32,5,1,4,62,5}};
            const std::array<std::uint8_t,8> repeatShape{{11,255,32,5,1,4,62,7}};
            bool initialMatch=true, repeatMatch=true;
            for (unsigned i=0; i<8; ++i) {
                initialMatch = initialMatch && n[12+i] == shape[i];
                repeatMatch = repeatMatch && n[12+i] == repeatShape[i];
            }
            if (!initialMatch && !repeatMatch) return false;
            if (!context.timeKnown) return false;
            reply.command=0x81; reply.phase=n[9]&63; reply.length=11;
            reply.data[0]=0x0a; reply.data[1]=profile_.address; reply.data[2]=profile_.selector;
            reply.data[3]=profile_.timingRaw & 255; reply.data[4]=profile_.timingRaw >> 8;
            for (unsigned i=0; i<5; ++i) reply.data[5+i]=context.time[i];
            reply.data[10]=1;
        } else if (addressed && assignmentSent_) {
            if (command == 0xa0) {
                if (notificationSent_ && (n[9]&63)==profile_.notificationPhase &&
                    (n[11]&31)==1 && n[12]==0) notificationAccepted_=true;
                return false;
            }
            valveConfiguration::Association a{};
            a.model=valveConfiguration::Model::Htv213; a.requestRouteA=profile_.controller;
            a.requestRouteB=paired; a.selector=profile_.selector;
            a.configurationRevision=notificationSent_ ? 2 : 1;
            for (auto& port : a.ports) {
                port.settings=profile_.settings; port.settingsKnown=true; port.emptyPlanKnown=true;
            }
            if (valveConfiguration::prepareReply(a,frame,context,reply) != valveConfiguration::Result::Ready)
                return false;
            if (command == 2) {
                reports_ |= 1U << (reply.port-1);
                // A later device report, not our last 86, supplies progression
                // evidence. Operational authorization still needs dry control.
                if (plans_ == 3 && settings_ == 3 && notificationAccepted_) observedAfterPlans_=true;
            } else if (!notificationAccepted_) return false;
        } else return false;
        if (replies_ >= 64) { cancel(Failure::ReplyLimit); return false; }
        out = {};
        if (!encode(profile_,reply.command,reply.phase,reply.data.data(),reply.length,out.frame)) return false;
        out.centerHz = factory ? assignmentReplyHz(profile_,n[12]) : profile_.routineHz;
        out.command=reply.command; out.port=reply.port;
        pending_=true; claimed_=out; return true;
    }
    bool claimNotification(std::uint32_t now, Transmission& out) {
        tick(now);
        if (state_ != State::Armed || pending_ || reports_ != 3 ||
            notificationSent_ || !reportAckSent_ || now-lastReportAckMs_ < profile_.notificationDelayMs)
            return false;
        if (replies_ >= 64) { cancel(Failure::ReplyLimit); return false; }
        const std::uint8_t data[]{2,0}; out={};
        if (!encode(profile_,0x20,profile_.notificationPhase,data,2,out.frame)) return false;
        out.command=0x20; out.centerHz=profile_.routineHz; out.wakeSymbols=2400;
        pending_=true; claimed_=out; return true;
    }
    void finish(bool sent, std::uint32_t now) {
        if (!pending_ || state_ != State::Armed) return;
        pending_=false;
        if (!sent) { cancel(Failure::Transmit); return; }
        ++replies_;
        switch (claimed_.command) {
            case 0x81: assignmentSent_=true; break;
            case 0x82: reportAckSent_=true; lastReportAckMs_=now; break;
            case 0x20: notificationSent_=true; notificationSentMs_=now; break;
            case 0x85: settings_ |= 1U << (claimed_.port-1); break;
            case 0x86: plans_ |= 1U << (claimed_.port-1); break;
        }
        if (observedAfterPlans_) state_=State::Observed;
    }
private:
    static bool routes(const Frame& f, const Endpoint& a, const Endpoint& b) {
        for (unsigned i=0;i<4;++i) if (f[5+i]!=a[i] || f[9+i]!=b[i]) return false;
        return true;
    }
    Profile profile_{}; Transmission claimed_{};
    State state_=State::Disarmed; Failure failure_=Failure::None;
    std::uint32_t started_=0,duration_=0,lastReportAckMs_=0,notificationSentMs_=0;
    unsigned reports_=0,settings_=0,plans_=0,replies_=0;
    bool pending_=false,assignmentSent_=false,notificationSent_=false;
    bool notificationAccepted_=false,reportAckSent_=false,observedAfterPlans_=false;
};
} // namespace rainpoint::htv213
