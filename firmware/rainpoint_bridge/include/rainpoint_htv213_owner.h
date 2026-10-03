#pragma once
#include "rainpoint_htv213_control.h"

namespace rainpoint::htv213Owner {
// The retained configuration comes from the association, not enrollment's
// captured defaults. Transport and reply data must identify the same device.
inline bool matches(const htv213::Profile& p, const valveConfiguration::Association& a) {
    auto paired=p.factory; paired[0]|=128;
    return htv213::valid(p) && a.model==valveConfiguration::Model::Htv213 &&
        a.factoryEndpoint==p.factory && a.requestRouteA==p.controller &&
        a.requestRouteB==paired && a.address==p.address && a.selector==p.selector &&
        a.timingKnown && a.timingRaw==p.timingRaw && a.configurationRevision!=0;
}

inline bool prepareReply(const htv213::Profile& p,
                         const valveConfiguration::Association& a,
                         const htv213::Frame& frame, const htv213::Context& context,
                         bool rejoinEnabled, htv213::Transmission& tx) {
    tx={};
    if (!matches(p,a)) return false;
    // Summary ACKs share the owner, but are not configuration requests.
    if (htv213::native(frame)[10]==4)
        return htv213Control::prepareReportAck(p,frame,a.configurationRevision,context,tx);
    valveConfiguration::Reply reply{};
    bool ready=valveConfiguration::prepareReply(a,frame,context,reply)==valveConfiguration::Result::Ready;
    if (!ready && rejoinEnabled)
        ready=valveConfiguration::prepareRetainedAssignment(a,frame,context,reply)==valveConfiguration::Result::Ready;
    if (!ready) return false;
    const auto replyHz=reply.command==0x81 ?
        htv213::assignmentReplyHz(p,reply.assignmentReplySelector) : p.routineHz;
    if (!replyHz || !htv213::encode(p,reply.command,reply.phase,reply.data.data(),reply.length,tx.frame)) return false;
    tx.command=reply.command; tx.port=reply.port; tx.centerHz=replyHz;
    return true;
}

} // namespace rainpoint::htv213Owner
