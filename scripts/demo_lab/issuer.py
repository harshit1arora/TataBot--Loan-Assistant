from pathlib import Path
import json, ssl, threading, time
from datetime import datetime, timezone, timedelta
from http.server import BaseHTTPRequestHandler
from base64 import urlsafe_b64encode
from hashlib import sha256
from html import escape
from secrets import token_urlsafe
from urllib.parse import parse_qs, urlencode, urlsplit
from http.server import ThreadingHTTPServer
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

    codes = {}

    class Handler(BaseHTTPRequestHandler):
        def output(self, payload, content="application/json"):
            self.send_response(200)
            self.send_header("Content-Type", content)
            self.send_header("Access-Control-Allow-Origin", env.get("LAB_BROWSER_ORIGIN", "null"))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(
                (json.dumps(payload) if content == "application/json" else payload).encode()
            )

        def do_GET(self):
            path = urlsplit(self.path)
            if path.path == "/keys":
                return self.output({"keys": [jwk]})
            if path.path == "/.well-known/openid-configuration":
                return self.output(
                    {
                        "issuer": issuer,
                        "authorization_endpoint": issuer + "/authorize",
                        "token_endpoint": issuer + "/token",
                        "jwks_uri": issuer + "/keys",
                        "response_types_supported": ["code"],
                        "subject_types_supported": ["public"],
                        "id_token_signing_alg_values_supported": ["RS256"],
                        "code_challenge_methods_supported": ["S256"],
                    }
                )
            params = {k: v[0] for k, v in parse_qs(path.query).items()}
            if (
                path.path != "/authorize"
                or params.get("redirect_uri") != env.get("LAB_BROWSER_ORIGIN", "") + "/identity"
                or params.get("client_id") != "pilot"
                or params.get("code_challenge_method") != "S256"
            ):
                return self.send_error(400)
            if params.get("role") not in ("applicant", "reviewer"):
                links = [
                    f'<a href="?{escape(urlencode(dict(params, role=role)))}">{role}</a>'
                    for role in ("applicant", "reviewer")
                ]
                return self.output(" ".join(links), "text/html")
            code = token_urlsafe(32)
            codes[code] = params
            self.send_response(302)
            self.send_header(
                "Location",
                params["redirect_uri"] + "?" + urlencode({"code": code, "state": params["state"]}),
            )
            self.end_headers()

        def do_POST(self):
            params = {
                k: v[0]
                for k, v in parse_qs(
                    self.rfile.read(int(self.headers["Content-Length"])).decode()
                ).items()
            }
            request = codes.pop(params.get("code", ""), None)
            challenge = (
                urlsafe_b64encode(sha256(params.get("code_verifier", "").encode()).digest())
                .decode()
                .rstrip("=")
            )
            if (
                self.path != "/token"
                or not request
                or request["code_challenge"] != challenge
                or params.get("redirect_uri") != request["redirect_uri"]
                or params.get("client_id") != "pilot"
            ):
                return self.send_error(400)
            claims = {
                "iss": issuer,
                "aud": "pilot",
                "sub": "staff-demo" if request["role"] == "reviewer" else "browser-applicant",
                "iat": int(time.time()),
                "exp": int(time.time()) + 900,
                "phone_number": "+919876543213",
                "phone_number_verified": True,
            }
            if request.get("nonce"):
                claims["nonce"] = request["nonce"]
            token = jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})
            self.output(
                {
                    "token_type": "Bearer",
                    "expires_in": 900,
                    "access_token": token_urlsafe(32),
                    "id_token": token,
                }
            )

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
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
