// Included only in the explicit phase-trial candidate, never production.
rainpoint::nativeReceipt::Guard nativeValveGuard;
bool nativeValveStorageReady=false, nativeValveListening=false;

bool saveNativeValveRecord(const rainpoint::nativeReceipt::Record& record) {
    Preferences prefs;
    if (!prefs.begin("native-phase",false)) return false;
    const bool saved=prefs.putBytes("record",&record,sizeof(record))==sizeof(record);
    prefs.end(); return saved;
}
void loadNativeValveRecord() {
    Preferences prefs;
    if (!prefs.begin("native-phase",false)) { nativeValveGuard.valid=false; return; }
    const auto size=prefs.getBytesLength("record");
    rainpoint::nativeReceipt::Record record{};
    const bool read=!size || (size==sizeof(record) && prefs.getBytes("record",&record,sizeof(record))==sizeof(record));
    prefs.end();
    if (!read || (size && !nativeValveGuard.restore(record))) { nativeValveGuard.valid=false; return; }
    if (size && record.stage==rainpoint::nativeReceipt::Stage::Attempted)
        nativeValveGuard.persist(nativeValveGuard.record,saveNativeValveRecord);
    nativeValveStorageReady=nativeValveGuard.valid;
}
const char* nativeValveStage() {
    using rainpoint::nativeReceipt::Stage;
    if (!nativeValveGuard.valid) return "uncertain";
    switch(nativeValveGuard.record.stage) {
        case Stage::Ready:return "ready";
        case Stage::Attempted:return "attempted";
        case Stage::Accepted:return "accepted";
        case Stage::Released:return "released";
        default:return "uncertain";
    }
}
void reportNativeValveReceipt() {
    const auto& record=nativeValveGuard.record;
    String line="{\"type\":\"valve_native_receipt\",\"epoch\":\"";
    line+=record.epoch; line+="\",\"command_id\":\""; line+=record.commandId;
    line+="\",\"stage\":\""; line+=nativeValveStage(); line+="\",\"phase\":";
    line+=record.stage==rainpoint::nativeReceipt::Stage::Ready?record.next:record.phase;
    line+=",\"frame\":\""; line+=hexString(record.frame.data(),record.frame.size()); line+='"';
    line+=",\"minimum_interval_ms\":";
    const auto elapsed=millis()-nativeValveGuard.attemptedAt;
    line+=elapsed>=15'000?0:15'000-elapsed;
    if (record.maximumCommands) {
        line+=",\"qualification_remaining_ms\":";
        line+=nativeValveGuard.qualificationRemaining(millis());
    }
    if (record.maintenance!=rainpoint::nativeReceipt::Maintenance::None) {
        line+=",\"maintenance_id\":\""; line+=record.maintenanceId;
        line+="\",\"maintenance_kind\":\"";
        line+=record.maintenance==rainpoint::nativeReceipt::Maintenance::Handback?"handback":"recover";
        line+="\",\"legacy_counter\":"; line+=record.legacyCounter;
    }
    line+='}';
    emitLine(line);
}
bool parseNativeFrame(const String& hex,rainpoint::commandPhase::Frame& frame) {
    if (hex.length()!=frame.size()*2) return false;
    const auto nibble=[](char c)->int { return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1; };
    for (unsigned i=0;i<frame.size();++i) {
        const int high=nibble(hex[2*i]),low=nibble(hex[2*i+1]);
        if (high<0 || low<0) return false;
        frame[i]=(high<<4)|low;
    }
    return true;
}
bool handleNativeValveCommand(const String& type,const String& command,const String& commandId) {
    const bool adopt=type=="valve_native_adopt", send=type=="valve_native_command";
    const bool maintain=type=="valve_native_recover" || type=="valve_native_handback";
    if (type=="valve_native_status") { reportNativeValveReceipt(); return true; }
    if (!adopt && !send && !maintain) {
        if (nativeValveGuard.locked() && (type=="pairing_start" || type.startsWith("valve_phase_trial_") ||
                type.startsWith("valve_control_") && type!="valve_control_configure" && type!="valve_control_status" ||
                type.startsWith("htv145_control_") && type!="htv145_control_configure" && type!="htv145_control_status")) {
            reportNetworkCommandError(commandId,"native_counter_owner_locked"); return true;
        }
        return false;
    }
    const auto error=[&]() { reportNetworkCommandError(commandId,"invalid_native_valve_command"); return true; };
    if (!nativeValveStorageReady || !wifiTransport.authenticated() || !radiosHealthy ||
            !rfMaintenance.transmitAllowed() || valvePhaseGuard.locked() || htv145Pending() ||
            valveControlProbe.commandPendingConfirmation || valveControlProbe.openQueued || valveControlProbe.closeQueued ||
            currentPairingState()==rainpoint::PairingSessionState::Armed) return error();
    const String epoch=jsonStringField(command,"epoch"),model=jsonStringField(command,"model");
    if (!rainpoint::nativeReceipt::id(epoch.c_str())) return error();
    rainpoint::commandPhase::Frame frame{};
    if (maintain) {
        rainpoint::commandPhase::Frame result{},idle{};
        long phase=-1;
        const bool handback=type=="valve_native_handback";
        const bool alreadyReleased=nativeValveGuard.record.stage==rainpoint::nativeReceipt::Stage::Released;
        if ((model=="HTV405FRF")!=nativeValveGuard.record.four ||
                (model!="HTV145FRF" && model!="HTV405FRF") ||
                !jsonLongField(command,"phase",phase) || phase!=nativeValveGuard.record.phase ||
                !parseNativeFrame(jsonStringField(command,"frame"),frame) || frame!=nativeValveGuard.record.frame ||
                !parseNativeFrame(jsonStringField(command,"result_frame"),result) ||
                !parseNativeFrame(jsonStringField(command,"idle_frame"),idle) ||
                !nativeValveGuard.maintain(epoch.c_str(),commandId.c_str(),
                    jsonStringField(command,"attempted_command_id").c_str(),
                    handback?rainpoint::nativeReceipt::Maintenance::Handback:rainpoint::nativeReceipt::Maintenance::Recover,
                    result,idle,millis(),saveNativeValveRecord)) return error();
        if (handback && !alreadyReleased) {
            if (nativeValveGuard.record.four) restoreValveControlCounter(nativeValveGuard.record.legacyCounter);
            else for (auto& owner:htv145Owners)
                if (owner.configured && owner.link.controllerEndpoint==nativeValveGuard.record.a &&
                        owner.link.valveEndpoint==nativeValveGuard.record.b) {
                    owner.nextSequence=0x80U|nativeValveGuard.record.legacyCounter;
                    owner.counterAuthenticated=true;
                }
        }
        reportNativeValveReceipt(); return true; // No RF, no phase allocation, no retry.
    }
    if (adopt) {
        if (commandId!=epoch) return error();
        rainpoint::nativeReceipt::Record next{};
        rainpoint::commandPhase::Frame response{};
        if (!parseRawHexEndpoint(jsonStringField(command,"endpoint_a"),next.a) ||
                !parseRawHexEndpoint(jsonStringField(command,"endpoint_b"),next.b) ||
                !parseNativeFrame(jsonStringField(command,"request_frame"),frame) ||
                !parseNativeFrame(jsonStringField(command,"response_frame"),response)) return error();
        long phase=-1,port=0,selector=0,reportSelector=0,maximumCommands=0,qualificationSeconds=0;
        if (!jsonLongField(command,"next_phase",phase) || !jsonLongField(command,"port",port) ||
                !jsonLongField(command,"selector",selector) || selector<1 || selector>255 ||
                !jsonLongField(command,"report_selector",reportSelector) || reportSelector<1 || reportSelector>15 ||
                !jsonLongField(command,"maximum_commands",maximumCommands) || maximumCommands<0 || maximumCommands>2 ||
                !jsonLongField(command,"qualification_seconds",qualificationSeconds) ||
                (maximumCommands?qualificationSeconds<120 || qualificationSeconds>900:qualificationSeconds!=0)) return error();
        const auto native=[&](unsigned i) { return static_cast<std::uint8_t>((frame[i+4]<<1U)|(frame[i+5]>>7U)); };
        const unsigned accepted=rainpoint::commandPhase::fromNormalized(frame);
        const bool opened=native(14)==1;
        const unsigned seconds=opened?(unsigned(native(15))|(unsigned(native(16))<<8U)):0;
        const unsigned projected=((accepted>>1U)+unsigned(opened))&31U;
        if (phase!=long((accepted+1U)&63U) || port<1 || port>4) return error();
        std::strcpy(next.epoch,epoch.c_str()); next.next=phase; next.selector=selector;
        next.reportSelector=reportSelector;
        next.maximumCommands=maximumCommands; next.qualificationPort=port;
        next.qualificationSeconds=qualificationSeconds;
        next.baseline=frame; next.port=port;
        if (model=="HTV145FRF") {
            bool found=false;
            for (const auto& owner:htv145Owners) if (owner.configured && owner.link.controllerEndpoint==next.a && owner.link.valveEndpoint==next.b) {
                if (owner.invert || !owner.commandMarkerInverted || !owner.counterAuthenticated ||
                        (owner.nextSequence&31U)!=projected || port!=1) return error();
                next.centerHz=owner.centerHz; next.power=owner.powerDbm;
                next.openResidue=owner.trailerResidual; next.closeResidue=owner.closeTrailerResidual; found=true;
            }
            if (!found) return error();
        } else if (model=="HTV405FRF") {
            if (!valveControlProbe.configured || valveControlProbe.gatewayControlLink.pairedEndpoint!=next.a ||
                    valveControlProbe.gatewayControlLink.companionEndpoint!=next.b ||
                    !valveControlProbe.commandCounterAuthenticated || valveControlProbe.commandSequence!=projected ||
                    valveControlProbe.selector!=selector) return error();
            next.four=true; next.centerHz=valveProbeCenterHz(); next.power=kValveProbePowerDbm;
        } else return error();
        rainpoint::nativeReceipt::Guard baseline;
        baseline.record=next;
        rainpoint::commandPhase::Frame expected{};
        if (!baseline.build(accepted,opened,seconds,port,expected) || expected!=frame) return error();
        baseline.record.phase=accepted; baseline.record.open=opened; baseline.record.seconds=seconds;
        baseline.record.stage=rainpoint::nativeReceipt::Stage::Attempted;
        if (!baseline.observe(response,0,[](const auto&) {return true;}) ||
                baseline.record.stage!=rainpoint::nativeReceipt::Stage::Accepted ||
                !nativeValveGuard.adopt(next,saveNativeValveRecord,millis())) return error();
        reportNativeValveReceipt(); return true; // Adoption is deliberately no-RF.
    }
    long phase=-1,port=0,seconds=0;
    const String action=jsonStringField(command,"action");
    if ((model=="HTV405FRF")!=nativeValveGuard.record.four ||
            (model!="HTV145FRF" && model!="HTV405FRF") ||
            (action!="open" && action!="close") ||
            !jsonLongField(command,"phase",phase) || !jsonLongField(command,"port",port) ||
            !parseNativeFrame(jsonStringField(command,"frame"),frame) ||
            (action=="open" && !jsonLongField(command,"duration_seconds",seconds))) return error();
    const auto admission=nativeValveGuard.begin(epoch.c_str(),commandId.c_str(),phase,action=="open",seconds,port,
                                               frame,millis(),saveNativeValveRecord);
    if (admission==rainpoint::nativeReceipt::Admission::Denied) return error();
    if (admission==rainpoint::nativeReceipt::Admission::Duplicate) { reportNativeValveReceipt(); return true; }
    scanChannels=false;
    const bool sent=primaryRadio.prepareTransmit() && primaryRadio.transmitAsync(frame,nativeValveGuard.record.centerHz,
        kValveProbeWakeSymbols,false,rainpoint::pairingPaTableValue(nativeValveGuard.record.power));
    nativeValveListening=sent && primaryRadio.setReceiveFrequency(nativeValveGuard.record.centerHz);
    if (!nativeValveListening) {
        nativeValveGuard.fail(saveNativeValveRecord);
        primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel);
        restoreScanningAfterPairing();
    }
    reportNativeValveReceipt(); return true;
}
void observeNativeValve(const rainpoint::commandPhase::Frame& frame) {
    nativeValveGuard.observePhysical(frame,millis());
    if (nativeValveGuard.observe(frame,millis(),saveNativeValveRecord)) reportNativeValveReceipt();
}
void pollNativeValve() {
    if (nativeValveGuard.pending() && (!wifiTransport.authenticated() ||
            !rfMaintenance.transmitAllowed() || millis()-nativeValveGuard.attemptedAt>15'000)) {
        nativeValveGuard.fail(saveNativeValveRecord); reportNativeValveReceipt();
    }
    if (nativeValveListening && (!nativeValveGuard.pending() || millis()-nativeValveGuard.attemptedAt>3'000)) {
        nativeValveListening=false;
        if (!primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel)) nativeValveGuard.valid=false;
        restoreScanningAfterPairing();
    }
}
