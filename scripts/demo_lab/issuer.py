from pathlib import Path
import json, ssl, threading, time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import jwt
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def fixture(directory, env):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.now(timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=5))
        .not_valid_after(now + timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), True)
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), False)
        .sign(key, hashes.SHA256())
    )
    d = Path(directory)
    (d / "cert.pem").write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    (d / "key.pem").write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", alg="RS256")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"keys": [jwk]}).encode())

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(d / "cert.pem", d / "key.pem")
    server.socket = ctx.wrap_socket(server.socket, server_side=True)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    issuer = f"https://localhost:{server.server_port}"
    env.update(
        OIDC_ISSUER=issuer,
        OIDC_JWKS_URL=issuer + "/keys",
        OIDC_AUDIENCE="pilot",
        OIDC_REVIEWER_SUBJECTS="staff-demo",
        SSL_CERT_FILE=str(d / "cert.pem"),
        PILOT_PHONE="9876543212",
    )
    for var, sub in [
        ("PILOT_APPLICANT_TOKEN", "customer-demo"),
        ("PILOT_REVIEWER_TOKEN", "staff-demo"),
    ]:
        env[var] = jwt.encode(
            {
                "iss": issuer,
                "aud": "pilot",
                "sub": sub,
                "iat": int(time.time()),
                "exp": int(time.time()) + 1200,
                "phone_number_verified": True,
                "phone_number": "+919876543212",
            },
            key,
            algorithm="RS256",
            headers={"kid": "test-key"},
        )
    return server
