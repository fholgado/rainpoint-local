// Included only by the opt-in dry-test build, inside main.cpp's namespace.
// No production valve/sensor session or ownership table is shared.
rainpoint::htv213::Session htv213Session;
String htv213CommandId;
rainpoint::PairingLocalDateTime htv213Clock{};
std::uint32_t htv213ClockAt=0;
std::int8_t htv213Power=0;
bool htv213ListeningForNotification=false;

bool htv213Armed() { return htv213Session.state()==rainpoint::htv213::State::Armed; }

void reportHtv213() {
    using State=rainpoint::htv213::State;
    const auto state=htv213Session.state();
    String line="{\"type\":\"htv213_pairing_status\",\"node_id\":\"";
    line+=wifiTransport.nodeId(); line+="\",\"command_id\":\""; line+=htv213CommandId;
    line+="\",\"state\":\"";
    line+=state==State::Armed ? "armed" : state==State::Observed ? "observed" :
        state==State::Failed ? "failed" : "disarmed";
    line+="\",\"reports\":"; line+=htv213Session.reports();
    line+=",\"settings_sent\":"; line+=htv213Session.settingsSent();
    line+=",\"plans_sent\":"; line+=htv213Session.plansSent();
    line+=",\"replies_sent\":"; line+=htv213Session.repliesSent();
    line+=",\"failure\":"; line+=static_cast<unsigned>(htv213Session.failure());
    line+=",\"factory_endpoint\":\"";
    line+=hexString(htv213Session.profile().factory.data(),4); line+="\"";
    line+=",\"notification_accepted\":";
    line+=htv213Session.notificationAccepted() ? "true" : "false";
    line+=",\"awaiting_confirmation\":";
    line+=htv213Session.awaitingConfirmation() ? "true" : "false";
    line+=",\"notification_ack_frame\":\"";
    line+=hexString(htv213Session.notificationAck().data(),rainpoint::kFrameBytes); line+="\"";
    line+=",\"completion_frame\":\"";
    line+=hexString(htv213Session.completionReport().data(),rainpoint::kFrameBytes); line+="\"";
    line+="}"; emitLine(line);
}

void finishHtv213(bool sent, bool notification=false) {
    htv213Session.finish(sent,millis());
    if (sent && notification && htv213Armed()) {
        // Stock a0 replies are on the hub command carrier, not the lower
        // addressed-report carrier. Return after the reply or bounded window.
        htv213ListeningForNotification=primaryRadio.setReceiveFrequency(htv213Session.profile().routineHz);
        if (!htv213ListeningForNotification)
            htv213Session.cancel(rainpoint::htv213::Failure::Receiver);
    }
    if (!htv213Armed()) restoreScanningAfterPairing();
    reportHtv213();
}

bool handleHtv213Command(const String& type,const String& command,const String& id) {
    if (type=="htv213_pairing_cancel") {
        if (id!=htv213CommandId) reportNetworkCommandError(id,"htv213_session_changed");
        else { htv213Session.cancel(); restoreScanningAfterPairing(); reportHtv213(); }
        return true;
    }
    const bool discover=type=="htv213_enrollment_start";
    if (type!="htv213_pairing_start" && !discover) {
        if (!htv213Armed()) return false;
        // Cancellation must unwind before a radio mode change or reboot.
        if (type=="rf_mode_set" || type=="node_reboot") {
            htv213Session.cancel(); restoreScanningAfterPairing(); reportHtv213(); return false;
        }
        reportNetworkCommandError(id,"htv213_experiment_busy"); return true;
    }
    if (!wifiTransport.authenticated() || !radiosHealthy || !rfMaintenance.transmitAllowed() ||
        htv213Armed() || currentPairingState()==rainpoint::PairingSessionState::Armed ||
        routineAckAuthorizations.activeCount() || htv405RoutineAckAuthorizations.activeCount() ||
        htv145OwnsReports() || htv145Pending() || valveControlProbe.commandPendingConfirmation ||
        valveControlProbe.openQueued || valveControlProbe.closeQueued) {
        reportNetworkCommandError(id,"htv213_requires_idle_unassigned_node"); return true;
    }
    rainpoint::htv213::Profile p{};
    long duration,address,selector,timing,phase,initial,routine,delayUs,notificationDelay,power;
    rainpoint::PairingLocalDateTime clock{};
    if ((discover ? jsonStringField(command,"factory_endpoint").length()!=0 :
            !parseRawHexEndpoint(jsonStringField(command,"factory_endpoint"),p.factory)) ||
        !parseRawHexEndpoint(jsonStringField(command,"controller_endpoint"),p.controller) ||
        !parseRawHexEndpoint(jsonStringField(command,"companion_endpoint"),p.companion) ||
        !parsePairingLocalDateTime(jsonStringField(command,"local_clock"),clock) ||
        !jsonLongField(command,"duration_seconds",duration) || duration<10 || duration>300 ||
        !jsonLongField(command,"device_address",address) || address<1 || address>255 ||
        !jsonLongField(command,"assigned_selector",selector) || selector<1 || selector>15 ||
        !jsonLongField(command,"timing_raw",timing) || timing<1 || timing>65535 ||
        !jsonLongField(command,"notification_phase",phase) || phase<1 || phase>63 ||
        !jsonLongField(command,"initial_center_hz",initial) || initial<433000000 || initial>435000000 ||
        !jsonLongField(command,"routine_center_hz",routine) || routine<433000000 || routine>435000000 ||
        !jsonLongField(command,"reply_delay_us",delayUs) || delayUs<20000 || delayUs>150000 ||
        !jsonLongField(command,"notification_delay_ms",notificationDelay) || notificationDelay<500 || notificationDelay>5000 ||
        !jsonLongField(command,"power_dbm",power) || power<-30 || power>10 ||
        !rainpoint::validPairingPowerDbm(static_cast<std::int8_t>(power))) {
        reportNetworkCommandError(id,"invalid_htv213_experiment"); return true;
    }
    p.address=address; p.selector=selector; p.timingRaw=timing; p.notificationPhase=phase;
    p.initialHz=initial; p.routineHz=routine; p.replyDelayUs=delayUs; p.notificationDelayMs=notificationDelay;
    // Captured empty stock defaults: no schedules or linked moisture sensor.
    // These are raw configuration fields, not the manual watering duration.
    p.settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
    if (!(discover ? rainpoint::htv213::validTransport(p) : rainpoint::htv213::valid(p)) || !primaryRadio.prepareTransmit() ||
        !primaryRadio.cacheTransmitFrequency(rainpoint::htv213::assignmentReplyHz(p,12)) ||
        !primaryRadio.cacheTransmitFrequency(rainpoint::htv213::assignmentReplyHz(p,11)) ||
        !(discover ? htv213Session.armDiscovery(p,millis(),duration*1000U) :
            htv213Session.arm(p,millis(),duration*1000U))) {
        reportNetworkCommandError(id,"htv213_prepare_failed"); return true;
    }
    // The radio has two fast-hop slots. Both possible assignment carriers
    // take priority. A distinct routine carrier uses the driver's existing
    // uncached calibration path; the captured selector-11 routine is cached.
    htv213CommandId=id; htv213Clock=clock; htv213ClockAt=millis(); htv213Power=power;
    htv213ListeningForNotification=false;
    scanChannels=false;
    if (!primaryRadio.setChannel(0)) {
        htv213Session.cancel(rainpoint::htv213::Failure::Receiver);
        restoreScanningAfterPairing();
    }
    reportHtv213(); return true;
}

void processHtv213(const rainpoint::htv213::Frame& frame,const rainpoint::RadioPacket& packet) {
    if (!htv213Armed()) return;
    htv213Session.tick(millis(),wifiTransport.authenticated() && rfMaintenance.transmitAllowed());
    if (!htv213Armed()) {
        restoreScanningAfterPairing(); reportHtv213(); return;
    }
    rainpoint::htv213::Context context{};
    auto clock=htv213Clock;
    if (!rainpoint::advancePairingLocalDateTime(clock,(millis()-htv213ClockAt)/1000)) return;
    // Gregorian weekday for the supplied local wall clock; Sunday=0.
    constexpr unsigned offsets[]={0,3,2,5,0,3,5,1,4,6,2,4};
    unsigned year=clock.year-(clock.month<3 ? 1U:0U);
    unsigned weekday=(year+year/4-year/100+year/400+offsets[clock.month-1]+clock.day)%7;
    if (!rainpoint::valveConfiguration::encodeNativeTime(clock.year,clock.month,clock.day,
            clock.hour,clock.minute,clock.second,weekday,context)) return;
    // Units are unknown: flagged unit requests fail closed, never invent them.
    rainpoint::htv213::Transmission tx{};
    if (htv213Session.claim(frame,context,millis(),tx)) {
        finishHtv213(primaryRadio.transmitAsync(tx.frame,tx.centerHz,tx.wakeSymbols,false,
            rainpoint::pairingPaTableValue(htv213Power),0x45,
            packet.receivedAtMicros+htv213Session.profile().replyDelayUs,0,
            rainpoint::htv213::nativeTailSymbol(tx.frame)));
    } else if (!htv213Armed()) {
        restoreScanningAfterPairing(); reportHtv213();
    }
}

void pollHtv213() {
    const auto before=htv213Session.state();
    htv213Session.tick(millis(),wifiTransport.authenticated() && rfMaintenance.transmitAllowed());
    if (htv213ListeningForNotification && !htv213Session.notificationResponseWindow(millis())) {
        htv213ListeningForNotification=false;
        // setReceiveFrequency changed the synthesizer base for a0. Merely
        // selecting channel 0 leaves that base unchanged and loses 02/05/06.
        if (!primaryRadio.restoreReceiveChannel(0)) htv213Session.cancel(rainpoint::htv213::Failure::Receiver);
    }
    rainpoint::htv213::Transmission tx{};
    if (htv213Session.claimNotification(millis(),tx)) {
        finishHtv213(primaryRadio.transmitAsync(tx.frame,tx.centerHz,tx.wakeSymbols,false,
            rainpoint::pairingPaTableValue(htv213Power),0x45,0,0,
            rainpoint::htv213::nativeTailSymbol(tx.frame)),true);
    } else if (before!=htv213Session.state()) {
        restoreScanningAfterPairing(); reportHtv213();
    }
}
