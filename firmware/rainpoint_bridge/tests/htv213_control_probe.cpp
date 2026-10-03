#include <iomanip>
#include <iostream>
#include <string>
#include "rainpoint_htv213_control.h"
#include "rainpoint_htv213_owner.h"

int main() {
    using namespace rainpoint::htv213Control;
    Profile profile{};
    profile.factory={{0x11,0x55,0x66,0x77}};
    profile.controller={{0xa2,0x44,0x66,0x88}}; profile.companion={{0x22,0x44,0x66,0x88}};
    profile.address=2; profile.selector=11; profile.notificationPhase=2; profile.timingRaw=480;
    profile.initialHz=434351500; profile.routineHz=434241500;
    profile.replyDelayUs=49000; profile.notificationDelayMs=1000;
    profile.settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
    rainpoint::valveConfiguration::Association retained{};
    retained.model=rainpoint::valveConfiguration::Model::Htv213;
    retained.requestRouteA=profile.controller; retained.requestRouteB=profile.factory; retained.requestRouteB[0]|=128;
    retained.factoryEndpoint=profile.factory; retained.address=profile.address; retained.selector=profile.selector;
    retained.timingKnown=true; retained.timingRaw=profile.timingRaw; retained.configurationRevision=2;
    for (unsigned i=0;i<2;++i) {
        retained.ports[i].settingsKnown=true; retained.ports[i].settings=profile.settings;
        retained.ports[i].emptyPlanKnown=true;
    }
    rainpoint::htv213::Context context{}; context.timeKnown=true; context.time[4]=1;
    Trial trial;
    std::string op;
    while (std::cin>>op) {
        unsigned now=0; std::cin>>now;
        Transmission tx{}; bool result=false; Observation observation{};
        if (op=="config") {
            unsigned revision,port,known,empty; std::string settings;
            std::cin>>revision>>port>>settings>>known>>empty;
            if (port<1 || port>2 || settings.size()!=28) return 4;
            retained.configurationRevision=revision;
            auto& config=retained.ports[port-1];
            for (unsigned i=0;i<14;++i) config.settings[i]=std::stoul(settings.substr(i*2,2),nullptr,16);
            config.settingsKnown=known; config.emptyPlanKnown=empty; result=true;
        } else if (op=="start" || op=="build") {
            unsigned port,seconds,phase; std::cin>>port>>seconds>>phase;
            result=op=="start" ? trial.start(profile,port,seconds,phase,now,tx) :
                prepareCommand(profile,port,phase,seconds!=0,seconds,tx);
        } else if (op=="close") { unsigned phase; std::cin>>phase; result=trial.close(phase,now,tx); }
        else if (op=="finish") { unsigned sent; std::cin>>sent; trial.finishTransmit(sent,now); }
        else if (op=="cancel") trial.cancel();
        else if (op=="tick") trial.tick(now);
        else if (op=="listen") result=trial.listening(now);
        else if (op=="observe" || op=="ack" || op=="decode" || op=="tail" || op=="owner_ack" || op=="owner_rejoin") {
            std::string raw; std::cin>>raw; Frame frame{};
            if (raw.size()!=frame.size()*2) return 2;
            for (unsigned i=0;i<frame.size();++i) frame[i]=std::stoul(raw.substr(i*2,2),nullptr,16);
            if (op=="observe") result=trial.observe(frame,now);
            else if (op=="tail") result=nativeTailSymbol(frame);
            else if (op=="owner_ack") result=rainpoint::htv213Owner::prepareReply(profile,retained,frame,context,false,tx);
            else if (op=="owner_rejoin") result=rainpoint::htv213Owner::prepareReply(profile,retained,frame,context,true,tx);
            else if (op=="ack") result=prepareReportAck(profile,frame,2,context,tx);
            else result=decode(profile,frame,observation);
        } else return 3;
        std::cout<<result<<' '<<unsigned(trial.state())<<' '<<trial.phase()<<' '
            <<trial.openAcknowledged()<<' '<<trial.closeAcknowledged()<<' '
            <<trial.openReported()<<' '<<trial.idleReported()<<' '
            <<trial.summaryReceived()<<' '<<trial.elapsed()<<' '
            <<unsigned(observation.kind)<<' '<<observation.port<<' '
            <<observation.remaining<<' '<<observation.requested<<' '
            <<tx.centerHz<<' '<<tx.wakeSymbols<<' ';
        if (tx.command) {
            for (auto byte:tx.frame) std::cout<<std::hex<<std::setfill('0')<<std::setw(2)<<unsigned(byte);
            std::cout<<std::dec;
        } else std::cout<<'-';
        std::cout<<'\n';
    }
}
