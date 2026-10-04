"""Set the NDFC user's default LAN write credentials for DC1 switches."""

import argparse
import json
from pathlib import Path

import yaml

from .config import _environment
from .ndfc_fabric import _BASE, _api
from .nexus_dashboard_browser import NexusDashboardBrowserError, _login, _spki_pin


_GET = _BASE + "/lan-fabric/rest/lanConfig/getDefaultCredentials"
_SAVE = _BASE + "/lan-fabric/rest/lanConfig/saveDefaultCredentials"


def _default_credentials(page):
    status, body = _api(page, "GET", _GET)
    if status != 200 or not isinstance(body, list) or len(body) != 1:
        raise NexusDashboardBrowserError(
            "NDFC default LAN credential readback unavailable: HTTP " + str(status))
    return body[0]


def ensure_default_credentials(intent, username, password):
    """Configure the logged-in user's LAN write credential when still absent."""
    from playwright.sync_api import sync_playwright

    address = intent["management"]["nd"]["address"].split("/")[0]
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True, args=["--ignore-certificate-errors-spki-list=" +
                                 _spki_pin(address)])
        try:
            page = browser.new_page()
            page.goto("https://" + address + "/", wait_until="domcontentloaded",
                      timeout=30000)
            _login(page, username, password, 90)
            current = _default_credentials(page)
            if current.get("sshUserName") and current.get("sshPassword"):
                if current["sshUserName"] != username:
                    raise NexusDashboardBrowserError(
                        "NDFC default LAN credentials belong to another user")
                return {"status": "already-configured"}
            if current.get("sshUserName") or current.get("sshPassword"):
                raise NexusDashboardBrowserError(
                    "NDFC default LAN credentials are partially configured")
            result = page.evaluate("""async ({endpoint, username, password}) => {
                const body = new URLSearchParams({username, password});
                const response = await fetch(endpoint, {
                    method: 'POST',
                    headers: {'Content-Type': 'application/x-www-form-urlencoded'},
                    body
                });
                return {status: response.status};
            }""", {"endpoint": _SAVE, "username": username, "password": password})
            if result["status"] != 200:
                raise NexusDashboardBrowserError(
                    "NDFC default LAN credential save failed with HTTP " +
                    str(result["status"]))
            observed = _default_credentials(page)
            if observed.get("sshUserName") != username or not observed.get("sshPassword"):
                raise NexusDashboardBrowserError(
                    "NDFC default LAN credential readback did not confirm the save")
            return {"status": "configured"}
        finally:
            browser.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("intent", type=Path)
    args = parser.parse_args()
    intent = yaml.safe_load(args.intent.read_text())
    env = _environment(Path.cwd())
    username, password = env.get("CISCO_USERNAME"), env.get("CISCO_PASSWORD")
    if not username or not password:
        raise ValueError("Set CISCO_USERNAME and CISCO_PASSWORD in EVE_ENV_FILE")
    print(json.dumps(ensure_default_credentials(intent, username, password)))


if __name__ == "__main__":
    main()
