"""Reconcile Nexus Dashboard management routes through its documented settings UI."""

from ipaddress import ip_network

from .nexus_dashboard_browser import NexusDashboardBrowserError, _wait_for


def declared_management_routes(intent):
    """Return canonical, duplicate-free management destinations from ND intent."""
    values = intent["nexus_dashboard"].get("management_network_routes", [])
    if not isinstance(values, list):
        raise ValueError("management_network_routes must be a list")
    routes = []
    for value in values:
        route = str(ip_network(value, strict=True))
        if route not in routes:
            routes.append(route)
    return routes


def ensure_management_routes(page, intent, deadline):
    """Add missing ND management routes and verify them in the Routes tile."""
    routes = declared_management_routes(intent)
    if not routes:
        return {"status": "already-configured", "routes": []}
    welcome = page.locator("#modal-root .meet-nd-modal")
    if welcome.count() == 1 and welcome.is_visible():
        close = welcome.locator(".modal__close")
        if close.count() != 1:
            raise NexusDashboardBrowserError("ND tour has no close control")
        close.click()
        _wait_for(page, lambda: not welcome.is_visible(), deadline,
                  "Nexus Dashboard tour dismissal")
    page.get_by_role("link", name="Admin", exact=True).click()
    page.get_by_role("link", name="System Settings", exact=True).click()
    card = page.locator("section.card").filter(
        has=page.get_by_role("heading", name="Routes", exact=True))
    _wait_for(page, lambda: card.count() == 1, deadline, "ND Routes tile")
    _wait_for(page, lambda: "Loading..." not in card.inner_text(), deadline,
              "ND Routes tile data")
    missing = [route for route in routes
               if card.get_by_text(route, exact=True).count() == 0]
    if not missing:
        return {"status": "already-configured", "routes": routes}
    card.get_by_text("Edit", exact=True).click()
    add = page.get_by_text("Add Management Network Routes", exact=True)
    for route in missing:
        add.click()
        row = page.locator(".add-edit-table-container").filter(
            has_text="Management Network Routes")
        input_field = row.locator("input").last
        if input_field.count() != 1:
            raise NexusDashboardBrowserError("Management route input is unavailable")
        input_field.fill(route)
        confirm = row.locator(".xicon-checked-circle-white")
        if confirm.count() != 1:
            raise NexusDashboardBrowserError("Management route confirmation is unavailable")
        confirm.click()
    save = page.get_by_role("button", name="Save", exact=True)
    if not save.is_enabled():
        raise NexusDashboardBrowserError("ND management route Save is disabled")
    save.click()
    _wait_for(page, lambda: all(
        card.get_by_text(route, exact=True).count() == 1 for route in routes),
        deadline, "ND management route readback")
    return {"status": "updated", "routes": routes}
