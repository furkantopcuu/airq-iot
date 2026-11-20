"""Security checks that must keep passing: no secrets or .env, loopback-only services, safe HTML.

The project needs no API keys or credentials at all (its only outbound traffic is the
checksum-verified dataset / release download), so a secret-looking string is always a mistake.
"""

import re
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from airq.dashboard import data as dash
from airq.iot.broker import broker_config, mosquitto_conf_text
from airq.pipelines import demo
from airq.server.api import create_app

ROOT = Path(__file__).resolve().parents[2]
THIS = "tests/unit/test_security.py"


def tracked_files() -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
        ).stdout.splitlines()
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return out


def tracked_text() -> list[tuple[str, str]]:
    skip_suffix = (".png", ".jpg", ".pdf", ".db", ".parquet", ".zip", ".ico")
    out = []
    for name in tracked_files():
        if name == THIS or name.endswith(skip_suffix):
            continue
        try:
            out.append((name, (ROOT / name).read_text(encoding="utf-8")))
        except (UnicodeDecodeError, FileNotFoundError):
            continue
    return out


# --- secrets and environment files -------------------------------------------------------------
def test_gitignore_blocks_env_and_key_files():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    for needed in (".env*", "*.pem", "*.key", "credentials*"):
        assert needed in rules, needed


def test_no_env_or_key_file_is_tracked():
    bad = [
        n
        for n in tracked_files()
        if re.search(r"(^|/)\.env($|\.)", n)
        and not n.endswith(".example")
        or re.search(r"\.(pem|key|p12|pfx)$", n)
        or re.search(r"(^|/)(id_rsa|credentials|secrets?)(\.|$)", n)
    ]
    assert bad == []


SECRET_PATTERNS = {
    "private key": r"-----BEGIN (RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----",
    "AWS access key": r"AKIA[0-9A-Z]{16}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "Slack token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "Google API key": r"AIza[0-9A-Za-z_-]{30,}",
    "Anthropic / OpenAI style key": r"sk-[A-Za-z0-9_-]{20,}",
    "hard-coded credential": (
        r"(?i)(api[_-]?key|secret|token|passwd|password)\s*[:=]\s*['\"][^'\"\s]{8,}['\"]"
    ),
}


@pytest.mark.parametrize("label,pattern", list(SECRET_PATTERNS.items()))
def test_no_secret_like_string_in_any_tracked_file(label, pattern):
    hits = [name for name, text in tracked_text() if re.search(pattern, text)]
    assert hits == [], f"{label} found in {hits}"


def test_no_personal_absolute_path_in_tracked_files():
    pattern = r"C:\\Users\\|C:/Users/|/home/[a-z][a-z0-9_-]+/|/Users/[A-Za-z]+/"
    hits = [name for name, text in tracked_text() if re.search(pattern, text)]
    assert hits == []


def test_no_unsafe_python_constructs_in_the_package():
    banned = {
        "shell=True": r"shell\s*=\s*True",
        "eval/exec": r"(?<![\w.])(eval|exec)\(",
        "pickle": r"\bimport pickle\b|\bpickle\.load",
        "yaml.load": r"yaml\.load\(",
        "os.system": r"os\.system\(",
        "TLS off": r"verify\s*=\s*False",
    }
    for path in (ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for label, pattern in banned.items():
            assert not re.search(pattern, text), f"{label} in {path.relative_to(ROOT)}"


# --- loopback only -----------------------------------------------------------------------------
def test_every_service_listens_on_the_loopback_interface_only():
    assert broker_config("127.0.0.1", 1883)["listeners"]["default"]["bind"] == "127.0.0.1:1883"
    assert mosquitto_conf_text("127.0.0.1", 1883).startswith("listener 1883 127.0.0.1")
    assert "listener 1883 127.0.0.1" in (ROOT / "configs" / "mosquitto.conf").read_text()
    api = demo.api_args(8000)
    assert api[api.index("--host") + 1] == "127.0.0.1"
    dash_args = demo.dashboard_args(8501)
    assert dash_args[dash_args.index("--server.address") + 1] == "127.0.0.1"
    cfg = (ROOT / ".streamlit" / "config.toml").read_text()
    assert 'address = "127.0.0.1"' in cfg and "enableXsrfProtection = true" in cfg
    assert "0.0.0.0" not in " ".join(demo.api_args(1) + demo.dashboard_args(1))


# --- dashboard HTML ----------------------------------------------------------------------------
def test_station_names_and_flags_from_mqtt_cannot_inject_html():
    evil = "<img src=x onerror=alert(1)>"
    card = dash.station_card(
        {"station": evil, "status": "online", "last_pm25": 90.0, "active_warnings": 0,
         "quality_flags": [evil]},
        [],
    )  # fmt: skip
    html_out = dash.card_html(card)
    assert "<img" not in html_out and "&lt;img" in html_out
    assert "onerror=alert(1)>" not in html_out.replace("&gt;", ">") or "&lt;img" in html_out


# --- API: path traversal, DNS rebinding, CSRF -----------------------------------------------------
class Controller:
    def __init__(self):
        self.sent = []

    def send(self, msg):
        self.sent.append(msg)

    def wait_acks(self, cmd_id, expect=1, timeout_s=3.0):
        from airq.iot.schemas import Ack

        return [Ack(cmd_id=cmd_id, source="fleet", ok=True)]


@pytest.fixture
def client(tmp_path):
    from airq.server import db

    db.connect(tmp_path / "s.db").close()
    (tmp_path / "tables").mkdir()
    (tmp_path / "tables" / "ok.csv").write_text("a\n1\n")
    (tmp_path / "secret.csv").write_text("a\n2\n")  # outside tables/: must not be reachable
    ctl = Controller()
    app = create_app(tmp_path / "s.db", tmp_path, controller=ctl)
    return TestClient(app), ctl


@pytest.mark.parametrize(
    "path",
    [
        "/tables/..%2fsecret",
        "/tables/../secret",
        "/tables/..%5csecret",
        "/figures/..%2f..%2fx",
        "/tables/%2e%2e/secret",
        "/tables/ok.csv",
    ],  # a dot is not allowed in a name either
)
def test_file_endpoints_refuse_path_traversal(client, path):
    c, _ = client
    assert c.get(path).status_code in (404, 422)


def test_only_a_plain_name_inside_tables_is_served(client):
    c, _ = client
    assert c.get("/tables/ok").status_code == 200


def test_a_foreign_host_header_is_refused_dns_rebinding(client):
    c, _ = client
    assert c.get("/health", headers={"host": "evil.example.com"}).status_code == 400
    assert c.get("/health", headers={"host": "127.0.0.1:8000"}).status_code == 200
    assert c.get("/health", headers={"host": "localhost:8000"}).status_code == 200


def test_control_posts_from_a_foreign_origin_are_refused_csrf(client):
    c, ctl = client
    for origin in ("https://evil.example.com", "http://192.168.1.7:8501", "null"):
        r = c.post("/control/reset", headers={"origin": origin})
        assert r.status_code == 403, origin
    assert ctl.sent == []  # nothing reached the MQTT controller
    ok = c.post(
        "/control/fleet", json={"action": "pause"}, headers={"origin": "http://localhost:8501"}
    )
    assert ok.status_code == 200  # the dashboard / a local page is fine
    assert (
        c.post("/control/fleet", json={"action": "resume"}).status_code == 200
    )  # no Origin: Python
    assert c.get("/health", headers={"origin": "https://evil.example.com"}).status_code == 200


def test_the_security_policy_names_the_known_limits():
    text = (ROOT / "SECURITY.md").read_text(encoding="utf-8")
    for must in ("no authentication", "localhost", "private vulnerability reporting"):
        assert must in text or must.replace("no ", "**no ") in text
