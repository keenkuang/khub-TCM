"""Tests for docker-compose.yml validity — structural checks via PyYAML.

Verifies:
1. YAML can be parsed and has expected top-level keys
2. All services reference valid images or build contexts
3. Environment variables follow KEY=VALUE format
4. Volume mounts reference existing local paths
5. Healthcheck configuration is well-formed
"""

import os
import yaml
import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COMPOSE_FILE = os.path.join(PROJECT_ROOT, "docker-compose.yml")

# Services we expect to find in the compose file
EXPECTED_SERVICES = {"khub", "nginx"}

# Valid sub-command values for docker-compose healthcheck.test
VALID_HC_COMMANDS = {"CMD", "CMD-SHELL", "NONE"}


@pytest.fixture(scope="module")
def compose_data():
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


# ──────────────────────────────────────────────────────────────
#  Top-level structure
# ──────────────────────────────────────────────────────────────


def test_compose_top_level_keys(compose_data):
    """docker-compose.yml must have the required top-level sections."""
    assert "services" in compose_data, "Missing 'services' top-level key"
    assert isinstance(compose_data["services"], dict), "'services' must be a mapping"


def test_compose_required_services(compose_data):
    """All expected services must be defined."""
    services = set(compose_data.get("services", {}).keys())
    missing = EXPECTED_SERVICES - services
    assert not missing, f"Missing expected services: {missing}"


def test_compose_volumes_defined(compose_data):
    """Named volumes used by services should be declared at top level."""
    declared_volumes = set(compose_data.get("volumes", {}).keys())
    # Collect volumes referenced by services
    referenced_volumes = set()
    for svc_name, svc_config in compose_data.get("services", {}).items():
        for vol in svc_config.get("volumes", []):
            if isinstance(vol, str):
                name = vol.split(":")[0]
            elif isinstance(vol, dict):
                name = vol.get("source", "")
            else:
                continue
            # Only check named volumes (not bind mounts like ./path)
            if name and not name.startswith(".") and not name.startswith("/"):
                referenced_volumes.add(name)
    undeclared = referenced_volumes - declared_volumes
    assert not undeclared, f"Volumes used but not declared: {undeclared}"


def test_compose_networks_defined(compose_data):
    """Network used by services should be declared at top level."""
    declared_networks = set(compose_data.get("networks", {}).keys())
    referenced_networks = set()
    for svc_name, svc_config in compose_data.get("services", {}).items():
        nets = svc_config.get("networks", [])
        if isinstance(nets, list):
            for n in nets:
                if isinstance(n, str):
                    referenced_networks.add(n)
                elif isinstance(n, dict):
                    referenced_networks.update(n.keys())
        elif isinstance(nets, dict):
            referenced_networks.update(nets.keys())
    undeclared = referenced_networks - declared_networks
    assert not undeclared, f"Networks used but not declared: {undeclared}"


# ──────────────────────────────────────────────────────────────
#  Service-level checks
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_service_image_or_build(compose_data, svc_name):
    """Every service must specify either ``image`` or ``build`` (or both)."""
    svc = compose_data["services"].get(svc_name)
    assert svc is not None, f"Service '{svc_name}' not found"
    has_image = "image" in svc
    has_build = "build" in svc
    assert has_image or has_build, (
        f"Service '{svc_name}' must specify 'image' or 'build'"
    )


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_service_restart_policy(compose_data, svc_name):
    """Every service should have a restart policy."""
    svc = compose_data["services"][svc_name]
    assert "restart" in svc, (
        f"Service '{svc_name}' missing restart policy"
    )


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_service_resource_limits(compose_data, svc_name):
    """Services should declare resource limits (mem_limit / cpus)."""
    svc = compose_data["services"][svc_name]
    has_mem_limit = "mem_limit" in svc or "mem_reservation" in svc
    has_cpu = "cpus" in svc
    # Only warn — not all services require limits, but they're good practice
    if not has_mem_limit and not has_cpu:
        pytest.skip(f"Service '{svc_name}' has no resource limits (non-critical)")


# ──────────────────────────────────────────────────────────────
#  Environment variable checks
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_env_var_format(compose_data, svc_name):
    """Environment variables must follow ``KEY=value`` format."""
    svc = compose_data["services"][svc_name]
    env = svc.get("environment", {})
    if not env:
        pytest.skip(f"Service '{svc_name}' has no environment variables")
    if isinstance(env, list):
        for entry in env:
            assert isinstance(entry, str), (
                f"Service '{svc_name}': env list entry must be string, got {type(entry)}"
            )
            # Accept KEY=value or bare KEY (for host env passthrough)
            if "=" in entry:
                key, _, val = entry.partition("=")
                assert key.strip(), (
                    f"Service '{svc_name}': empty env key in '{entry}'"
                )
    elif isinstance(env, dict):
        for key, val in env.items():
            assert isinstance(key, str) and key.strip(), (
                f"Service '{svc_name}': empty env key in mapping"
            )


# ──────────────────────────────────────────────────────────────
#  Volume mount checks
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_volume_mounts(compose_data, svc_name):
    """Bind-mount volumes referencing local paths must exist on disk."""
    svc = compose_data["services"][svc_name]
    for vol in svc.get("volumes", []):
        if isinstance(vol, str):
            source = vol.split(":")[0]
        elif isinstance(vol, dict):
            source = vol.get("source", "")
        else:
            continue
        # Only check bind-mounts (start with . or /)
        if source.startswith(".") or source.startswith("/"):
            abs_source = os.path.join(PROJECT_ROOT, source)
            assert os.path.exists(abs_source), (
                f"Service '{svc_name}': bind-mount source '{source}' not found "
                f"(resolved: {abs_source})"
            )


# ──────────────────────────────────────────────────────────────
#  Healthcheck checks
# ──────────────────────────────────────────────────────────────


@pytest.mark.parametrize("svc_name", sorted(EXPECTED_SERVICES))
def test_compose_healthcheck_config(compose_data, svc_name):
    """Verify healthcheck.test uses valid command syntax."""
    svc = compose_data["services"][svc_name]
    hc = svc.get("healthcheck")
    if hc is None:
        pytest.skip(f"Service '{svc_name}' has no healthcheck")
    test_instr = hc.get("test")
    assert test_instr is not None, (
        f"Service '{svc_name}': healthcheck missing 'test' command"
    )
    if isinstance(test_instr, list):
        command_type = test_instr[0]
        assert command_type in VALID_HC_COMMANDS, (
            f"Service '{svc_name}': invalid healthcheck command type '{command_type}', "
            f"expected one of {VALID_HC_COMMANDS}"
        )
        assert len(test_instr) > 1, (
            f"Service '{svc_name}': healthcheck test list must have at least "
            f"a command type and a command"
        )
    elif isinstance(test_instr, str):
        # NONE means disable; anything else should be a command
        if test_instr != "NONE":
            assert test_instr.startswith("CMD ") or test_instr.startswith("CMD-SHELL ") or test_instr == "NONE", (
                f"Service '{svc_name}': string healthcheck.test should be "
                f"'CMD ...', 'CMD-SHELL ...', or 'NONE', got: {test_instr}"
            )

    # Check interval/timeout/retries types
    for field in ("interval", "timeout", "start_period"):
        val = hc.get(field)
        if val is not None:
            val_str = str(val)
            assert any(unit in val_str for unit in ("s", "m", "h", "ms", "us", "ns")), (
                f"Service '{svc_name}': healthcheck.{field} must have a duration suffix, "
                f"got: {val}"
            )
