"""TLS-PSK transport using existing private credentials, never plaintext fallback.

TLS provides record integrity, confidentiality and replay protection. Application
command IDs/counters still prevent logical duplicate actions across sessions.
Credential lookup runs for each handshake; no session tickets bypass revocation.
"""
import re
import ssl
from collections.abc import Callable

PSK_CIPHERS = "ECDHE-PSK-CHACHA20-POLY1305:PSK-AES128-GCM-SHA256"


def client_context(token: str, *, identity: str = "management") -> ssl.SSLContext:
    """Explicitly authenticated client for local diagnostic tools."""
    key = token.encode() if identity == "management" else bytes.fromhex(token)
    if not 32 <= len(key) <= 256:
        raise ValueError("TLS requires a high-entropy credential")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE  # TLS-PSK verifies the peer, not X.509.
    context.minimum_version = context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.set_ciphers(PSK_CIPHERS)
    context.set_psk_client_callback(lambda hint: (identity, key))
    return context


def server_context(credential: Callable[[str], str | None]) -> ssl.SSLContext:
    if not hasattr(ssl.SSLContext, "set_psk_server_callback"):
        raise RuntimeError("Encrypted RainPoint sessions require Python 3.13+ with TLS-PSK")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.maximum_version = ssl.TLSVersion.TLSv1_2
    context.options |= ssl.OP_NO_TICKET
    context.set_ciphers(PSK_CIPHERS)

    def lookup(identity):
        if not isinstance(identity, str) or len(identity) > 64:
            return b""
        token = credential(identity)
        if identity == "management":
            return token.encode() if isinstance(token, str) and 32 <= len(token.encode()) <= 256 else b""
        if not isinstance(token, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", token):
            return b""
        return bytes.fromhex(token)

    context.set_psk_server_callback(lookup)
    return context
