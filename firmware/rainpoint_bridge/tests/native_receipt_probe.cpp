// Hardware-independent receipt lifecycle. No RF or NVS driver is linked.
#include "rainpoint_native_receipt.h"
#include <cassert>
#include <iostream>

using namespace rainpoint;
using namespace rainpoint::nativeReceipt;

commandPhase::Frame hex(const std::string& value) {
    commandPhase::Frame frame{};
    for (unsigned i=0;i<frame.size();++i) frame[i]=std::stoul(value.substr(i*2,2),nullptr,16);
    return frame;
}
int main(int argc,char** argv) {
    if (argc!=5) return 2;
    const bool four=std::string(argv[1])=="four";
    const auto request=hex(argv[2]),response=hex(argv[3]),idle=hex(argv[4]);
    Record profile{};
    std::strcpy(profile.epoch,"abababababababababababababababab");
    profile.four=four; profile.next=commandPhase::fromNormalized(request);
    profile.phase=profile.next;
    profile.selector=5;
    profile.reportSelector=(idle[16]<<1U)|(idle[17]>>7U); profile.port=four?2:1;
    profile.centerHz=433920000; profile.power=10; profile.openResidue=0x4f03; profile.closeResidue=0x4f03;
    if (!four) profile.openResidue=trailerResidual(request);
    std::copy(request.begin()+5,request.begin()+9,profile.a.begin());
    std::copy(request.begin()+9,request.begin()+13,profile.b.begin());
    profile.baseline=request;
    const char* command="cdcdcdcdcdcdcdcdcdcdcdcdcdcdcdcd";
    Record durable{};
    unsigned writes=0;
    const auto save=[&](const Record& record) { durable=record; ++writes; return true; };
    Guard guard;
    assert(guard.adopt(profile,save));
    assert(guard.record.stage==Stage::Ready && writes==1);
    assert(guard.adopt(profile,save) && writes==1); // Adoption cannot rewind.
    assert(guard.begin(profile.epoch,command,profile.next,true,60,profile.port,request,14'999,save)==Admission::Denied);
    assert(guard.begin(profile.epoch,command,profile.next,true,60,profile.port,request,15'000,save)==Admission::Transmit);
    assert(durable.stage==Stage::Attempted && durable.frame==request);
    assert(guard.begin(profile.epoch,command,profile.next,true,60,profile.port,request,15'100,save)==Admission::Duplicate);
    assert(writes==2);
    auto wrong=request; wrong[20]^=1;
    assert(guard.begin(profile.epoch,command,profile.next,true,60,profile.port,wrong,15'100,save)==Admission::Denied);
    Guard restarted;
    assert(restarted.restore(durable) && restarted.record.stage==Stage::Uncertain);
    assert(restarted.begin(profile.epoch,command,profile.next,true,60,profile.port,request,40'000,save)==Admission::Duplicate);
    assert(restarted.begin(profile.epoch,"efefefefefefefefefefefefefefefef",(profile.next+1)&63,true,60,profile.port,request,40'000,save)==Admission::Denied);
    assert(guard.observe(response,15'500,save));
    assert(durable.stage==Stage::Accepted);
    assert(!guard.observe(response,15'600,save));
    const auto accepted=durable;
    const char* recovery="12121212121212121212121212121212";
    const char* handback="34343434343434343434343434343434";
    assert(!guard.maintain(profile.epoch,recovery,command,Maintenance::Recover,response,idle,76'000,save));
    assert(guard.observePhysical(idle,30'000));
    assert(!guard.maintain(profile.epoch,recovery,command,Maintenance::Recover,response,idle,76'000,save));
    assert(guard.observePhysical(idle,75'000));
    assert(!guard.maintain(profile.epoch,recovery,recovery,Maintenance::Recover,response,idle,76'000,save));
    auto wrongAck=response; wrongAck[18]^=1;
    assert(!guard.maintain(profile.epoch,recovery,command,Maintenance::Recover,wrongAck,idle,76'000,save));
    assert(guard.maintain(profile.epoch,recovery,command,Maintenance::Recover,response,idle,76'000,save));
    assert(guard.record.next==accepted.next && guard.record.stage==Stage::Accepted);
    const auto recovered=durable;
    auto writeCount=writes;
    assert(guard.maintain(profile.epoch,recovery,command,Maintenance::Recover,response,idle,77'000,save));
    assert(writes==writeCount);
    assert(guard.maintain(profile.epoch,handback,command,Maintenance::Handback,response,idle,77'000,save));
    assert(durable.stage==Stage::Released && !guard.locked());
    assert(durable.legacyCounter==(profile.phase+1U)/2U);
    Guard released;
    assert(released.restore(durable) && !released.locked());
    writeCount=writes;
    assert(released.maintain(profile.epoch,handback,command,Maintenance::Handback,response,idle,100'000,save));
    assert(writes==writeCount); // Lost receipt after restart does not rewind counters.
    assert(!released.adopt(profile,save));
    auto fresh=profile; std::strcpy(fresh.epoch,"56565656565656565656565656565656");
    assert(released.adopt(fresh,save));
    Guard failedMaintenance;
    assert(failedMaintenance.restore(recovered));
    assert(failedMaintenance.observePhysical(idle,75'000));
    assert(!failedMaintenance.maintain(profile.epoch,handback,command,Maintenance::Handback,response,idle,77'000,
        [](const Record&) {return false;}));
    assert(failedMaintenance.locked() && !failedMaintenance.valid);
    auto incompatible=accepted; incompatible.version=1; incompatible.checksum=checksum(incompatible);
    Guard oldVersion; assert(!oldVersion.restore(incompatible) && oldVersion.locked());
    Guard acceptedRestart;
    assert(acceptedRestart.restore(accepted) && acceptedRestart.record.stage==Stage::Accepted);
    commandPhase::Frame close{};
    assert(acceptedRestart.build(profile.next+1,false,0,profile.port,close));
    assert(acceptedRestart.begin(profile.epoch,"efefefefefefefefefefefefefefefef",profile.next+1,false,0,profile.port,close,30'000,save)==Admission::Transmit);
    assert(acceptedRestart.fail(save) && durable.stage==Stage::Uncertain);
    assert(!acceptedRestart.fail(save));
    auto corrupt=durable; corrupt.frame[17]^=1;
    Guard corruptGuard; assert(!corruptGuard.restore(corrupt) && corruptGuard.locked());
    Guard failedCommit;
    assert(failedCommit.adopt(profile,[](const Record&) {return true;}));
    assert(failedCommit.begin(profile.epoch,command,profile.next,true,60,profile.port,request,15'000,
        [](const Record&) {return false;})==Admission::Denied);
    assert(failedCommit.locked() && !failedCommit.valid);
    Guard boundary;
    profile.next=0; assert(boundary.adopt(profile,[](const Record&) {return true;}));
    commandPhase::Frame zero{};
    assert(boundary.build(0,true,60,profile.port,zero));
    assert(boundary.begin(profile.epoch,command,0,true,60,profile.port,zero,40'000,save)==Admission::Denied);
    auto scopedProfile=profile;
    scopedProfile.next=scopedProfile.phase;
    scopedProfile.maximumCommands=2; scopedProfile.qualificationPort=profile.port;
    scopedProfile.qualificationSeconds=120;
    Guard scoped;
    assert(scoped.adopt(scopedProfile,save));
    assert(scoped.begin(profile.epoch,command,profile.phase,true,120,profile.port,request,15'000,save)==Admission::Denied);
    assert(scoped.begin(profile.epoch,command,profile.phase,true,60,four?1:2,request,15'000,save)==Admission::Denied);
    assert(scoped.begin(profile.epoch,command,profile.phase,false,0,profile.port,request,15'000,save)==Admission::Denied);
    assert(scoped.begin(profile.epoch,command,profile.phase,true,60,profile.port,request,15'000,save)==Admission::Transmit);
    assert(scoped.observe(response,15'500,save) && scoped.record.attempts==1);
    const auto scopedAccepted=scoped.record;
    commandPhase::Frame second{};
    assert(scoped.build(profile.phase+1,true,60,profile.port,second));
    const char* secondId="78787878787878787878787878787878";
    assert(scoped.begin(profile.epoch,secondId,profile.phase+1,true,60,profile.port,second,30'000,save)==Admission::Transmit);
    auto secondAck=response;
    secondAck[13]=(secondAck[13]&0xe0U)|((profile.phase+1U)>>1U);
    secondAck[14]=(secondAck[14]&0x7fU)|(((profile.phase+1U)&1U)<<7U);
    writeTrailer(secondAck,trailerResidual(response));
    assert(scoped.observe(secondAck,30'500,save) && scoped.record.attempts==2);
    assert(scoped.begin(profile.epoch,secondId,profile.phase+1,true,60,profile.port,second,130'000,save)==Admission::Duplicate);
    assert(scoped.adopt(scopedProfile,save,100'000) && scoped.qualificationRemaining(100'000)==20'000);
    commandPhase::Frame third{};
    assert(scoped.build(profile.phase+2,true,60,profile.port,third));
    assert(scoped.begin(profile.epoch,recovery,profile.phase+2,true,60,profile.port,third,45'000,save)==Admission::Denied);
    Guard scopedRestart;
    assert(scopedRestart.restore(scopedAccepted));
    assert(scopedRestart.qualificationRemaining(30'000)==0);
    assert(scopedRestart.begin(profile.epoch,secondId,profile.phase+1,true,60,profile.port,second,30'000,save)==Admission::Denied);
    assert(scopedRestart.observePhysical(idle,75'000));
    assert(scopedRestart.maintain(profile.epoch,handback,command,Maintenance::Handback,response,idle,76'000,save));
    Guard expired;
    assert(expired.adopt(scopedProfile,save));
    assert(expired.begin(profile.epoch,command,profile.phase,true,60,profile.port,request,120'000,save)==Admission::Denied);
    std::cout<<"receipt lifecycle passed\n";
}
