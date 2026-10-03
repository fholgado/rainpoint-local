#include <iostream>
#include <iomanip>
#include <string>
#include "rainpoint_htv213_pairing.h"

template<std::size_t N> bool hex(const std::string& s, std::array<std::uint8_t,N>& out) {
    if (s.size()!=N*2) return false;
    try { for (std::size_t i=0;i<N;++i) out[i]=std::stoul(s.substr(i*2,2),nullptr,16); }
    catch (...) { return false; } return true;
}
int main() {
    using namespace rainpoint::htv213;
    Profile p{};
    hex("11556677",p.factory); hex("a2446688",p.controller); hex("22446688",p.companion);
    p.address=2; p.selector=11; p.notificationPhase=2; p.timingRaw=480;
    p.initialHz=434351500; p.routineHz=434241500; p.replyDelayUs=49000; p.notificationDelayMs=1000;
    p.settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
    Session s; Context ctx{}; ctx.timeKnown=true; ctx.unitsKnown=true;
    std::string op;
    while (std::cin>>op) {
        unsigned now=0; std::cin>>now;
        Transmission out{}; bool claimed=false;
        if (op=="profile") {
            unsigned selector; std::cin>>p.initialHz>>p.routineHz>>selector;
            p.selector=selector;
        }
        else if (op=="arm") claimed=s.arm(p,now,300000);
        else if (op=="discover") { auto discovery=p; discovery.factory={}; claimed=s.armDiscovery(discovery,now,300000); }
        else if (op=="bound") claimed=rainpoint::valveConfiguration::nonzero(s.profile().factory);
        else if (op=="ack-proof") { claimed=s.notificationAccepted(); out.command=0xa0; out.frame=s.notificationAck(); }
        else if (op=="completion-proof") { claimed=s.state()==State::Observed; out.command=2; out.frame=s.completionReport(); }
        else if (op=="frame") { std::string raw; Frame f{}; std::cin>>raw; if (!hex(raw,f)) return 2; claimed=s.claim(f,ctx,now,out); }
        else if (op=="notification") claimed=s.claimNotification(now,out);
        else if (op=="listening") claimed=s.notificationResponseWindow(now);
        else if (op=="finish") { unsigned sent; std::cin>>sent; s.finish(sent,now); }
        else if (op=="tick") s.tick(now);
        else if (op=="disconnect") s.tick(now,false);
        else if (op=="cancel") s.cancel();
        else return 2;
        std::cout<<claimed<<' '<<int(s.state())<<' '<<int(s.failure())<<' '
            <<s.reports()<<' '<<s.settingsSent()<<' '<<s.plansSent()<<' '
            <<s.notificationAccepted()<<' '<<s.repliesSent()<<' '<<out.centerHz<<' ';
        if (out.command) {
            for (auto byte:out.frame) std::cout<<std::hex<<std::setfill('0')<<std::setw(2)<<unsigned(byte);
            std::cout<<std::dec;
        } else std::cout<<'-';
        std::cout<<'\n';
    }
}
