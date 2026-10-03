#pragma once

#include "rainpoint_htv213_pairing.h"

namespace rainpoint::htv213Control {

// Compile-gated dry-trial candidate, never a production authorization.
// The caller must durably reserve each master phase before TX.
using Profile = htv213::Profile;
using Frame = htv213::Frame;
using Transmission = htv213::Transmission;
constexpr unsigned kMaximumTrialSeconds = 3600;
constexpr unsigned kResponseWindowMs = 1500;
constexpr unsigned kCompletionGraceMs = 60000;

inline std::uint8_t nativeTailSymbol(const Frame& frame) {
    const auto payload=htv213::native(frame);
    std::uint16_t crc=0xa8a8;
    for (auto value:payload) {
        crc^=static_cast<std::uint16_t>(value)<<8;
        for (unsigned bit=0;bit<8;++bit)
            crc=static_cast<std::uint16_t>((crc<<1)^((crc&0x8000)?0x1021:0));
    }
    return crc&1U;
}

inline bool prepareCommand(const Profile& profile, unsigned port, unsigned phase,
                           bool open, unsigned seconds, Transmission& tx) {
    tx = {};
    if (port < 1 || port > 2 || phase > 63 ||
        (open ? seconds < 1 || seconds > kMaximumTrialSeconds : seconds != 0)) return false;
    const std::uint8_t data[]{static_cast<std::uint8_t>(port), 2,
        static_cast<std::uint8_t>(open), static_cast<std::uint8_t>(seconds),
        static_cast<std::uint8_t>(seconds >> 8)};
    if (!htv213::encode(profile, 0x21, phase, data, open ? 5 : 3, tx.frame)) return false;
    tx.command = 0x21; tx.port = port; tx.centerHz = profile.routineHz;
    tx.wakeSymbols = 2400;
    return true;
}

enum class Kind { None, Result, State, Summary };
struct Observation {
    Kind kind = Kind::None;
    unsigned phase = 0, port = 0, result = 0, mode = 0;
    unsigned remaining = 0, requested = 0, elapsed = 0;
};

inline unsigned word(const std::uint8_t* data) { return data[0] | (unsigned(data[1]) << 8); }

inline bool decode(const Profile& profile, const Frame& frame, Observation& out) {
    out = {};
    if (!htv213::valid(profile) || !hasSync(frame) || !hasOrdinaryTrailer(frame)) return false;
    auto paired = profile.factory; paired[0] |= 128;
    for (unsigned i=0; i<4; ++i)
        if (frame[5+i] != profile.controller[i] || frame[9+i] != paired[i]) return false;
    const auto n = htv213::native(frame);
    if (n[0] != 0x51 || (n[9] & 0x40)) return false;
    const unsigned command=n[10], length=n[11]&31;
    const auto* d=n.data()+12;
    out.phase=n[9]&63;
    if (command==0xa1) {
        // Negative-result shape is not qualified: do not invent a rejection
        // decoder. Only the captured thirteen-byte successful result is used.
        if (length!=13 || d[0]!=0 || (d[1]!=0x21 && d[1]!=0x20)) return false;
        out.kind=Kind::Result; out.result=d[0]; out.mode=d[1];
        out.remaining=word(d+8); out.requested=word(d+11);
        // a1 has no port field. Exactly one outstanding command supplies it.
    } else if (command==2) {
        if (length!=15 || d[0]!=profile.selector || d[2]<1 || d[2]>2 ||
            (d[3]!=0 && d[3]!=0x21)) return false;
        out.kind=Kind::State; out.port=d[2]; out.mode=d[3];
        out.remaining=word(d+10); out.requested=word(d+13);
    } else if (command==4) {
        if (length!=14 || d[0]!=profile.selector || d[1]<1 || d[1]>2 ||
            d[2]!=1 || d[7]!=0x21) return false;
        out.kind=Kind::Summary; out.port=d[1]; out.elapsed=word(d+12);
    } else return false;
    return true;
}

inline bool prepareReportAck(const Profile& profile, const Frame& frame,
                             std::uint8_t revision, const htv213::Context& context,
                             Transmission& tx) {
    tx={};
    Observation observed{};
    if (revision==0 || !decode(profile,frame,observed)) return false;
    valveConfiguration::Reply reply{};
    if (observed.kind==Kind::State) {
        valveConfiguration::Association association{};
        association.model=valveConfiguration::Model::Htv213;
        association.requestRouteA=profile.controller;
        association.requestRouteB=profile.factory; association.requestRouteB[0]|=128;
        association.selector=profile.selector; association.configurationRevision=revision;
        if (valveConfiguration::prepareReply(association,frame,context,reply)!=
            valveConfiguration::Result::Ready) return false;
    } else if (observed.kind==Kind::Summary) {
        reply.command=0x84; reply.phase=observed.phase; reply.port=observed.port;
        reply.length=1; reply.data[0]=0;
    } else return false; // Never acknowledge an acknowledgement.
    if (!htv213::encode(profile,reply.command,reply.phase,reply.data.data(),reply.length,tx.frame)) return false;
    tx.command=reply.command; tx.port=reply.port; tx.centerHz=profile.routineHz;
    return true;
}

enum class State { Idle, Transmitting, AwaitingResponse, OpenConfirmed, CloseAwaitingResponse,
                   CloseConfirmed, Complete, Uncertain, Overdue, Cancelled };

class Trial {
public:
    bool start(const Profile& profile, unsigned port, unsigned seconds, unsigned phase,
               std::uint32_t now, Transmission& tx) {
        if (state_!=State::Idle || !prepareCommand(profile,port,phase,true,seconds,tx)) return false;
        profile_=profile; port_=port; seconds_=seconds; phase_=phase; started_=now;
        state_=State::Transmitting; return true;
    }
    // An explicit early-stop request, never triggered by a timeout or startup.
    // Its independent phase is supplied by the durable caller, not report RX.
    bool close(unsigned phase, std::uint32_t now, Transmission& tx) {
        tick(now);
        if (state_!=State::OpenConfirmed || closeSent_ || idleSeen_ || phase>63 || phase==phase_ ||
            !prepareCommand(profile_,port_,phase,false,0,tx)) return false;
        phase_=phase; closeSent_=true; state_=State::Transmitting; return true;
    }
    void finishTransmit(bool sent, std::uint32_t now) {
        if (state_!=State::Transmitting) return;
        responseAt_=now;
        state_=sent ? (closeSent_ ? State::CloseAwaitingResponse : State::AwaitingResponse) : State::Uncertain;
    }
    bool listening(std::uint32_t now) const {
        return (state_==State::AwaitingResponse || state_==State::CloseAwaitingResponse) &&
            now-responseAt_<kResponseWindowMs;
    }
    void tick(std::uint32_t now) {
        if (state_==State::Idle || state_==State::Complete || state_==State::Cancelled) return;
        if ((state_==State::AwaitingResponse || state_==State::CloseAwaitingResponse) &&
            now-responseAt_>=kResponseWindowMs) state_=State::Uncertain;
        if (now-started_>=seconds_*1000U+kCompletionGraceMs) state_=State::Overdue;
    }
    void cancel() { if (state_!=State::Complete && state_!=State::Idle) state_=State::Cancelled; }
    bool observe(const Frame& frame, std::uint32_t now) {
        tick(now);
        if (state_==State::Idle || state_==State::Transmitting || state_==State::Complete ||
            state_==State::Cancelled || state_==State::Overdue) return false;
        Observation observation{};
        if (!decode(profile_,frame,observation)) return false;
        if (observation.kind==Kind::Result) {
            if (observation.phase!=phase_ || observation.requested!=seconds_) return false;
            if (!closeSent_ && observation.mode==0x21 && observation.remaining>0 &&
                observation.remaining<=seconds_+1) {
                openAck_=true; state_=State::OpenConfirmed;
            } else if (closeSent_ && observation.mode==0x20 && observation.remaining==0) {
                closeAck_=true; state_=State::CloseConfirmed;
            } else return false;
        } else {
            if (observation.port!=port_) return false;
            if (observation.kind==Kind::State) {
                if (observation.mode==0x21 && observation.requested==seconds_ && observation.remaining>0 &&
                    observation.remaining<=seconds_+1) openReport_=true;
                else if (observation.mode==0 && observation.remaining==0 && observation.requested==0 &&
                         openAck_) idleSeen_=true;
                else return false;
            } else if (openAck_ && idleSeen_ && observation.elapsed<=seconds_ &&
                       (closeSent_ ? closeAck_ : observation.elapsed==seconds_)) {
                summarySeen_=true; elapsed_=observation.elapsed;
            } else return false;
        }
        if (openAck_ && idleSeen_ && summarySeen_ && (!closeSent_ || closeAck_)) state_=State::Complete;
        return true;
    }
    State state() const { return state_; }
    unsigned phase() const { return phase_; }
    bool openAcknowledged() const { return openAck_; }
    bool closeAcknowledged() const { return closeAck_; }
    bool openReported() const { return openReport_; }
    bool idleReported() const { return idleSeen_; }
    bool summaryReceived() const { return summarySeen_; }
    unsigned elapsed() const { return elapsed_; }
private:
    Profile profile_{};
    State state_=State::Idle;
    unsigned port_=0,seconds_=0,phase_=0,elapsed_=0;
    std::uint32_t started_=0,responseAt_=0;
    bool closeSent_=false,openAck_=false,closeAck_=false,openReport_=false;
    bool idleSeen_=false,summarySeen_=false;
};
} // namespace rainpoint::htv213Control
