// Explicit dry-test transport, compiled out unless BOTH HTV213 experiment
// flags are enabled. No automatic counter seed, retry, rejoin or startup TX.
rainpoint::htv213Control::Trial htv213ControlTrial;
rainpoint::htv213::Profile htv213ControlProfile{};
String htv213ControlCommandId, htv213ControlOpenId;
rainpoint::PairingLocalDateTime htv213ControlClock{};
std::uint32_t htv213ControlClockAt=0;
std::int8_t htv213ControlPower=0;
bool htv213ControlListening=false;
unsigned htv213ControlAcks=0;
bool htv213OwnerEnabled=false;
bool htv213RetainedRejoinEnabled=false;
rainpoint::valveConfiguration::Association htv213RetainedConfiguration{};
String htv213OwnerId;

bool parseHtv213Settings(const String& text, std::array<std::uint8_t,14>& settings) {
    if (text.length()!=settings.size()*2) return false;
    const auto nibble=[](char c)->int {
        return c>='0' && c<='9' ? c-'0' : c>='a' && c<='f' ? c-'a'+10 : -1;
    };
    for (unsigned i=0;i<settings.size();++i) {
        const int high=nibble(text[2*i]),low=nibble(text[2*i+1]);
        if (high<0 || low<0) return false;
        settings[i]=(high<<4)|low;
    }
    return true;
}

void reportHtv213Owner(const rainpoint::htv213::Frame* frame=nullptr) {
    String line="{\"type\":\"htv213_owner_status\",\"command_id\":\"";
    line+=htv213OwnerId; line+="\",\"enabled\":";
    line+=htv213OwnerEnabled ? "true" : "false";
    line+=",\"retained_rejoin_enabled\":";
    line+=htv213RetainedRejoinEnabled ? "true" : "false";
    line+=",\"configuration_revision\":";
    line+=htv213RetainedConfiguration.configurationRevision;
    if (frame) {
        constexpr char digits[]="0123456789abcdef";
        line+=",\"frame\":\"";
        for (auto byte:*frame) { line+=digits[byte>>4]; line+=digits[byte&15]; }
        line+='"';
    }
    line+='}'; emitLine(line);
}

bool htv213ControlActive() {
    using S=rainpoint::htv213Control::State;
    const auto state=htv213ControlTrial.state();
    return state!=S::Idle && state!=S::Complete && state!=S::Cancelled && state!=S::Overdue &&
        state!=S::RecoveredIdle;
}

void reportHtv213Control(const rainpoint::htv213::Frame* frame=nullptr) {
    constexpr const char* names[]={"idle","transmitting","awaiting_response","open_confirmed",
        "close_awaiting_response","close_confirmed","complete","uncertain","overdue","cancelled","recovered_idle"};
    String line="{\"type\":\"htv213_control_status\",\"node_id\":\"";
    line+=wifiTransport.nodeId(); line+="\",\"command_id\":\""; line+=htv213ControlCommandId;
    line+="\",\"state\":\""; line+=names[static_cast<unsigned>(htv213ControlTrial.state())];
    line+="\",\"tx_armed\":"; line+=htv213ControlActive() ? "true" : "false";
    line+=",\"phase\":"; line+=htv213ControlTrial.phase();
    if (frame) {
        constexpr char digits[]="0123456789abcdef";
        line+=",\"frame\":\"";
        for (const auto byte:*frame) { line+=digits[byte>>4]; line+=digits[byte&15]; }
        line+='"';
    }
    line+='}'; emitLine(line);
}

void restoreHtv213ControlReceiver() {
    htv213ControlListening=false;
    if (!primaryRadio.restoreReceiveChannel(0)) htv213ControlTrial.cancel();
    if (!htv213ControlActive() && !htv213OwnerEnabled) restoreScanningAfterPairing();
}

void transmitHtv213Control(const rainpoint::htv213::Transmission& tx) {
    const bool sent=primaryRadio.transmitAsync(tx.frame,tx.centerHz,tx.wakeSymbols,false,
        rainpoint::pairingPaTableValue(htv213ControlPower),0x45,0,0,
        rainpoint::htv213Control::nativeTailSymbol(tx.frame));
    htv213ControlTrial.finishTransmit(sent,millis());
    if (sent) {
        htv213ControlListening=primaryRadio.setReceiveFrequency(tx.centerHz);
        if (!htv213ControlListening) htv213ControlTrial.cancel();
    }
    if (!htv213ControlActive()) restoreHtv213ControlReceiver();
    reportHtv213Control();
}

bool handleHtv213ControlCommand(const String& type,const String& command,const String& id) {
    const bool open=type=="htv213_control_probe_open";
    const bool close=type=="htv213_control_probe_close";
    const bool owner=type=="htv213_owner_set";
    if (type=="htv213_owner_clear") {
        if (!htv213OwnerEnabled && !htv213ControlActive()) {
            htv213OwnerId=jsonStringField(command,"owner_id");
            reportHtv213Owner(); return true; // Already disabled, including after reboot.
        }
        if (jsonStringField(command,"owner_id")!=htv213OwnerId || htv213ControlActive())
            reportNetworkCommandError(id,"htv213_owner_clear_requires_idle_matching_owner");
        else { htv213OwnerEnabled=false; reportHtv213Owner(); restoreHtv213ControlReceiver(); }
        return true;
    }
    if (!open && !close && !owner) {
        // Persistent ACK ownership is not an active valve transaction. Let
        // idle OTA reach the shared signed-update validator, retaining this
        // owner until reboot; the gateway restores it after authentication.
        if (type=="firmware_update_start" && !htv213ControlActive()) return false;
        if (!htv213ControlActive() && !htv213OwnerEnabled) return false;
        if (type=="rf_mode_set" || type=="node_reboot") {
            htv213OwnerEnabled=false; reportHtv213Owner();
            htv213ControlTrial.cancel(); restoreHtv213ControlReceiver(); reportHtv213Control(); return false;
        }
        reportNetworkCommandError(id,"htv213_control_experiment_busy"); return true;
    }
    if (id==htv213ControlCommandId || id==htv213ControlOpenId) {
        reportNetworkCommandError(id,"htv213_control_duplicate"); return true;
    }
    if (!wifiTransport.authenticated() || !radiosHealthy || !rfMaintenance.transmitAllowed() ||
        htv213Armed() || currentPairingState()==rainpoint::PairingSessionState::Armed ||
        routineAckAuthorizations.activeCount() || htv405RoutineAckAuthorizations.activeCount() ||
        htv145OwnsReports() || htv145Pending() || valveControlProbe.commandPendingConfirmation ||
        valveControlProbe.openQueued || valveControlProbe.closeQueued) {
        reportNetworkCommandError(id,"htv213_requires_idle_unassigned_node"); return true;
    }
    long phase=0;
    if (!owner && (!jsonLongField(command,"phase",phase) || phase<0 || phase>63)) {
        reportNetworkCommandError(id,"invalid_htv213_control_phase"); return true;
    }
    rainpoint::htv213::Transmission tx{};
    if (close) {
        if (jsonStringField(command,"open_command_id")!=htv213ControlOpenId ||
            !htv213ControlTrial.close(phase,millis(),tx)) {
            reportNetworkCommandError(id,"htv213_close_requires_confirmed_open"); return true;
        }
        htv213ControlCommandId=id; transmitHtv213Control(tx); return true;
    }
    if (htv213ControlActive()) {
        reportNetworkCommandError(id,"htv213_control_experiment_busy"); return true;
    }
    rainpoint::htv213::Profile p{};
    rainpoint::PairingLocalDateTime clock{};
    long port,seconds,selector,initial,routine,delay,power,address,timing,notificationPhase,notificationDelay;
    if (!parseRawHexEndpoint(jsonStringField(command,"factory_endpoint"),p.factory) ||
        !parseRawHexEndpoint(jsonStringField(command,"controller_endpoint"),p.controller) ||
        !parseRawHexEndpoint(jsonStringField(command,"companion_endpoint"),p.companion) ||
        !parsePairingLocalDateTime(jsonStringField(command,"local_clock"),clock) ||
        !jsonLongField(command,"port",port) || port<1 || port>2 ||
        !jsonLongField(command,"seconds",seconds) || seconds<1 || seconds>rainpoint::htv213Control::kMaximumTrialSeconds ||
        !jsonLongField(command,"assigned_selector",selector) || selector<1 || selector>15 ||
        !jsonLongField(command,"initial_center_hz",initial) || initial<433000000 || initial>435000000 ||
        !jsonLongField(command,"routine_center_hz",routine) || routine<433000000 || routine>435000000 ||
        !jsonLongField(command,"reply_delay_us",delay) || delay<20000 || delay>150000 ||
        !jsonLongField(command,"power_dbm",power) || power<-30 || power>10 ||
        !rainpoint::validPairingPowerDbm(power) ||
        !jsonLongField(command,"device_address",address) || address<1 || address>255 ||
        !jsonLongField(command,"timing_raw",timing) || timing<1 || timing>65535 ||
        !jsonLongField(command,"notification_phase",notificationPhase) || notificationPhase<1 || notificationPhase>63 ||
        !jsonLongField(command,"notification_delay_ms",notificationDelay) || notificationDelay<500 || notificationDelay>5000) {
        reportNetworkCommandError(id,"invalid_htv213_control_profile"); return true;
    }
    p.address=address; p.timingRaw=timing; p.notificationPhase=notificationPhase;
    p.notificationDelayMs=notificationDelay; p.initialHz=initial; p.routineHz=routine;
    p.selector=selector; p.replyDelayUs=delay;
    p.settings={{0x58,2,10,0,30,0,0,0,0,0,0,0,0,0}};
    rainpoint::valveConfiguration::Association retained{};
    bool rejoin=false;
    if (owner) {
        long revision=0;
        retained.model=rainpoint::valveConfiguration::Model::Htv213;
        retained.factoryEndpoint=p.factory; retained.requestRouteA=p.controller;
        retained.requestRouteB=p.factory; retained.requestRouteB[0]|=128;
        retained.address=p.address; retained.selector=p.selector;
        retained.timingRaw=p.timingRaw; retained.timingKnown=true;
        if (!jsonLongField(command,"configuration_revision",revision) || revision<1 || revision>255 ||
            !jsonBoolField(command,"retained_rejoin_enabled",rejoin)) {
            reportNetworkCommandError(id,"explicit_htv213_configuration_required"); return true;
        }
        retained.configurationRevision=revision;
        for (unsigned index=0;index<2;++index) {
            const char* settingsKey=index ? "port_2_settings" : "port_1_settings";
            const char* planKey=index ? "port_2_empty_plan" : "port_1_empty_plan";
            auto& portConfig=retained.ports[index];
            if (!parseHtv213Settings(jsonStringField(command,settingsKey),portConfig.settings) ||
                !jsonBoolField(command,planKey,portConfig.emptyPlanKnown) || !portConfig.emptyPlanKnown) {
                reportNetworkCommandError(id,"explicit_htv213_configuration_required"); return true;
            }
            portConfig.settingsKnown=true;
        }
    }
    if (htv213OwnerEnabled && (p.factory!=htv213ControlProfile.factory ||
        p.controller!=htv213ControlProfile.controller || p.companion!=htv213ControlProfile.companion ||
        p.routineHz!=htv213ControlProfile.routineHz || p.initialHz!=htv213ControlProfile.initialHz ||
        p.selector!=htv213ControlProfile.selector || p.address!=htv213ControlProfile.address ||
        p.timingRaw!=htv213ControlProfile.timingRaw || p.replyDelayUs!=htv213ControlProfile.replyDelayUs ||
        power!=htv213ControlPower || (owner && id!=htv213OwnerId))) {
        reportNetworkCommandError(id,"htv213_revoke_owner_before_reconfiguration"); return true;
    }
    rainpoint::htv213Control::Trial restoredTrial;
    const String recoveryId=owner ? jsonStringField(command,"recovery_command_id") : String{};
    if (recoveryId.length()) {
        long recoveryPhase=0,recoveryPort=0,recoverySeconds=0;
        if (!validCommandId(recoveryId) || recoveryId==id ||
            !jsonLongField(command,"recovery_phase",recoveryPhase) || recoveryPhase<0 || recoveryPhase>63 ||
            !jsonLongField(command,"recovery_port",recoveryPort) || recoveryPort<1 || recoveryPort>2 ||
            !jsonLongField(command,"recovery_seconds",recoverySeconds) || recoverySeconds<1 ||
            recoverySeconds>rainpoint::htv213Control::kMaximumTrialSeconds ||
            !restoredTrial.resumeIdleRecovery(p,recoveryPort,recoverySeconds,recoveryPhase,millis())) {
            reportNetworkCommandError(id,"invalid_htv213_idle_recovery"); return true;
        }
    }
    if (!rainpoint::htv213::valid(p) || !primaryRadio.prepareTransmit() ||
        (owner && rejoin && (!primaryRadio.cacheTransmitFrequency(rainpoint::htv213::assignmentReplyHz(p,12)) ||
                            !primaryRadio.cacheTransmitFrequency(rainpoint::htv213::assignmentReplyHz(p,11)))) ||
        !primaryRadio.restoreReceiveChannel(0)) {
        reportNetworkCommandError(id,"htv213_control_prepare_failed"); return true;
    }
    htv213ControlTrial=restoredTrial;
    if (!owner && !htv213ControlTrial.start(p,port,seconds,phase,millis(),tx)) {
        reportNetworkCommandError(id,"htv213_control_start_failed"); return true;
    }
    htv213ControlProfile=p; htv213ControlClock=clock; htv213ControlClockAt=millis();
    htv213ControlPower=power; htv213ControlAcks=0; htv213ControlListening=false;
    if (owner) {
        htv213RetainedConfiguration=retained;
        htv213RetainedRejoinEnabled=rejoin;
        htv213OwnerEnabled=true; htv213OwnerId=id; scanChannels=false;
        reportHtv213Owner();
        if (recoveryId.length()) {
            htv213ControlCommandId=recoveryId; htv213ControlOpenId=recoveryId;
            reportHtv213Control();
        }
        return true; // Reply ownership/recovery never transmits an open.
    }
    htv213ControlCommandId=id; htv213ControlOpenId=id;
    scanChannels=false;
    transmitHtv213Control(tx); return true;
}

void processHtv213Control(const rainpoint::htv213::Frame& frame,const rainpoint::RadioPacket& packet) {
    if (!htv213ControlActive() && !htv213OwnerEnabled) return;
    htv213ControlTrial.tick(millis());
    if (!wifiTransport.authenticated() || !rfMaintenance.transmitAllowed()) {
        htv213ControlTrial.cancel(); htv213OwnerEnabled=false;
    }
    if (!htv213ControlActive() && !htv213OwnerEnabled) { restoreHtv213ControlReceiver(); reportHtv213Control(); return; }
    const bool observed=htv213ControlTrial.observe(frame,millis());
    rainpoint::htv213::Context context{};
    auto clock=htv213ControlClock;
    if (rainpoint::advancePairingLocalDateTime(clock,(millis()-htv213ControlClockAt)/1000)) {
        constexpr unsigned offsets[]={0,3,2,5,0,3,5,1,4,6,2,4};
        unsigned year=clock.year-(clock.month<3 ? 1U:0U);
        unsigned weekday=(year+year/4-year/100+year/400+offsets[clock.month-1]+clock.day)%7;
        rainpoint::valveConfiguration::encodeNativeTime(clock.year,clock.month,clock.day,
            clock.hour,clock.minute,clock.second,weekday,context);
    }
    rainpoint::htv213::Transmission tx{};
    const bool reply=htv213OwnerEnabled ? rainpoint::htv213Owner::prepareReply(
        htv213ControlProfile,htv213RetainedConfiguration,frame,context,htv213RetainedRejoinEnabled,tx) :
        rainpoint::htv213Control::prepareReportAck(htv213ControlProfile,frame,2,context,tx);
    if (reply) {
        if ((!htv213OwnerEnabled && ++htv213ControlAcks>64) || !primaryRadio.transmitAsync(tx.frame,tx.centerHz,tx.wakeSymbols,false,
                rainpoint::pairingPaTableValue(htv213ControlPower),0x45,
                packet.receivedAtMicros+htv213ControlProfile.replyDelayUs,0,
                rainpoint::htv213Control::nativeTailSymbol(tx.frame))) {
            htv213ControlTrial.cancel(); htv213OwnerEnabled=false;
        }
        if (htv213OwnerId.length()) reportHtv213Owner(&frame);
    }
    if (observed || !htv213ControlActive()) reportHtv213Control(&frame);
    if (!htv213ControlActive()) restoreHtv213ControlReceiver();
}

void pollHtv213Control() {
    if (htv213OwnerEnabled && (!wifiTransport.authenticated() || !rfMaintenance.transmitAllowed())) {
        htv213OwnerEnabled=false; reportHtv213Owner(); restoreHtv213ControlReceiver();
    }
    if (!htv213ControlActive()) return;
    const auto before=htv213ControlTrial.state();
    htv213ControlTrial.tick(millis());
    if (!wifiTransport.authenticated() || !rfMaintenance.transmitAllowed()) htv213ControlTrial.cancel();
    if (htv213ControlListening && !htv213ControlTrial.listening(millis())) restoreHtv213ControlReceiver();
    if (!htv213ControlActive()) restoreHtv213ControlReceiver();
    if (before!=htv213ControlTrial.state()) reportHtv213Control();
}
