"""Exercise real TLS handshakes against the production HTTP listener."""
import json
import hashlib
import hmac
import socket
import ssl
import threading
import unittest
import asyncio
import importlib
from pathlib import Path
import sys
import types
from urllib.request import urlopen

from rainpointd.gateway import Gateway
from rainpointd.http import create_server
from rainpointd.secure_transport import PSK_CIPHERS, server_context
from rainpointd.esp32_network import ESP32NetworkServer


def client_context(identity, key):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # TLS-PSK authenticates the server.
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(PSK_CIPHERS)
    context.set_psk_client_callback(lambda hint: (identity, key.encode() if identity == "management" else bytes.fromhex(key)))
    return context


class SecureTransportTest(unittest.TestCase):
    def setUp(self):
        self.key = "42" * 32
        self.gateway = Gateway(registry_token=self.key)
        self.context = server_context(lambda identity: self.key if identity == "management" else None)
        self.server = create_server(self.gateway, port=0, tls_context=self.context)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.gateway.close()

    def test_encrypted_api_authenticates_peer_and_returns_info(self):
        context = client_context("management", self.key)
        with urlopen(f"https://127.0.0.1:{self.server.server_port}/api/v1/info", context=context, timeout=2) as response:
            self.assertEqual("v1", json.load(response)["api_version"])

    def test_actual_ha_client_reads_authenticates_and_rotates_over_tls(self):
        import aiohttp
        package_name = "rainpoint_tls_client_test"
        package = types.ModuleType(package_name)
        package.__path__ = [str(Path(__file__).resolve().parents[1] / "custom_components/rainpoint_local")]
        sys.modules[package_name] = package
        api = importlib.import_module(f"{package_name}.api")
        self.server.tls_context = server_context(lambda identity: self.gateway._registry_token
                                                if identity == "management" else None)
        async def exercise():
            async with aiohttp.ClientSession() as session:
                client = api.RainPointLocalClient("127.0.0.1", self.server.server_port, session, token=self.key)
                self.assertEqual("v1", (await client.info()).api_version)
                await client.authenticate(self.key)
                replacement = await client.rotate_management_token(self.key)
                await client.authenticate(replacement)
                self.assertEqual("v1", (await client.info()).api_version)
        try:
            asyncio.run(exercise())
        finally:
            for name in list(sys.modules):
                if name == package_name or name.startswith(package_name + "."):
                    sys.modules.pop(name)

    def test_wrong_secret_and_unknown_identity_cannot_connect(self):
        for identity, key in (("management", "43" * 32), ("unregistered", self.key)):
            with self.subTest(identity=identity), self.assertRaises(OSError):
                with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as raw:
                    client_context(identity, key).wrap_socket(raw, server_hostname="localhost")

    def test_plaintext_has_no_fallback(self):
        with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as raw:
            raw.sendall(b"GET /api/v1/info HTTP/1.0\r\n\r\n")
            try:
                self.assertNotIn(b"api_version", raw.recv(4096))
            except ConnectionResetError:
                pass

    def test_rotated_key_rejects_new_connections_with_old_key(self):
        old = self.key
        self.key = "44" * 32
        with self.assertRaises(OSError):
            with socket.create_connection(("127.0.0.1", self.server.server_port), timeout=2) as raw:
                client_context("management", old).wrap_socket(raw, server_hostname="localhost")
        self.test_encrypted_api_authenticates_peer_and_returns_info()

    def test_encrypted_radio_retains_mutual_authentication_and_multi_valve_capability(self):
        node = "rp-001122334455"
        tls = server_context(lambda identity: self.key if identity == node else None)
        server = ESP32NetworkServer(self.gateway, host="127.0.0.1", port=0,
            node_tokens={node: self.key}, tls_context=tls)
        server.start()
        try:
            with socket.create_connection(("127.0.0.1", server.server_port), timeout=3) as raw:
                with client_context(node, self.key).wrap_socket(raw, server_hostname="localhost") as connection:
                    self.assertEqual("TLSv1.2", connection.version())
                    with connection.makefile("rwb", buffering=0) as stream:
                        challenge = json.loads(stream.readline())
                        nonce = challenge["nonce"]
                        proof = hmac.new(self.key.encode(), f"rainpoint-node-v2\n{nonce}\n{node}".encode(), hashlib.sha256).hexdigest()
                        stream.write(json.dumps({"type":"node_hello", "node_id":node,
                            "protocol_version":2, "proof":proof, "mode":"local_radio_node",
                            "capabilities":["rx", "sensor_pairing_tx", "htv145_multi_valve"]}).encode()+b"\n")
                        response = json.loads(stream.readline())
                        self.assertEqual("node_authenticated", response["type"])
                        expected = hmac.new(self.key.encode(), f"rainpoint-gateway-v2\n{nonce}\n{node}".encode(), hashlib.sha256).hexdigest()
                        self.assertEqual(expected, response["server_proof"])
        finally:
            server.stop()
