"""Browser-driven initial Nexus Dashboard Cluster Bringup.

Cisco documents the HTTPS Cluster Bringup wizard, rather than a public API,
for the initial deployment of pre-3.2.2 Linux KVM appliances. This module
therefore automates that documented UI only. It never calls private XHR APIs.
"""

import base64
import hashlib
import json
import socket
import ssl
import time
from ipaddress import IPv4Interface, IPv4Network


class NexusDashboardBrowserError(RuntimeError):
    """A safe, actionable browser bootstrap error."""


def _spki_pin(address, timeout=10):
    """Return the target TLS public-key pin for one constrained browser launch."""
    try:
        from cryptography import x509
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        context = ssl._create_unverified_context()
        with socket.create_connection((address, 443), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=address) as tls:
                certificate = x509.load_der_x509_certificate(
                    tls.getpeercert(binary_form=True))
    except (ImportError, OSError, ssl.SSLError, ValueError) as error:
        raise NexusDashboardBrowserError(
            "Could not obtain the declared Nexus Dashboard TLS public key") from error
    public_key = certificate.public_key().public_bytes(
        Encoding.DER, PublicFormat.SubjectPublicKeyInfo)
    return base64.b64encode(hashlib.sha256(public_key).digest()).decode("ascii")


def _table(page, title):
    table = page.locator(".add-edit-table").filter(has_text=title)
    if table.count() != 1:
        raise NexusDashboardBrowserError(
            "Nexus Dashboard Cluster Bringup did not expose the expected " + title + " table")
    return table


def _add_rows(page, title, add_label, values):
    """Create and commit one inline wizard row for each value."""
    table = _table(page, title)
    for index, value in enumerate(values):
        page.get_by_text(add_label, exact=True).click()
        row = table.locator(".add-edit-table-edit-item").last
        field = row.locator("input[type=text]")
        # The 3.2.1i NTP editor uses a combobox outside the generic row wrapper.
        if field.count() == 0 and title == "NTP Host":
            field = page.locator("[data-testid=ntpServershost]").last
        if field.count() != 1:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard Cluster Bringup did not expose the expected value field")
        field.fill(value)
        if title == "NTP Host" and index == 0:
            preferred = table.locator(".add-edit-col-2 input[type=checkbox]").last
            if preferred.count() != 1:
                raise NexusDashboardBrowserError(
                    "Nexus Dashboard Cluster Bringup did not expose the NTP Preferred control")
            preferred.locator("xpath=..").click()
            if not preferred.is_checked():
                raise NexusDashboardBrowserError("Nexus Dashboard did not accept the NTP Preferred selection")
        # The action column is a sibling of the editable value cell in the 3.2.1i wizard DOM.
        confirm = table.locator(".xicon-checked-circle-white").last
        if confirm.count() != 1:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard Cluster Bringup did not expose the row confirmation control")
        confirm.click()
        # The wizard performs asynchronous row validation; do not race its modal loader.
        page.locator(".loader.translucent").wait_for(
            state="detached", timeout=90000 if title == "NTP Host" else 30000)
        page.wait_for_timeout(100)


def _validation_errors(page):
    """Return safe user-visible wizard validation text without a page dump."""
    messages = []
    for value in page.locator(
            ".edit-item-error-message, .input-error-message, .error-message, [role=alert]").all_text_contents():
        normalized = " ".join(value.split())
        if normalized and normalized not in messages:
            messages.append(normalized)
    return messages[:10]


def _state(page):
    text = " ".join(page.locator("body").inner_text().split())
    if "Answer some questions" in text and "Configuration" in text:
        return "awaiting-bringup"
    if ("Bootstrap Cluster Deployment" in text
            or "Service Installation is in progress" in text):
        return "initializing"
    if "Nexus Dashboard Overview" in text or "Nexus Dashboard" in text:
        return "ready-or-post-bringup"
    return "unknown"


def _login(page, username, password, timeout):
    """Wait for either the login form or an already-authenticated Dashboard."""
    password_field = page.locator("input[type=password]")
    deadline = time.monotonic() + min(30, max(1, timeout))
    while password_field.count() == 0 and time.monotonic() < deadline:
        body = page.locator("body").inner_text()
        if "Nexus Dashboard" in body or page.locator("nd-launcher").count():
            return False
        page.wait_for_timeout(250)
    if password_field.count() == 0:
        raise NexusDashboardBrowserError("Nexus Dashboard did not render login or Dashboard UI")
    username_field = page.locator("#username")
    if username_field.count() > 1:
        raise NexusDashboardBrowserError("Nexus Dashboard exposed ambiguous username controls")
    if username_field.count() == 1:
        username_field.fill(username)
    password_field.first.fill(password)
    login = page.get_by_role("button", name="Login")
    if login.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard login button was not uniquely available")
    login.click()
    page.wait_for_timeout(min(5000, timeout * 1000))
    if page.locator("input[type=password]").count():
        raise NexusDashboardBrowserError("Nexus Dashboard rejected the configured administrator password")
    return True


def _normalize_invalid_internal_networks(page):
    """Correct only UI-marked invalid default app/service CIDR values."""
    advanced = page.get_by_text("Advanced Settings", exact=True)
    if advanced.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Configuration did not expose Advanced Settings")
    pane = advanced.locator("xpath=../../..")
    pane.locator(".collapsible-pane-header-wrapper").click()
    for label in ("App Network", "Service Network"):
        control = page.get_by_label(label, exact=True)
        if control.count() != 1:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard Configuration did not expose " + label)
        if "input--invalid" not in (control.get_attribute("class") or ""):
            continue
        try:
            normalized = str(IPv4Network(control.input_value(), strict=False))
        except ValueError as error:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard supplied an invalid " + label + " default") from error
        control.fill(normalized)
        control.press("Tab")

def _configuration(page, intent):
    """Fill only the documented Configuration step using semantic controls."""
    name = page.get_by_label("Nexus Dashboard Cluster Name", exact=True)
    if name.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Cluster Bringup did not expose its cluster-name field")
    name.fill(intent["cluster_name"])
    _add_rows(page, "DNS Provider IP Address", "Add DNS Provider", intent["dns_servers"])
    # NTP remains disabled until its committed DNS dependency propagates.
    page.get_by_text("NTP will be disabled until DNS Provider is added", exact=True).wait_for(
        state="detached", timeout=10000)
    _add_rows(page, "DNS Search Domain", "Add DNS Search Domain", intent["search_domains"])
    _add_rows(page, "NTP Host", "Add NTP Host Name/IP Address", intent["ntp_servers"])
    _normalize_invalid_internal_networks(page)
    skip_proxy = page.get_by_text("Skip Proxy", exact=True)
    if skip_proxy.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Configuration did not expose Skip Proxy")
    skip_proxy.click()
    confirm = page.get_by_text("Confirm", exact=True)
    if confirm.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard did not present the Skip Proxy confirmation")
    confirm.click()
    page.wait_for_timeout(300)
    next_button = page.get_by_role("button", name="Next")
    if next_button.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Configuration step did not expose a unique Next button")
    next_button.click()
    try:
        page.get_by_role("heading", name="Node Details", exact=True).wait_for(timeout=30000)
    except Exception as error:
        errors = _validation_errors(page)
        text = " ".join(page.locator("body").inner_text().split())
        if "Can not reach NTP on Management Network" in text:
            errors.append("NTP endpoints are unreachable on the management network")
        detail = "; ".join(dict.fromkeys(errors)) or "Node Details did not appear"
        raise NexusDashboardBrowserError(
            "Nexus Dashboard Configuration did not advance: " + detail) from error


def _node_details(page, intent):
    """Configure the primary-node data interface through the documented UI."""
    edit = page.locator(".icon-edit")
    if edit.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Node Details did not expose one primary-node edit action")
    edit.click()
    name = page.locator("[data-testid=nodeName]")
    if name.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Node Details did not expose the required node-name control")
    primary_name = intent["cluster_name"] + "-1"
    name.fill(primary_name)
    if name.input_value() != primary_name:
        raise NexusDashboardBrowserError("Nexus Dashboard did not retain the derived primary-node name")
    data = page.locator("[data-testid=dataIpv4]")
    gateway = page.locator("[data-testid=dataIpv4Gw]")
    if data.count() != 1 or gateway.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Node Details did not expose data IPv4 controls")
    data.fill(intent["data"]["address"])
    gateway.fill(intent["data"]["gateway"])
    if data.input_value() != intent["data"]["address"] or gateway.input_value() != intent["data"]["gateway"]:
        raise NexusDashboardBrowserError("Nexus Dashboard did not retain the declared data-network values")
    save = page.get_by_text("Save", exact=True)
    if save.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Node Details did not expose a unique Save action")
    save.click()
    page.locator(".loader.translucent").wait_for(state="detached", timeout=30000)
    expected = "IPv4 Address: " + intent["data"]["address"]
    page.get_by_text(expected, exact=True).wait_for(timeout=30000)
    next_button = page.get_by_role("button", name="Next")
    if next_button.count() != 1 or next_button.is_disabled():
        raise NexusDashboardBrowserError("Nexus Dashboard Node Details did not enable Next after saving data network")
    next_button.click()
    page.get_by_role("heading", name="Deployment Mode", exact=True).wait_for(timeout=30000)

def _deployment_mode(page, intent):
    """Enable only the declared platform service through its labeled card."""
    fabric_label = page.get_by_text("Fabric Controller", exact=True)
    fabric_label.wait_for(timeout=30000)
    if fabric_label.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Deployment Mode did not expose Fabric Controller")
    card = fabric_label.locator("xpath=ancestor::section[1]")
    choice = card.locator("input[type=checkbox]")
    if choice.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Fabric Controller card did not expose one selection control")
    if intent["fabric_controller"]["enabled"] and not choice.is_checked():
        choice.locator("xpath=..").click()
    if choice.is_checked() != intent["fabric_controller"]["enabled"]:
        raise NexusDashboardBrowserError("Nexus Dashboard did not retain the Fabric Controller selection")
    orchestrator = page.get_by_text("Orchestrator", exact=True).locator(
        "xpath=ancestor::section[1]").locator("input[type=checkbox]")
    if orchestrator.count() != 1 or orchestrator.is_checked():
        raise NexusDashboardBrowserError("Nexus Dashboard Deployment Mode did not preserve the unselected Orchestrator state")
    next_button = page.get_by_role("button", name="Next")
    if next_button.count() != 1 or next_button.is_disabled():
        raise NexusDashboardBrowserError("Nexus Dashboard Deployment Mode did not enable Next")
    next_button.click()
    page.get_by_role("heading", name="Summary", exact=True).wait_for(timeout=30000)

def _summary(page, intent):
    """Submit the verified documented summary and its deployment-mode warning."""
    summary_text = " ".join(page.locator("body").inner_text().split())
    for value in (intent["cluster_name"], intent["data"]["address"],
                  intent["data"]["gateway"], "Fabric Controller"):
        if value not in summary_text:
            raise NexusDashboardBrowserError("Nexus Dashboard Summary omitted a declared value")
    save = page.get_by_role("button", name="Save")
    if save.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard Summary did not expose Save")
    save.click()
    confirm = page.get_by_text("Continue", exact=True)
    if confirm.count() != 1:
        raise NexusDashboardBrowserError("Nexus Dashboard did not present the deployment-mode save confirmation")
    confirm.click()
    # Keep the documented UI session alive until its save request has time to leave the wizard.
    page.wait_for_timeout(30000)

_EXTERNAL_IPS_ENDPOINT = "/nexus/infra/api/platform/v1/externalips"
_EXTERNAL_IP_RESOURCES = (
    ("management-external-services", "Management"),
    ("data-external-services", "Data"),
)


def _external_ips_payloads(intent):
    """Build documented, separately targeted external-service IP resources."""
    pools = intent["service_ip_pools"]
    return [{"spec": {"name": name, "targetNetwork": target, "ip": pools[target]}}
            for name, target in _EXTERNAL_IP_RESOURCES if pools[target]]


def _external_ip_response(page, method, payload=None):
    """Use only the documented platform external-IP API in the authenticated UI session."""
    result = page.evaluate("""async ({method, endpoint, payload}) => {
        const options = {method};
        if (payload) {
            options.headers = {'Content-Type': 'application/json; charset=utf-8'};
            options.body = JSON.stringify(payload);
        }
        const response = await fetch(endpoint, options);
        return {status: response.status, body: await response.text()};
    }""", {"method": method, "endpoint": _EXTERNAL_IPS_ENDPOINT,
             "payload": payload})
    try:
        body = json.loads(result["body"])
    except (KeyError, TypeError, json.JSONDecodeError):
        body = None
    return result.get("status"), body


def _external_ip_specs(current):
    if not isinstance(current, dict) or not isinstance(current.get("items"), list):
        raise NexusDashboardBrowserError("Nexus Dashboard external-IP collection is unavailable")
    specs = []
    for item in current["items"]:
        spec = item.get("spec") if isinstance(item, dict) else None
        if isinstance(spec, dict):
            specs.append(spec)
    return specs


def _ensure_external_ips(page, intent):
    """Reconcile all declared service-IP pools without cross-resource collisions."""
    desired = _external_ips_payloads(intent)
    desired_ips = [address for item in desired for address in item["spec"]["ip"]]
    if len(desired_ips) != len(set(desired_ips)):
        raise NexusDashboardBrowserError("Nexus Dashboard desired service-IP pools overlap")
    status, current = _external_ip_response(page, "GET")
    if status != 200:
        raise NexusDashboardBrowserError("Nexus Dashboard external-IP collection is unavailable")
    specs = _external_ip_specs(current)
    matches = {}
    for item in desired:
        wanted = item["spec"]
        matching = [spec for spec in specs if spec.get("name") == wanted["name"]]
        if len(matching) > 1:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard has duplicate service-IP resource " + wanted["name"])
        for actual in specs:
            if actual.get("name") != wanted["name"] and set(actual.get("ip", [])) & set(wanted["ip"]):
                raise NexusDashboardBrowserError(
                    "Nexus Dashboard service-IP resource conflicts with " + wanted["name"])
        matches[wanted["name"]] = matching
    outcomes = {}
    for item in desired:
        wanted = item["spec"]
        matching = matches[wanted["name"]]
        if matching:
            actual = matching[0]
            if (actual.get("targetNetwork") != wanted["targetNetwork"]
                    or sorted(actual.get("ip", [])) != sorted(wanted["ip"])):
                raise NexusDashboardBrowserError(
                    "Nexus Dashboard service-IP resource conflicts with intent: " + wanted["name"])
            outcomes[wanted["targetNetwork"]] = "already-configured"
            continue
        status, _ = _external_ip_response(page, "POST", item)
        if status not in (200, 201):
            raise NexusDashboardBrowserError(
                "Nexus Dashboard rejected service-IP resource " + wanted["name"])
        specs.append(wanted)
        outcomes[wanted["targetNetwork"]] = "configured"
    status, verified = _external_ip_response(page, "GET")
    if status != 200:
        raise NexusDashboardBrowserError("Nexus Dashboard did not return service-IP resources")
    verified_specs = _external_ip_specs(verified)
    for item in desired:
        if item["spec"] not in verified_specs:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard did not retain service-IP resource " + item["spec"]["name"])
    return {"status": "already-configured" if all(value == "already-configured"
            for value in outcomes.values()) else "configured", "resources": outcomes}

def configure_external_ips(intent, username, password, timeout=600):
    """Reconcile all declared documented external service-IP pools after bringup."""
    address = str(IPv4Interface(intent["management"]["address"]).ip)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError as error:
        raise NexusDashboardBrowserError("Nexus Dashboard external-IP reconciliation requires Playwright") from error
    pin = _spki_pin(address)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True, args=["--ignore-certificate-errors-spki-list=" + pin])
            try:
                page = browser.new_page()
                page.goto("https://" + address + "/", wait_until="domcontentloaded", timeout=min(30000, timeout * 1000))
                _login(page, username, password, timeout)
                state = _state(page)
                if state != "ready-or-post-bringup":
                    return {"status": state, "resource": None}
                return _ensure_external_ips(page, intent)
            finally:
                browser.close()
    except PlaywrightTimeoutError as error:
        raise NexusDashboardBrowserError("Timed out reconciling documented Nexus Dashboard service IPs") from error

def _wait_for(page, predicate, deadline, description):
    """Bound a lifecycle wait without treating a pre-state API as a fault."""
    while time.monotonic() < deadline:
        if predicate():
            return
        page.wait_for_timeout(5000)
    raise NexusDashboardBrowserError("Timed out waiting for " + description)


def _launch_fabric_controller(page, deadline):
    """Follow the Dashboard's visible app launcher; never synthesize a private route."""
    launcher = page.locator("nd-launcher")
    _wait_for(page, lambda: launcher.count() == 1 and launcher.is_visible(), deadline,
              "Nexus Dashboard application launcher")
    # A fresh 3.2.1i login can display the optional ``Meet Nexus Dashboard``
    # tour. Escape does not reliably close this modal, and it intercepts the
    # documented launcher. Close only the positively identified tour rather
    # than forcing a click through an arbitrary overlay.
    welcome = page.locator("#modal-root .meet-nd-modal")
    if welcome.count() == 1 and welcome.is_visible():
        close = welcome.locator(".modal__close")
        if close.count() != 1:
            raise NexusDashboardBrowserError(
                "Nexus Dashboard welcome modal did not expose its close control")
        close.click()
        _wait_for(page, lambda: not welcome.is_visible(), deadline,
                  "Nexus Dashboard welcome modal dismissal")
    launcher.locator(".selected-item").click()
    item = launcher.locator(".dropdown-launcher .item").filter(has_text="Fabric Controller")
    _wait_for(page, lambda: item.count() == 1 and item.is_visible(), deadline,
              "Fabric Controller launcher item")
    item.click()


def _dismiss_fabric_controller_dialogs(page, deadline):
    """Dismiss first-run information and device-credential prompts."""
    modal = page.locator("#modal-root .modal.modeblocked")
    if modal.count() == 0:
        return
    for _ in range(4):
        prerequisites = page.locator(
            "#modal-root .welcome-modal", has_text="Fabric Controller")
        cancel = page.get_by_role("button", name="Cancel")
        if prerequisites.count() == 1 and prerequisites.is_visible():
            prerequisites.locator(".info-detail-screen-close").click()
        elif cancel.count() == 1 and cancel.is_visible() and (
                "Set credentials" in page.locator("body").inner_text()):
            # Device credentials are for onboarding, outside this baseline.
            cancel.click()
        else:
            break
        page.wait_for_timeout(1000)
    _wait_for(page, lambda: modal.count() == 0, deadline,
              "Fabric Controller first-run dialog dismissal")


def _fabric_controller_service_setup(page, deadline):
    """Perform the observed supported LAN/Advanced first-run UI only when present."""
    setup = page.locator(".gradient-card", has_text="Service Setup")
    admin = page.get_by_role("link", name="Admin", exact=True)
    # The Fabric Controller application can initially render a blank shell
    # while its UI bundle loads. Its documented first-run and post-setup
    # states are respectively Service Setup and Admin; wait for one rather
    # than treating the transient shell as an already-configured service.
    _wait_for(page, lambda: (
        (setup.count() == 1 and setup.is_visible())
        or (admin.count() == 1 and admin.is_visible())), deadline,
        "Fabric Controller first-run or configured UI")
    page.wait_for_timeout(1000)
    _dismiss_fabric_controller_dialogs(page, deadline)
    # The dashboard retains its Service Setup card after submission. The
    # completed two-step journey is the observed persisted setup indicator.
    journey_complete = "Getting Started Progress 100%" in page.locator("body").inner_text()
    if admin.count() == 1 and admin.is_visible() and (
            journey_complete or not (setup.count() == 1 and setup.is_visible())):
        return False
    setup.click()
    go = page.get_by_text("Go", exact=True)
    _wait_for(page, lambda: go.count() == 1 and go.is_visible(), deadline,
              "Fabric Controller Service Setup action")
    go.click()
    lan = page.locator(".CardWithIcon_cardWithIconContainer__OHIF7", has_text="LAN")
    _wait_for(page, lambda: lan.count() == 1 and lan.is_visible(), deadline,
              "Fabric Controller LAN selector")
    lan.click(force=True, no_wait_after=True)
    advanced = page.locator('input[value="Use-Case-Fabric-Management-Advanced"]')
    _wait_for(page, lambda: advanced.count() == 1 and advanced.is_visible(), deadline,
              "Fabric Management Advanced selector")
    if not advanced.is_checked():
        advanced.locator("xpath=..").click()
    if not advanced.is_checked():
        raise NexusDashboardBrowserError("Fabric Controller did not retain Fabric Management Advanced")
    next_button = page.get_by_role("button", name="Next")
    if next_button.count() != 1 or next_button.is_disabled():
        raise NexusDashboardBrowserError("Fabric Controller Feature Selection did not enable Next")
    next_button.click()
    _wait_for(page, lambda: page.get_by_role("button", name="Submit").count() == 1,
              deadline, "Fabric Controller Summary")
    summary = " ".join(page.locator("body").inner_text().split())
    for value in ("Operational Mode LAN", "Fabric Builder", "Endpoint Locator",
                  "Performance Monitoring"):
        if value not in summary:
            raise NexusDashboardBrowserError("Fabric Controller Summary omitted " + value)
    submit = page.get_by_role("button", name="Submit")
    submit.click(no_wait_after=True)
    _wait_for(page, lambda: submit.count() == 0 or submit.is_disabled(), deadline,
              "Fabric Controller Service Setup submission")
    return True

def _set_fabric_controller_connectivity(page, deadline, connectivity):
    """Reconcile LAN device-management connectivity through Server Settings."""
    admin = page.get_by_role("link", name="Admin", exact=True)
    _wait_for(page, lambda: admin.count() == 1 and admin.is_visible(), deadline,
              "Fabric Controller Admin UI")
    _dismiss_fabric_controller_dialogs(page, deadline)
    admin.click()
    system = page.get_by_role("link", name="System Settings", exact=True)
    _wait_for(page, lambda: system.count() == 1 and system.is_visible(), deadline,
              "Fabric Controller System Settings")
    system.click()
    category = page.locator("form").get_by_text("Admin", exact=True)
    _wait_for(page, lambda: category.count() == 1 and category.is_visible(), deadline,
              "Fabric Controller Server Settings Admin category")
    category.click()
    mode = page.locator('[id="serverProperties.global.oob_network_mode"]')
    _wait_for(page, lambda: mode.count() == 1 and mode.is_visible(), deadline,
              "LAN Device Management Connectivity")
    observed = mode.input_value().lower()
    if observed not in ("data", "management"):
        raise NexusDashboardBrowserError("Fabric Controller exposed an unexpected device-management value")
    if observed == connectivity:
        return "already-configured"
    mode.click()
    option = page.get_by_text(connectivity.title(), exact=True)
    _wait_for(page, lambda: option.count() == 1 and option.is_visible(), deadline,
              "LAN " + connectivity.upper() + " device-management option")
    option.click()
    if mode.input_value().lower() != connectivity:
        raise NexusDashboardBrowserError(
            "Fabric Controller did not retain " + connectivity.upper() +
            " device-management selection")
    save = page.get_by_role("button", name="Save")
    if save.count() != 1 or save.is_disabled():
        raise NexusDashboardBrowserError("Fabric Controller Server Settings did not enable Save")
    save.click(no_wait_after=True)
    _wait_for(page, lambda: "Saving server properties is in progress" not in
              page.locator("body").inner_text(), deadline,
              "Fabric Controller " + connectivity.upper() + " device-management save")
    if mode.input_value().lower() != connectivity:
        raise NexusDashboardBrowserError(
            "Fabric Controller did not persist " + connectivity.upper() + " device-management")
    return "configured"


def configure_fabric_controller(intent, username, password, timeout=1800):
    """Run the Fabric Controller setup and reconcile declared connectivity.

    The documented fabrics API is called only after the UI lifecycle has reached
    Server Settings and the desired selection has settled. No fabric is created.
    """
    if not intent["fabric_controller"]["enabled"]:
        return {"status": "disabled"}
    address = str(IPv4Interface(intent["management"]["address"]).ip)
    deadline = time.monotonic() + timeout
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError as error:
        raise NexusDashboardBrowserError("Fabric Controller setup requires Playwright") from error
    pin = _spki_pin(address)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True,
                args=["--ignore-certificate-errors-spki-list=" + pin])
            try:
                page = browser.new_page()
                page.goto("https://" + address + "/", wait_until="domcontentloaded",
                          timeout=min(30000, int((deadline - time.monotonic()) * 1000)))
                _login(page, username, password, max(1, deadline - time.monotonic()))
                page.goto("https://" + address + "/#/systemDashboard",
                          wait_until="domcontentloaded",
                          timeout=min(30000, max(1000, int((deadline - time.monotonic()) * 1000))))
                _launch_fabric_controller(page, deadline)
                submitted = _fabric_controller_service_setup(page, deadline)
                result = _set_fabric_controller_connectivity(
                    page, deadline, intent["fabric_controller"]["device_management_connectivity"])
                status, body = _external_ip_response(page, "GET")  # Dashboard API remains read-only here.
                if status != 200 or not isinstance(body, dict):
                    raise NexusDashboardBrowserError("Nexus Dashboard external-IP read validation is unavailable")
                fabrics = {}
                def fabrics_api_ready():
                    fabrics.update(page.evaluate("""async () => { const r = await fetch(
                        '/appcenter/cisco/ndfc/api/v1/lan-fabric/rest/control/fabrics');
                        return {status:r.status, body:await r.text()}; }"""))
                    return fabrics.get("status") == 200
                # The documented gateway can register after the UI has saved
                # desired selection. Poll the public endpoint rather than
                # treating its pre-registration response as a configuration fault.
                _wait_for(page, fabrics_api_ready, deadline,
                          "Fabric Controller documented fabrics API registration")
                if fabrics.get("status") != 200:
                    raise NexusDashboardBrowserError("Fabric Controller documented fabrics API is not ready after connectivity selection")
                try:
                    listing = json.loads(fabrics.get("body", ""))
                except json.JSONDecodeError as error:
                    raise NexusDashboardBrowserError("Fabric Controller fabrics API returned an invalid response") from error
                if not isinstance(listing, list) or listing:
                    raise NexusDashboardBrowserError("Fabric Controller baseline must contain no fabrics")
                return {"status": result, "service_setup_submitted": submitted,
                        "fabrics": 0}
            finally:
                browser.close()
    except PlaywrightTimeoutError as error:
        raise NexusDashboardBrowserError("Timed out in Fabric Controller lifecycle transition") from error


def bringup(intent, username, password, timeout=600):
    """Run or classify the documented initial Cluster Bringup wizard.

    It is safe to repeat: a completed wizard is classified and no settings are
    resubmitted. Subsequent wizard steps are handled only when their documented
    controls are positively identified.
    """
    if not 1 <= timeout <= 3600:
        raise ValueError("Nexus Dashboard browser timeout must be between 1 and 3600 seconds")
    if not isinstance(username, str) or not username:
        raise ValueError("CISCO_USERNAME must be set for Nexus Dashboard browser bringup")
    if not isinstance(password, str) or not password:
        raise ValueError("CISCO_PASSWORD must be set for Nexus Dashboard browser bringup")
    address = str(IPv4Interface(intent["management"]["address"]).ip)
    try:
        from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
    except ImportError as error:
        raise NexusDashboardBrowserError(
            "Nexus Dashboard Cluster Bringup requires the optional Playwright runtime") from error
    pin = _spki_pin(address)
    deadline = time.monotonic() + timeout
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=["--ignore-certificate-errors-spki-list=" + pin])
            try:
                page = browser.new_page()
                page.goto("https://" + address + "/", wait_until="domcontentloaded",
                          timeout=min(30000, max(1000, int((deadline - time.monotonic()) * 1000))))
                logged_in = _login(page, username, password, max(1, deadline - time.monotonic()))
                state = _state(page)
                if state == "awaiting-bringup":
                    _configuration(page, intent)
                    _node_details(page, intent)
                    _deployment_mode(page, intent)
                    _summary(page, intent)
                    return {"status": "initializing", "login": logged_in,
                            "stage": "summary-submitted"}
                return {"status": state, "login": logged_in, "stage": "classified"}
            finally:
                browser.close()
    except PlaywrightTimeoutError as error:
        raise NexusDashboardBrowserError(
            "Timed out waiting for the documented Nexus Dashboard Cluster Bringup UI") from error
