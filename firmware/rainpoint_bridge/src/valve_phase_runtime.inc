// Included only by the explicitly versioned full-phase experiment build.
rainpoint::phaseCanary::Guard valvePhaseGuard;
bool valvePhaseStorageReady=false, valvePhaseListening=false;
std::uint32_t valvePhaseSentAt=0;

bool saveValvePhaseRecord(const rainpoint::phaseCanary::Record& record) {
    Preferences prefs;
    if (!prefs.begin("phase-canary",false)) return false;
    const bool saved=prefs.putBytes("record",&record,sizeof(record))==sizeof(record);
    prefs.end(); return saved;
}

void loadValvePhaseRecord() {
    Preferences prefs;
    if (!prefs.begin("phase-canary",false)) return;
    const auto size=prefs.getBytesLength("record");
    rainpoint::phaseCanary::Record record{};
    if (size && (size!=sizeof(record) || prefs.getBytes("record",&record,sizeof(record))!=sizeof(record))) {
        prefs.end(); valvePhaseGuard.record.stage=rainpoint::phaseCanary::Stage::Failed; return;
    }
    prefs.end();
    if (size) valvePhaseGuard.restore(record);
    valvePhaseStorageReady=true;
}

void reportValvePhase(const rainpoint::commandPhase::Frame* frame=nullptr) {
    String line="{\"type\":\"valve_phase_trial_status\",\"authorization_id\":\"";
    line+=valvePhaseGuard.record.authorization; line+="\",\"command_id\":\"";
    line+=valvePhaseGuard.record.commandId; line+="\",\"stage\":";
    line+=static_cast<unsigned>(valvePhaseGuard.record.stage);
    line+=",\"phase\":"; line+=valvePhaseGuard.record.phase;
    line+=",\"count\":"; line+=valvePhaseGuard.record.count;
    if (frame) { line+=",\"frame\":\""; line+=hexString(frame->data(),frame->size()); line+='"'; }
    line+='}'; emitLine(line);
}

void restoreValvePhaseReceiver() {
    if (!valvePhaseListening) return;
    valvePhaseListening=false;
    if (!primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel)) valvePhaseGuard.fail();
    restoreScanningAfterPairing();
}

bool handleValvePhaseCommand(const String& type,const String& command,const String& id) {
    if (type=="valve_phase_trial_status") { reportValvePhase(); return true; }
    const bool open=type=="valve_phase_trial_open", release=type=="valve_phase_trial_release";
    const bool recover=type=="valve_phase_trial_recover";
    if (!open && !release && !recover) {
        // Keep routine ACK ownership/restoration, maintenance and signed OTA.
        // No normal valve TX or pairing can race the reserved experiment.
        if (valvePhaseGuard.locked() && (type.startsWith("valve_control_") ||
                (type.startsWith("htv145_control_") && type!="htv145_control_configure" &&
                    type!="htv145_control_status") || type=="pairing_start")) {
            reportNetworkCommandError(id,"valve_phase_trial_locked"); return true;
        }
        return false;
    }
    const auto error=[&]() { reportNetworkCommandError(id,"invalid_valve_phase_trial"); return true; };
    if (!valvePhaseStorageReady || !wifiTransport.authenticated() || !radiosHealthy ||
            !rfMaintenance.transmitAllowed() || htv145Pending() ||
            valveControlProbe.commandPendingConfirmation || valveControlProbe.openQueued ||
            valveControlProbe.closeQueued || currentPairingState()==rainpoint::PairingSessionState::Armed)
        return error();
    const String model=jsonStringField(command,"model");
    const String authorization=jsonStringField(command,"authorization_id");
    std::array<std::uint8_t,4> a{},b{};
    if (!parseRawHexEndpoint(jsonStringField(command,"endpoint_a"),a) ||
            !parseRawHexEndpoint(jsonStringField(command,"endpoint_b"),b)) return error();
    std::size_t slot=htv145Owners.size();
    std::array<std::uint8_t,8> route{};
    std::uint32_t center=0; std::int8_t power=0;
    rainpoint::commandPhase::Frame frame{};
    long phase=-1, ordinal=0, selector=0, seconds=0;
    if (open && (!jsonLongField(command,"phase",phase) ||
            !jsonLongField(command,"ordinal",ordinal) ||
            !jsonLongField(command,"selector",selector) ||
            !jsonLongField(command,"seconds",seconds) || seconds!=60)) return error();
    if (model=="HTV145FRF") {
        for (std::size_t i=0;i<htv145Owners.size();++i)
            if (htv145Owners[i].configured && htv145Owners[i].link.controllerEndpoint==a &&
                    htv145Owners[i].link.valveEndpoint==b) slot=i;
        if (slot==htv145Owners.size()) return error();
        const auto& owner=htv145Owners[slot];
        if (!owner.commandMarkerInverted || owner.invert) return error();
        center=owner.centerHz; power=owner.powerDbm;
        std::copy(b.begin(),b.end(),route.begin()); std::copy(a.begin(),a.end(),route.begin()+4);
        if (open && ((!owner.counterAuthenticated && ordinal==1) ||
                (ordinal==1 && (phase>>1)!=(owner.nextSequence&31)) ||
                !rainpoint::commandPhase::buildHtv145(owner.link,phase,true,60,owner.trailerResidual,frame))) return error();
    } else if (model=="HTV405FRF") {
        if (recover) return error(); // This repair is qualified for HTV145 only.
        if (!valveControlProbe.configured || valveControlProbe.gatewayControlLink.pairedEndpoint!=a ||
                valveControlProbe.gatewayControlLink.companionEndpoint!=b) return error();
        center=valveProbeCenterHz(); power=kValveProbePowerDbm;
        std::copy(b.begin(),b.end(),route.begin()); route[0]|=128;
        std::copy(a.begin(),a.end(),route.begin()+4);
        if (open && ((!valveControlProbe.commandCounterAuthenticated && ordinal==1) ||
                (ordinal==1 && (phase>>1)!=valveControlProbe.commandSequence) ||
                !rainpoint::commandPhase::buildHtv405(valveControlProbe.gatewayControlLink,phase,true,
                    60,1,valveControlProbe.selector,kValveProbeTrailerResidual,frame))) return error();
    } else return error();
    if (recover) {
        if (route!=valvePhaseGuard.record.responseRoute) return error();
        if (valvePhaseGuard.record.stage==rainpoint::phaseCanary::Stage::Recovered) {
            if (authorization!=valvePhaseGuard.record.authorization || id!=valvePhaseGuard.record.commandId)
                return error();
            reportValvePhase(); return true; // Lost reply may repeat; never rewind RAM counter.
        }
        rainpoint::commandPhase::Frame ack{}, active{}, idle{};
        const auto parseFrame=[&](const char* field, auto& output) {
            const String hex=jsonStringField(command,field);
            if (hex.length()!=output.size()*2) return false;
            for (unsigned i=0;i<output.size();++i) {
                const auto nibble=[](char c)->int { return c>='0'&&c<='9'?c-'0':c>='a'&&c<='f'?c-'a'+10:-1; };
                const int high=nibble(hex[2*i]), low=nibble(hex[2*i+1]);
                if (high<0 || low<0) return false;
                output[i]=static_cast<std::uint8_t>((high<<4)|low);
            }
            return true;
        };
        long ackAge=-1,activeAge=-1,idleAge=-1;
        if (!parseFrame("ack_frame",ack) || !parseFrame("watering_frame",active) || !parseFrame("idle_frame",idle) ||
                !jsonLongField(command,"ack_age_ms",ackAge) || !jsonLongField(command,"watering_age_ms",activeAge) ||
                !jsonLongField(command,"idle_age_ms",idleAge) || ackAge<0 || activeAge<0 || idleAge<0 ||
                !valvePhaseGuard.recover(authorization.c_str(),id.c_str(),
                    jsonStringField(command,"attempted_command_id").c_str(),ack,active,idle,
                    ackAge,activeAge,idleAge,saveValvePhaseRecord)) return error();
        htv145Owners[slot].nextSequence=0x80U|((valvePhaseGuard.record.phase+1U)/2U);
        htv145Owners[slot].counterAuthenticated=true;
        reportValvePhase(); return true; // Deliberately no transmitter or receiver reconfiguration.
    }
    if (release) {
        if (valvePhaseGuard.record.stage==rainpoint::phaseCanary::Stage::Released &&
                authorization==valvePhaseGuard.record.authorization && route==valvePhaseGuard.record.responseRoute) {
            reportValvePhase(); return true; // Never restore an old counter twice.
        }
        if (route!=valvePhaseGuard.record.responseRoute ||
                !valvePhaseGuard.release(authorization.c_str(),saveValvePhaseRecord)) return error();
        // Return to the existing odd-open recipe, not a new general allocator.
        const auto counter=static_cast<std::uint8_t>((valvePhaseGuard.record.phase+1U)/2U);
        if (model=="HTV145FRF") {
            htv145Owners[slot].nextSequence=0x80U|counter;
            htv145Owners[slot].counterAuthenticated=true;
        } else restoreValveControlCounter(counter);
        reportValvePhase(); return true;
    }
    if (!valvePhaseGuard.begin(authorization.c_str(),id.c_str(),
            phase,ordinal,selector,route,millis(),saveValvePhaseRecord)) return error();
    scanChannels=false; valvePhaseSentAt=millis();
    const bool sent=primaryRadio.prepareTransmit() && primaryRadio.transmitAsync(frame,center,kValveProbeWakeSymbols,false,
        rainpoint::pairingPaTableValue(power));
    valvePhaseListening=sent && primaryRadio.setReceiveFrequency(center);
    if (!valvePhaseListening) {
        valvePhaseGuard.fail(); saveValvePhaseRecord(valvePhaseGuard.record);
        primaryRadio.restoreReceiveChannel(kHcs026TelemetryChannel); restoreScanningAfterPairing();
    }
    reportValvePhase(); return true;
}

void observeValvePhase(const rainpoint::commandPhase::Frame& frame) {
    if (!valvePhaseGuard.observe(frame,millis())) return;
    if (!saveValvePhaseRecord(valvePhaseGuard.record)) valvePhaseGuard.fail();
    if (!valvePhaseGuard.listening()) restoreValvePhaseReceiver();
    reportValvePhase(&frame);
}

void pollValvePhase() {
    bool changed=valvePhaseGuard.tick(millis());
    if (valvePhaseGuard.inFlight() && !wifiTransport.authenticated()) { valvePhaseGuard.fail(); changed=true; }
    if (valvePhaseListening && (!valvePhaseGuard.listening() || millis()-valvePhaseSentAt>3'000))
        restoreValvePhaseReceiver();
    if (changed) { saveValvePhaseRecord(valvePhaseGuard.record); reportValvePhase(); }
}
