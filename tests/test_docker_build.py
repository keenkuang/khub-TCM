"""Tests for Docker build configuration — static analysis of Dockerfile.

Since we can't actually run ``docker build`` (requires daemon), we verify:
1. Dockerfile instruction syntax is well-formed
2. All referenced files exist on disk
3. HEALTHCHECK parameters are valid
4. docker-compose.yml can be parsed by ``docker compose config``
"""

import os
import re
import subprocess
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DOCKERFILE = os.path.join(PROJECT_ROOT, "Dockerfile")
COMPOSE_FILE = os.path.join(PROJECT_ROOT, "docker-compose.yml")

# Files referenced in Dockerfile and docker-compose.yml that must exist
REQUIRED_DOCKER_FILES = {
    "Dockerfile",
    "docker-compose.yml",
    "docker-entrypoint.sh",
    "pyproject.toml",
    "nginx/khub-docker.conf",
    "ssl/khub.crt",
    "ssl/khub.key",
}


@pytest.fixture(scope="module")
def dockerfile_lines():
    with open(DOCKERFILE) as f:
        return f.readlines()


def _normalize_instruction(line):
    """Extract the uppercased Dockerfile instruction keyword (FROM, RUN, etc.)."""
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return None
    # Dockerfile instructions are case-insensitive but conventionally uppercase
    match = re.match(r"^(\w+)", stripped)
    return match.group(1).upper() if match else None


# ──────────────────────────────────────────────────────────────
#  Dockerfile instruction tests
# ──────────────────────────────────────────────────────────────


def test_dockerfile_from_instr(dockerfile_lines):
    """First instruction must be ``FROM`` with a valid base image."""
    for line in dockerfile_lines:
        instr = _normalize_instruction(line)
        if instr == "FROM":
            assert "python:" in line, f"Expected python base image, got: {line.strip()}"
            return
    pytest.fail("No FROM instruction found in Dockerfile")


def test_dockerfile_valid_instructions(dockerfile_lines):
    """Every non-comment line should start with a recognised Dockerfile instruction.

    Continuation lines (indented, following a ``\\``-terminated line) are skipped.
    """
    valid_instructions = {
        "FROM", "RUN", "WORKDIR", "COPY", "ADD",
        "CMD", "ENTRYPOINT", "EXPOSE", "ENV", "ARG",
        "LABEL", "MAINTAINER", "USER", "VOLUME",
        "HEALTHCHECK", "SHELL", "STOPSIGNAL", "ONBUILD",
    }
    for i, line in enumerate(dockerfile_lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # Skip continuation lines (indented — preceded by a backslash-terminated line)
        if line[0] in (" ", "\t"):
            continue
        instr = _normalize_instruction(line)
        assert instr in valid_instructions, (
            f"Line {i}: unknown instruction '{instr}' -> {stripped!r}"
        )


def test_dockerfile_healthcheck_syntax(dockerfile_lines):
    """HEALTHCHECK must have valid interval/timeout/retries and a CMD sub-command."""
    healthcheck_lines = []
    in_healthcheck = False
    for line in dockerfile_lines:
        instr = _normalize_instruction(line)
        if instr == "HEALTHCHECK":
            in_healthcheck = True
            healthcheck_lines.append(line.strip())
        elif in_healthcheck:
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            # Continuation lines inside HEALTHCHECK (e.g. CMD ...)
            if _normalize_instruction(line) in {"CMD", None}:
                healthcheck_lines.append(stripped)
            else:
                in_healthcheck = False

    assert healthcheck_lines, "No HEALTHCHECK instruction found"

    # Combine multi-line HEALTHCHECK
    hc_text = " ".join(healthcheck_lines)
    assert "--interval=" in hc_text, "HEALTHCHECK missing --interval"
    assert "--timeout=" in hc_text, "HEALTHCHECK missing --timeout"
    assert "--retries=" in hc_text, "HEALTHCHECK missing --retries"
    assert "CMD" in hc_text, "HEALTHCHECK missing CMD sub-command"


def test_dockerfile_entrypoint_exec_form(dockerfile_lines):
    """ENTRYPOINT should use exec form (JSON array) not shell form."""
    for line in dockerfile_lines:
        instr = _normalize_instruction(line)
        if instr == "ENTRYPOINT":
            stripped = line.strip()
            assert '["' in stripped or '["' in stripped, (
                f"ENTRYPOINT should use exec form (JSON array), got: {stripped}"
            )


def test_dockerfile_expose_port(dockerfile_lines):
    """EXPOSE must specify a valid numeric port."""
    for line in dockerfile_lines:
        instr = _normalize_instruction(line)
        if instr == "EXPOSE":
            parts = line.strip().split()
            assert len(parts) == 2, f"EXPOSE should have exactly one port argument: {line.strip()}"
            port = parts[1]
            assert port.isdigit(), f"EXPOSE port must be numeric, got: {port}"
            assert 1 <= int(port) <= 65535, f"EXPOSE port out of range: {port}"


# ──────────────────────────────────────────────────────────────
#  File existence tests
# ──────────────────────────────────────────────────────────────


def test_docker_key_files_exist():
    """All Docker-related key files must be present in the project root."""
    missing = []
    for rel_path in sorted(REQUIRED_DOCKER_FILES):
        abs_path = os.path.join(PROJECT_ROOT, rel_path)
        if not os.path.exists(abs_path):
            missing.append(rel_path)
    assert not missing, f"Missing Docker-related files: {missing}"


def test_docker_entrypoint_executable():
    """docker-entrypoint.sh should be executable (or at least have a shebang)."""
    entrypoint = os.path.join(PROJECT_ROOT, "docker-entrypoint.sh")
    with open(entrypoint) as f:
        first_line = f.readline().strip()
    assert first_line.startswith("#!/"), (
        f"docker-entrypoint.sh missing shebang, got: {first_line}"
    )


def test_nginx_conf_exists():
    """nginx configuration referenced in docker-compose.yml must exist."""
    nginx_conf = os.path.join(PROJECT_ROOT, "nginx", "khub-docker.conf")
    assert os.path.exists(nginx_conf), f"Missing nginx config: {nginx_conf}"


def test_ssl_cert_files_exist():
    """SSL certificate and key files referenced in docker-compose.yml must exist."""
    cert = os.path.join(PROJECT_ROOT, "ssl", "khub.crt")
    key = os.path.join(PROJECT_ROOT, "ssl", "khub.key")
    assert os.path.exists(cert), f"Missing SSL cert: {cert}"
    assert os.path.exists(key), f"Missing SSL key: {key}"


# ──────────────────────────────────────────────────────────────
#  docker-compose.yml integration test
# ──────────────────────────────────────────────────────────────


def test_docker_compose_config_dry_run():
    """Verify docker-compose.yml can be resolved by ``docker compose config``.

    This does NOT start any containers; it only validates the compose file
    syntax and resolves any variable references.
    """
    result = subprocess.run(
        ["docker", "compose", "config", "--dry-run"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, (
        f"docker compose config --dry-run failed:\n"
        f"STDERR:\n{result.stderr}\n"
        f"STDOUT:\n{result.stdout}"
    )
