#pragma once

#include "rainpoint_valve_command_phase.h"
#include <cstring>
#include <cstddef>

namespace rainpoint::phaseCanary {

// Disabled-by-default installed-valve experiment. The gateway owns admission,
// association selection and durable reservations. This second guard lives on
// the radio: two one-minute transmissions, never retries or phase searches.
enum class Stage : std::uint8_t { Empty, Ready, Awaiting, Between, Complete, Failed, Released, Recovered };
struct Record {
    std::uint32_t magic = 0x50484333;
    char authorization[33]{};
    char commandId[33]{};
    std::array<std::uint8_t, 8> responseRoute{};
    Stage stage = Stage::Empty;
    std::uint8_t phase = 0, count = 0, selector = 0;
    bool acknowledged = false, active = false, idle = false;
    std::uint8_t port = 1; // Uses former padding; legacy records migrate to port 1.
    std::uint8_t fourZone = 0; // Explicit model; never infer it from packet shape.
};
static_assert(sizeof(Record)==88, "phase-trial.1 NVS layout requires explicit migration if changed");
static_assert(offsetof(Record,port)==85, "port must occupy legacy padding, not a saved field");
static_assert(offsetof(Record,fourZone)==86, "model must occupy legacy padding");

inline bool identifier(const char* value) {
    if (!value || std::strlen(value) != 32) return false;
    for (unsigned i=0; i<32; ++i)
        if (!((value[i]>='0' && value[i]<='9') || (value[i]>='a' && value[i]<='f'))) return false;
    return true;
}

class Guard {
public:
    Record record{};
    bool locked() const { return record.stage != Stage::Empty && record.stage != Stage::Released && record.stage != Stage::Recovered; }
    bool listening() const { return record.stage == Stage::Awaiting && !record.acknowledged; }
    bool inFlight() const { return record.stage == Stage::Awaiting; }
    void restore(const Record& saved) {
        record = saved;
        if (record.magic == 0x50484331) { record.port=1; record.fourZone=0; record.magic=0x50484333; }
        if (record.magic == 0x50484332) { record.fourZone=0; record.magic=0x50484333; }
        if (record.magic != 0x50484333 || record.port<1 || record.port>4 || record.fourZone>1 || record.authorization[32] != '\0' ||
                record.commandId[32] != '\0' ||
                static_cast<unsigned>(record.stage)>static_cast<unsigned>(Stage::Recovered) ||
                (record.stage != Stage::Empty && (!identifier(record.authorization) ||
                    !identifier(record.commandId) || record.count<1 || record.count>2 ||
                    record.phase<1 || record.phase>62 || record.selector<1 || record.selector>15))) {
            record = {}; record.stage = Stage::Failed; return;
        }
        // A reboot is not evidence of closure and cannot resume a permission
        // window. Keep the durable lock even if the last run had completed.
        if (locked()) record.stage = Stage::Failed;
    }
    template<class Save>
    bool begin(const char* authorization, const char* commandId, unsigned phase,
               unsigned ordinal, unsigned selector,
               const std::array<std::uint8_t, 8>& route, std::uint32_t now, Save save,
               unsigned port=1, bool fourZone=false) {
        if (!identifier(authorization) || !identifier(commandId) || phase > 62 ||
                phase == 0 || selector == 0 || selector > 15 || port<1 || port>4) return false;
        const bool first = ordinal == 1 && !locked() &&
            std::strcmp(record.authorization, authorization) != 0;
        const bool second = ordinal == 2 && record.stage == Stage::Between &&
            record.count == 1 && std::strcmp(record.authorization, authorization) == 0 &&
            std::strcmp(record.commandId, commandId) != 0 && phase == record.phase + 1U &&
            selector == record.selector && port == record.port && fourZone == bool(record.fourZone) && route == record.responseRoute &&
            now - grantedAt_ <= 3'600'000;
        if ((!first && !second) || (first && phase > 61)) return false;
        auto next = record;
        std::strcpy(next.authorization, authorization);
        std::strcpy(next.commandId, commandId);
        next.responseRoute = route; next.selector = selector; next.port=port; next.fourZone=fourZone;
        next.phase = phase; next.count = ordinal; next.stage = Stage::Awaiting;
        next.acknowledged = next.active = next.idle = false;
        // Persistence precedes the caller's only transmission. Failed storage
        // does not leave an in-memory permission that can accidentally send.
        if (!save(next)) return false;
        record = next; startedAt_ = now;
        if (first) grantedAt_ = now;
        return true;
    }
    void fail() { if (locked()) record.stage = Stage::Failed; }
    bool tick(std::uint32_t now) {
        if (!inFlight()) return false;
        const auto age = now-startedAt_;
        if ((!record.acknowledged && age > 15'000) || age > 125'000) {
            fail(); return true;
        }
        return false;
    }
    bool observe(const commandPhase::Frame& frame, std::uint32_t now) {
        if (!inFlight() || !hasSync(frame) || !hasOrdinaryTrailer(frame) ||
                !std::equal(record.responseRoute.begin(), record.responseRoute.end(), frame.begin()+5)) return false;
        const auto native = [&frame](unsigned i) {
            return static_cast<std::uint8_t>((frame[i+4]<<1U)|(frame[i+5]>>7U));
        };
        if (native(0)!=0x51 || (native(9)&0x40)) return false;
        // Avoid Arduino's word(...) macro, which silently replaces a call to
        // a lambda named word with makeWord(index), discarding the packet data.
        const auto readLe16 = [&native](unsigned i) { return native(i) | (unsigned(native(i+1))<<8U); };
        const auto age = now-startedAt_;
        if (native(10)==0xa1 && (native(11)&31)==13 && commandPhase::fromNormalized(frame)==record.phase) {
            if (tick(now)) return true;
            if (native(12)!=0) { fail(); return true; }
            const bool openMode=native(13)==0x21 ||
                (record.fourZone && native(13)==((record.port<<5U)|1U));
            if (!openMode || readLe16(23)!=60 || readLe16(20)==0 || readLe16(20)>61) return false;
            record.acknowledged = true;
        } else if (native(10)==2 && (native(11)&31)==15 && native(12)==record.selector) {
            if (tick(now)) return true;
            Htv405StateReport fourReport{};
            const bool four=record.fourZone && decodeHtv405StateReport(frame,fourReport);
            const bool active=four ? fourReport.watering && fourReport.zone==record.port
                : native(14)==record.port && native(15)==0x21;
            const bool idle=four ? !fourReport.watering && (fourReport.zone==record.port || fourReport.zone==0)
                : native(14)==record.port && native(15)==0;
            if (active && readLe16(25)==60 && readLe16(22)>0 && readLe16(22)<=61)
                record.active = true;
            else if (record.active && age>=55'000 && idle && readLe16(25)==0 && readLe16(22)==0)
                record.idle = true;
            else return false;
        } else return false;
        if (record.acknowledged && record.active && record.idle)
            record.stage = record.count==2 ? Stage::Complete : Stage::Between;
        return true;
    }
    template<class Save>
    bool recover(const char* authorization, const char* recoveryId, const char* attemptedId,
                 const commandPhase::Frame& ack, const commandPhase::Frame& active,
                 const commandPhase::Frame& idle, std::uint32_t ackAge,
                 std::uint32_t activeAge, std::uint32_t idleAge, Save save) {
        // Explicit repair of the first phase-2 HTV145 trial, not a general
        // counter search, new watering grant, or automatic timeout recovery.
        // Record layout is unchanged so phase-trial.1 NVS remains readable.
        if (record.stage!=Stage::Failed || record.count!=1 || record.phase!=2 || record.port!=1 || record.fourZone ||
                !identifier(authorization) || !identifier(recoveryId) || !identifier(attemptedId) ||
                std::strcmp(record.authorization,authorization)!=0 ||
                std::strcmp(record.commandId,attemptedId)!=0 ||
                std::strcmp(recoveryId,attemptedId)==0 ||
                !(ackAge<activeAge && activeAge<idleAge && ackAge<=15'000 && idleAge<=125'000)) return false;
        Guard proof;
        proof.record=record; proof.record.stage=Stage::Awaiting;
        proof.record.acknowledged=proof.record.active=proof.record.idle=false;
        if (!proof.observe(ack,ackAge) || !proof.record.acknowledged ||
                !proof.observe(active,activeAge) || !proof.record.active ||
                !proof.observe(idle,idleAge) || proof.record.stage!=Stage::Between) return false;
        auto next=record; next.stage=Stage::Recovered;
        std::strcpy(next.commandId,recoveryId);
        // Preserve original observation flags; external evidence is not a
        // claim that this radio recognized these frames during the old run.
        if (!save(next)) return false;
        record=next; return true;
    }
    template<class Save>
    bool release(const char* authorization, Save save) {
        if (record.stage!=Stage::Complete || !identifier(authorization) ||
                std::strcmp(record.authorization,authorization)!=0) return false;
        auto next=record; next.stage=Stage::Released;
        if (!save(next)) return false;
        record=next; return true;
    }
private:
    std::uint32_t startedAt_=0, grantedAt_=0;
};

} // namespace rainpoint::phaseCanary
