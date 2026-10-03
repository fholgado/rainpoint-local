#pragma once
#include "rainpoint_htv213_control.h"

namespace rainpoint::htv213Owner {
// Reply-only retained association. Never allocates a command phase or opens a
// valve. The authenticated gateway owns admission, persistence and revocation.
inline bool prepareReply(const htv213::Profile& p, const htv213::Frame& frame,
                         const htv213::Context& context, bool rejoinEnabled,
                         htv213::Transmission& tx) {
    if (!htv213::valid(p)) return false;
    if (htv213Control::prepareReportAck(p,frame,2,context,tx)) return true;
    valveConfiguration::Association a{};
    a.model=valveConfiguration::Model::Htv213;
    a.requestRouteA=p.controller; a.requestRouteB=p.factory; a.requestRouteB[0]|=128;
    a.factoryEndpoint=p.factory; a.address=p.address; a.selector=p.selector;
    a.timingKnown=true; a.timingRaw=p.timingRaw; a.configurationRevision=2;
    for (unsigned i=0;i<2;++i) {
        a.ports[i].settingsKnown=true; a.ports[i].settings=p.settings;
        a.ports[i].emptyPlanKnown=true;
    }
    valveConfiguration::Reply reply{};
    bool ready=valveConfiguration::prepareReply(a,frame,context,reply)==valveConfiguration::Result::Ready;
    if (!ready && rejoinEnabled)
        ready=valveConfiguration::prepareRetainedAssignment(a,frame,context,reply)==valveConfiguration::Result::Ready;
    if (!ready) return false;
    const auto replyHz = reply.command == 0x81 ?
        htv213::assignmentReplyHz(p,reply.assignmentReplySelector) : p.routineHz;
    if (!replyHz) return false; // Unqualified announcement selectors stay silent.
    tx={};
    if (!htv213::encode(p,reply.command,reply.phase,reply.data.data(),reply.length,tx.frame)) return false;
    tx.command=reply.command; tx.port=reply.port; tx.centerHz=replyHz;
    return true;
}
} // namespace rainpoint::htv213Owner
