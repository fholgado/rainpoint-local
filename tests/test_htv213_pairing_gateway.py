"""Unassigned-node and explicit-input gates; no real node or RF access."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import json
import threading
from urllib.request import Request, urlopen
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"rainpointd_addon"))
from rainpointd.gateway import Gateway
from rainpointd import htv213_pairing as pairing
from rainpointd.http import create_server

NODE="rp-001122334455"


def request():
    return {"node_id":NODE,"factory_endpoint":"11556677","dry_valve_confirmed":True,
            "duration_seconds":300,"device_address":2,"assigned_selector":11,
            "timing_raw":480,"notification_phase":2,"initial_center_hz":434351500,
            "routine_center_hz":434241500,"reply_delay_us":49000,
            "notification_delay_ms":1000,"power_dbm":0}


class Htv213PairingGatewayTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.gateway=Gateway(transport="network",storage_path=str(Path(self.temp.name)/"gateway.sqlite"),registry_token="test-token")
        self.addCleanup(self.gateway.close)
        self.gateway.register_radio_node(node_id=NODE,token="ab"*32,name="Dry test",area=None)
        self.gateway.update_node(NODE,connected=True,authenticated=True,tx_armed=False,
            capabilities=["rx","sensor_pairing_tx",pairing.CAPABILITY])
        self.sent=[]
        self.gateway.set_node_command_sender(lambda node,command:self.sent.append((node,command)))

    def test_dispatch_uses_generated_gateway_identity_without_registration(self):
        result=pairing.start(self.gateway,request())
        command=self.sent[0][1]
        self.assertEqual(command["controller_endpoint"],self.gateway.rf_identity.controller_endpoint)
        self.assertEqual(command["companion_endpoint"],self.gateway.rf_identity.companion_endpoint)
        self.assertEqual(command["type"],"htv213_pairing_start")
        self.assertFalse(result["operational"])
        self.assertEqual(self.gateway._store.valve_registry(),[])

    def test_explicit_bounds_and_dry_confirmation(self):
        for key,value in (("dry_valve_confirmed",False),("factory_endpoint",""),
                          ("duration_seconds",301),("notification_phase",64),
                          ("initial_center_hz",0),("device_address",True),
                          ("reply_delay_us",0),("power_dbm",8)):
            with self.subTest(key=key),self.assertRaises(ValueError):
                pairing.start(self.gateway,{**request(),key:value})
        self.assertEqual(self.sent,[])

    def test_old_firmware_and_assigned_node_rejected(self):
        self.gateway.update_node(NODE,capabilities=["rx","sensor_pairing_tx"])
        with self.assertRaisesRegex(ValueError,"canary"):
            pairing.start(self.gateway,request())
        self.gateway.update_node(NODE,capabilities=[pairing.CAPABILITY])
        with patch.object(self.gateway._store,"ack_assignments",return_value=[{"node_id":NODE}]):
            with self.assertRaisesRegex(ValueError,"unassigned"):
                pairing.start(self.gateway,request())
        self.assertEqual(self.sent,[])

    def test_no_duplicate_before_ack_and_correlated_cancel(self):
        status=pairing.start(self.gateway,request())
        with self.assertRaisesRegex(ValueError,"already requested"):
            pairing.start(self.gateway,request())
        with self.assertRaises(ValueError):
            pairing.cancel(self.gateway,{"node_id":NODE,"command_id":"stale"})
        pairing.cancel(self.gateway,{"node_id":NODE,"command_id":status["command_id"]})
        self.assertEqual(len(self.sent),2)
        self.assertEqual(self.sent[-1][1]["type"],"htv213_pairing_cancel")
        with self.assertRaises(ValueError):pairing.start(self.gateway,request())
        pairing.observe(self.gateway,NODE,{"command_id":status["command_id"],"state":"failed","failure":4})
        pairing.start(self.gateway,request())

    def test_status_is_correlated_and_never_enables_water_controls(self):
        status=pairing.start(self.gateway,request())
        pairing.observe(self.gateway,NODE,{"command_id":"stale","state":"observed"})
        self.assertEqual(self.gateway._nodes[NODE]["htv213_pairing"]["state"],"requested")
        pairing.observe(self.gateway,NODE,{"command_id":status["command_id"],"state":"observed",
                                         "operational":True,"plans_sent":3})
        self.assertFalse(self.gateway._nodes[NODE]["htv213_pairing"]["operational"])
        self.assertEqual(self.gateway._store.valve_registry(),[])

    def test_suppressed_target_and_indeterminate_delivery_fail_closed(self):
        with patch.object(self.gateway,"endpoint_suppressed",return_value=True):
            with self.assertRaises(ValueError):pairing.start(self.gateway,request())
        self.gateway.set_node_command_sender(lambda *_:(_ for _ in ()).throw(ConnectionError()))
        with self.assertRaises(ConnectionError):pairing.start(self.gateway,request())
        with self.assertRaises(ValueError):pairing.start(self.gateway,request())

    def test_candidate_blocks_regular_pairing_and_errors_remain_correlated(self):
        status=pairing.start(self.gateway,request())
        with self.assertRaisesRegex(ValueError,"HTV213"):
            self.gateway.start_pairing()
        self.assertFalse(pairing.observe_error(self.gateway,NODE,{"command_id":"stale"}))
        self.assertTrue(pairing.observe_error(self.gateway,NODE,{"command_id":status["command_id"]}))
        self.assertEqual(self.gateway._nodes[NODE]["htv213_pairing"]["state"],"command_rejected")
        self.assertTrue(pairing.busy(self.gateway))

    def test_late_terminal_from_old_node_cannot_release_new_lease(self):
        status=pairing.start(self.gateway,request())
        other="rp-aabbccddeeff"
        self.gateway._htv213_experiment_owner=(other,"new-session")
        pairing.observe(self.gateway,NODE,{"command_id":status["command_id"],"state":"failed"})
        self.assertTrue(pairing.busy(self.gateway))

    def test_http_requires_authentication_and_returns_explicit_pending_state(self):
        server=create_server(self.gateway,port=0)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            url=f"http://127.0.0.1:{server.server_port}/api/v1/pairing/htv213/start"
            headers={"Content-Type":"application/json"}
            payload=json.dumps(request()).encode()
            with self.assertRaises(HTTPError) as raised:
                urlopen(Request(url,data=payload,headers=headers),timeout=2)
            self.assertEqual(raised.exception.code,401)
            raised.exception.close()
            self.assertEqual(self.sent,[])
            headers["Authorization"]="Bearer test-token"
            with urlopen(Request(url,data=payload,headers=headers),timeout=2) as response:
                self.assertEqual(response.status,202)
                self.assertEqual(json.load(response)["state"],"requested")
        finally:
            server.shutdown();server.server_close();thread.join(timeout=2)
