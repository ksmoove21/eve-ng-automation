"""Repository configuration and local credentials."""

import os
from pathlib import Path

import yaml


def _read_environment_file(path: Path) -> dict[str, str]:
    """Read a simple local KEY=value file without exposing its values."""
    if not path.is_file():
        raise ValueError("EVE_ENV_FILE must name an existing regular file")
    values = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            key, separator, value = line.partition("=")
            if not separator:
                raise ValueError("Invalid environment entry; expected KEY=value")
            values[key.strip()] = value.strip()
    return values


def _environment(root: Path) -> dict[str, str]:
    """Resolve the workspace .env or an explicit private environment source."""
    env = dict(os.environ)
    selected = env.get("EVE_ENV_FILE")
    if selected:
        path = Path(selected).expanduser()
        if not path.is_absolute():
            raise ValueError("EVE_ENV_FILE must be an absolute path")
        for key, value in _read_environment_file(path).items():
            if key != "EVE_ENV_FILE":
                env[key] = value
        return env
    return env


def load_server(root: Path, name: str, auth: str = "web") -> dict:
    """Read simple KEY=value credentials; shell environment takes precedence."""
    env = _environment(root)
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                key, separator, value = line.partition("=")
                if not separator:
                    raise ValueError("Invalid .env entry; expected KEY=value")
                env.setdefault(key.strip(), value.strip())
    config = yaml.safe_load((root / "config/servers.yaml").read_text())
    try:
        server = dict(config["servers"][name])
    except KeyError:
        raise ValueError(f"Unknown server: {name}") from None
    fields = ("ssh_username", "ssh_password") if auth == "ssh" else ("username", "password")
    for field in ("url", "ssh_host"):
        variable = server.get(f"{field}_env")
        if variable:
            if not env.get(variable):
                raise ValueError(f"Set {variable} in the selected EVE environment")
            server[field] = env[variable]
    for field in fields:
        variable = server.get(f"{field}_env", f"EVE_{field.upper()}")
        if not env.get(variable):
            raise ValueError(f"Set {variable} in the environment or .env")
        server[field] = env[variable]
    return server
