#pragma once

#include "rainpoint_valve_command_phase.h"
#include <cstring>

namespace rainpoint::nativeReceipt {

// Candidate only. One exclusive association per radio until multi-owner
// scheduling is separately qualified. No startup transmission or erase/reset.
enum class Stage : std::uint8_t { Empty, Ready, Attempted, Accepted, Uncertain, Released };
enum class Maintenance : std::uint8_t { None, Recover, Handback };
enum class Admission { Denied, Duplicate, Transmit };
struct Record {
    std::uint32_t version=2, checksum=0, centerHz=0;
    char epoch[33]{}, commandId[33]{}, maintenanceId[33]{};
    std::array<std::uint8_t,4> a{}, b{};
    commandPhase::Frame baseline{}, frame{};
    std::uint16_t openResidue=0, closeResidue=0, seconds=0;
    std::int8_t power=0;
    std::uint8_t next=0, phase=0, port=0, selector=0, reportSelector=0;
    Stage stage=Stage::Empty;
    Maintenance maintenance=Maintenance::None;
    std::uint8_t legacyCounter=0;
    std::uint8_t maximumCommands=0, attempts=0, qualificationPort=0;
    std::uint16_t qualificationSeconds=0;
    bool four=false, open=false;
};
inline bool id(const char* value) {
    if (!value) return false;
    for (unsigned i=0;i<32;++i)
        if (!((value[i]>='0' && value[i]<='9') || (value[i]>='a' && value[i]<='f'))) return false;
    return value[32]=='\0';
}
inline std::uint32_t checksum(Record record) {
    std::uint32_t hash=2166136261U;
    const auto byte=[&](std::uint8_t value) { hash=(hash^value)*16777619U; };
    const auto number=[&](std::uint32_t value) { for (unsigned i=0;i<4;++i) byte(value>>(i*8U)); };
    number(record.version); number(record.centerHz);
    for (auto value:record.epoch) byte(value);
    for (auto value:record.commandId) byte(value);
    for (auto value:record.maintenanceId) byte(value);
    for (auto value:record.a) byte(value);
    for (auto value:record.b) byte(value);
    for (auto value:record.baseline) byte(value);
    for (auto value:record.frame) byte(value);
    number(record.openResidue); number(record.closeResidue); number(record.seconds);
    byte(record.power); byte(record.next); byte(record.phase); byte(record.port);
    byte(record.selector); byte(record.reportSelector); byte(static_cast<unsigned>(record.stage)); byte(record.four); byte(record.open);
    byte(static_cast<unsigned>(record.maintenance)); byte(record.legacyCounter);
    byte(record.maximumCommands); byte(record.attempts); byte(record.qualificationPort); number(record.qualificationSeconds);
    return hash;
}
class Guard {
public:
    Record record{};
    std::uint32_t attemptedAt=0;
    bool valid=true;
    bool physicalSeen=false, physicalIdle=false;
    std::uint32_t physicalAt=0;
    commandPhase::Frame physicalFrame{};
    bool qualificationLive=false;
    std::uint32_t qualifiedAt=0;
    std::uint32_t qualificationRemaining(std::uint32_t now) const {
        if (!record.maximumCommands || !qualificationLive) return 0;
        const auto lifetime=unsigned(record.qualificationSeconds)*1000U;
        return now-qualifiedAt>=lifetime?0:lifetime-(now-qualifiedAt);
    }
    bool locked() const { return !valid || (record.stage!=Stage::Empty && record.stage!=Stage::Released); }
    bool pending() const { return record.stage==Stage::Attempted; }
    template<class Save> bool persist(Record next, Save save) {
        next.checksum=checksum(next);
        if (!save(next)) { valid=false; record.stage=Stage::Uncertain; return false; }
        record=next; return true;
    }
    bool restore(const Record& saved) {
        if (saved.version!=2 || saved.checksum!=checksum(saved) ||
                !id(saved.epoch) || !id(saved.commandId) || saved.next>63 || saved.phase>63 ||
                saved.stage==Stage::Empty || static_cast<unsigned>(saved.stage)>5 ||
                static_cast<unsigned>(saved.maintenance)>2 || saved.legacyCounter>31 ||
                (saved.maintenance!=Maintenance::None && !id(saved.maintenanceId)) ||
                saved.maximumCommands>2 || saved.attempts>saved.maximumCommands ||
                (saved.maximumCommands && (saved.qualificationSeconds<120 || saved.qualificationSeconds>900 ||
                    saved.qualificationPort<1 || saved.qualificationPort>(saved.four?4U:1U))) ||
                (saved.stage==Stage::Released && saved.maintenance!=Maintenance::Handback)) {
            valid=false; return false;
        }
        record=saved;
        physicalSeen=false; attemptedAt=0; qualificationLive=false;
        // An attempted RF command is never replayable after MCU restart.
        if (record.stage==Stage::Attempted) record.stage=Stage::Uncertain;
        return true;
    }
    template<class Save> bool adopt(Record next, Save save, std::uint32_t now=0) {
        if (!valid || !id(next.epoch) || next.next>63) return false;
        if (next.maximumCommands>2 || next.attempts ||
                (next.maximumCommands && (next.qualificationSeconds<120 || next.qualificationSeconds>900 ||
                    next.qualificationPort<1 || next.qualificationPort>(next.four?4U:1U)))) return false;
        if (record.stage==Stage::Released && std::strcmp(next.epoch,record.epoch)==0) return false;
        if (locked()) return std::strcmp(next.epoch,record.epoch)==0 &&
            next.a==record.a && next.b==record.b && next.baseline==record.baseline;
        next.stage=Stage::Ready;
        std::strcpy(next.commandId,next.epoch);
        if (!persist(next,save)) return false;
        qualifiedAt=now; qualificationLive=true;
        return true;
    }
    bool build(unsigned phase, bool open, unsigned seconds, unsigned port, commandPhase::Frame& frame) const {
        if (phase>63 || port<1 || port>(record.four?4U:1U)) return false;
        if (record.four) return commandPhase::buildHtv405({record.a,record.b},phase,open,seconds,
            port,record.selector,0x4f03,frame);
        return commandPhase::buildHtv145({record.a,record.b},phase,open,seconds,
            open?record.openResidue:record.closeResidue,frame);
    }
    template<class Save> Admission begin(const char* epoch, const char* commandId,
            unsigned phase, bool open, unsigned seconds, unsigned port,
            const commandPhase::Frame& frame, std::uint32_t now, Save save) {
        if (!valid || !id(epoch) || !id(commandId) || std::strcmp(epoch,record.epoch)!=0) return Admission::Denied;
        if (std::strcmp(commandId,record.commandId)==0)
            return frame==record.frame && phase==record.phase && open==record.open &&
                seconds==record.seconds && port==record.port ? Admission::Duplicate : Admission::Denied;
        if (record.maximumCommands && (!qualificationRemaining(now) || !open || seconds!=60 ||
                port!=record.qualificationPort || record.attempts>=record.maximumCommands)) return Admission::Denied;
        // Rollover is source-supported but not admitted before model dry tests.
        if ((record.stage!=Stage::Ready && record.stage!=Stage::Accepted) ||
                phase!=record.next || phase==0 || now-attemptedAt<15'000) return Admission::Denied;
        commandPhase::Frame expected{};
        if (!build(phase,open,seconds,port,expected) || expected!=frame) return Admission::Denied;
        Record next=record;
        std::strcpy(next.commandId,commandId);
        next.frame=frame; next.phase=phase; next.next=(phase+1U)&63U;
        next.open=open; next.port=port; next.seconds=seconds; next.stage=Stage::Attempted;
        next.maintenance=Maintenance::None; next.maintenanceId[0]='\0';
        if (next.maximumCommands) ++next.attempts;
        if (!persist(next,save)) return Admission::Denied;
        physicalSeen=false;
        attemptedAt=now; return Admission::Transmit;
    }
    template<class Save> bool fail(Save save) {
        if (!pending()) return false;
        auto next=record; next.stage=Stage::Uncertain; persist(next,save); return true;
    }
    template<class Save> bool observe(const commandPhase::Frame& frame, std::uint32_t now, Save save) {
        commandPhase::ResultEnvelope result;
        if (!pending() || now-attemptedAt>15'000 ||
                !commandPhase::decodeResultEnvelope(frame,result) || result.phase!=record.phase) return false;
        auto a=record.b;
        if (record.four) a[0]|=128U;
        if (!std::equal(a.begin(),a.end(),frame.begin()+5) ||
                !std::equal(record.a.begin(),record.a.end(),frame.begin()+9)) return false;
        if (result.result) return fail(save);
        const auto native=[&](unsigned i) { return static_cast<std::uint8_t>((frame[i+4]<<1U)|(frame[i+5]>>7U)); };
        const auto secondsAt=[&](unsigned i) { return static_cast<unsigned>(native(i))|(static_cast<unsigned>(native(i+1))<<8U); };
        const unsigned mode=native(13);
        const unsigned expected=(record.four?record.port<<5U:0x20U)|unsigned(record.open);
        if (mode!=expected && mode!=(0x20U|unsigned(record.open))) return false;
        if (record.open && (secondsAt(23)!=record.seconds || secondsAt(20)<1 || secondsAt(20)>record.seconds+1U)) return false;
        auto next=record; next.stage=Stage::Accepted; persist(next,save); return true;
    }
    bool observePhysical(const commandPhase::Frame& frame, std::uint32_t now) {
        if (!locked() || !hasSync(frame) || !hasOrdinaryTrailer(frame)) return false;
        const auto native=[&](unsigned i) { return static_cast<std::uint8_t>((frame[i+4]<<1U)|(frame[i+5]>>7U)); };
        auto a=record.b; if (record.four) a[0]|=128U;
        if (native(0)!=0x51 || (native(9)&0x40U) || native(10)!=2 || (native(11)&31U)!=15 ||
                native(12)!=record.reportSelector || !std::equal(a.begin(),a.end(),frame.begin()+5) ||
                !std::equal(record.a.begin(),record.a.end(),frame.begin()+9)) return false;
        bool idle=false;
        if (record.four) {
            Htv405StateReport report{};
            if (!decodeHtv405StateReport(frame,report)) return false;
            idle=!report.watering && (report.zone==0 || report.zone==record.port);
        } else {
            if (native(14)!=1 || (native(15)!=0 && native(15)!=0x21)) return false;
            idle=native(15)==0;
        }
        const auto secondsAt=[&](unsigned i) { return unsigned(native(i))|(unsigned(native(i+1))<<8U); };
        if (idle && (secondsAt(22) || secondsAt(25))) return false;
        physicalSeen=true; physicalIdle=idle; physicalAt=now; physicalFrame=frame;
        return true;
    }
    template<class Save> bool maintain(const char* epoch, const char* operationId, const char* attemptedId,
            Maintenance kind, const commandPhase::Frame& result, const commandPhase::Frame& idle,
            std::uint32_t now, Save save) {
        if (!valid || !id(epoch) || !id(operationId) || !id(attemptedId) ||
                std::strcmp(epoch,record.epoch)!=0 || std::strcmp(attemptedId,record.commandId)!=0 ||
                (kind!=Maintenance::Recover && kind!=Maintenance::Handback)) return false;
        if (id(record.maintenanceId) && std::strcmp(operationId,record.maintenanceId)==0)
            return kind==record.maintenance; // Never reapply a counter after lost receipt/restart.
        if (record.stage!=Stage::Accepted || !physicalSeen || !physicalIdle || idle!=physicalFrame ||
                now-physicalAt>120'000 || physicalAt<attemptedAt ||
                (record.open && attemptedAt && physicalAt-attemptedAt<unsigned(record.seconds)*1000U)) return false;
        auto verifier=*this;
        verifier.record.stage=Stage::Attempted; verifier.attemptedAt=now;
        if (!verifier.observe(result,now,[](const Record&) {return true;}) || verifier.record.stage!=Stage::Accepted)
            return false;
        // Only return to the qualified legacy odd-OPEN/even-CLOSE recipes.
        // Odd native CLOSE and rollover need separate RF qualification.
        if (kind==Maintenance::Handback && (record.phase>62 || (!record.open && (record.phase&1U)))) return false;
        auto next=record;
        std::strcpy(next.maintenanceId,operationId); next.maintenance=kind;
        if (kind==Maintenance::Handback) {
            next.legacyCounter=(record.phase+1U)/2U;
            next.stage=Stage::Released;
        }
        return persist(next,save);
    }
};
} // namespace rainpoint::nativeReceipt
