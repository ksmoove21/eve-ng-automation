"""Compile and reconcile declarative EVE canvas presentation objects."""

import base64
from html import escape
import re


_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
_REGION_FIELDS = {
    "name", "left", "top", "width", "height", "stroke", "fill",
    "fill_opacity", "stroke_width", "radius", "dash",
}
_LABEL_FIELDS = {
    "name", "left", "top", "text", "font_size", "color", "background",
    "align",
}


def _integer(item, field, minimum=0, default=None):
    value = item.get(field, default)
    if type(value) is not int or value < minimum:
        raise ValueError(f"presentation {item.get('name', '<unnamed>')}: {field} must be an integer >= {minimum}")
    return value


def _color(item, field, default):
    value = item.get(field, default)
    if not isinstance(value, str) or not _COLOR.fullmatch(value):
        raise ValueError(f"presentation {item.get('name', '<unnamed>')}: {field} must be #RRGGBB")
    return value.lower()


def validate_presentation(document, network_names=None):
    if document is None:
        return
    if not isinstance(document, dict) or set(document) - {"version", "regions", "labels", "hidden_networks"}:
        raise ValueError("presentation.yaml supports only version, regions, labels, and hidden_networks")
    if document.get("version") != 1:
        raise ValueError("presentation.yaml version must be 1")
    hidden = document.get("hidden_networks", [])
    if not isinstance(hidden, list) or any(
        not isinstance(name, str) or not name.strip() for name in hidden
    ) or len(hidden) != len(set(hidden)):
        raise ValueError("presentation hidden_networks must be unique nonempty network names")
    if network_names is not None:
        unknown = sorted(set(hidden) - set(network_names))
        if unknown:
            raise ValueError(f"presentation hidden_networks reference undeclared networks: {unknown}")
    names = set()
    for kind, allowed in (("regions", _REGION_FIELDS), ("labels", _LABEL_FIELDS)):
        items = document.get(kind, [])
        if not isinstance(items, list):
            raise ValueError(f"presentation {kind} must be a list")
        for item in items:
            if not isinstance(item, dict) or set(item) - allowed:
                raise ValueError(f"Invalid presentation {kind[:-1]}: {item}")
            name = item.get("name")
            if not isinstance(name, str) or not name.strip() or name in names:
                raise ValueError("presentation object names must be unique nonempty strings")
            names.add(name)
            _integer(item, "left")
            _integer(item, "top")
            if kind == "regions":
                _integer(item, "width", 2)
                _integer(item, "height", 2)
                _integer(item, "stroke_width", 1, 2)
                _integer(item, "radius", 0, 0)
                _color(item, "stroke", "#777777")
                _color(item, "fill", "#ffffff")
                opacity = item.get("fill_opacity", 0.15)
                if type(opacity) not in (int, float) or not 0 <= opacity <= 1:
                    raise ValueError(f"presentation {name}: fill_opacity must be between 0 and 1")
                dash = item.get("dash", "")
                if not isinstance(dash, str) or not re.fullmatch(r"[0-9, ]*", dash):
                    raise ValueError(f"presentation {name}: dash must contain only integers, commas, and spaces")
            else:
                if not isinstance(item.get("text"), str) or not item["text"].strip():
                    raise ValueError(f"presentation {name}: text must be a nonempty string")
                _integer(item, "font_size", 1, 16)
                _color(item, "color", "#222222")
                _color(item, "background", "#ffffff")
                if item.get("align", "center") not in ("left", "center", "right"):
                    raise ValueError(f"presentation {name}: align must be left, center, or right")


def _encode(value):
    return base64.b64encode(value.encode("utf-8")).decode("ascii")


def _region(item, ident):
    width, height = item["width"], item["height"]
    stroke = _color(item, "stroke", "#777777")
    fill = _color(item, "fill", "#ffffff")
    opacity = item.get("fill_opacity", 0.15)
    dash = item.get("dash", "")
    dash_attribute = f' stroke-dasharray="{dash}"' if dash else ""
    value = (
        f'<div id="customShape{ident}" class="customShape context-menu jtk-managed '
        f'jtk-draggable ui-selectee ui-resizable" data-path="{ident}" '
        f'style="display:inline;z-index:900;position:absolute;left:{item["left"]}px;'
        f'top:{item["top"]}px;width:{width}px;height:{height}px;" name="{escape(item["name"], quote=True)}">'
        f'<svg width="{width}" height="{height}"><rect x="1" y="1" rx="{item.get("radius", 0)}" '
        f'ry="{item.get("radius", 0)}" width="{width - 2}" height="{height - 2}" '
        f'fill="{fill}" fill-opacity="{opacity}" stroke-width="{item.get("stroke_width", 2)}" '
        f'stroke="{stroke}"{dash_attribute}></rect></svg></div>'
    )
    return {"name": item["name"], "type": "square", "data": _encode(value)}


def _label(item, ident):
    text = "<br>".join(escape(part) for part in item["text"].splitlines())
    value = (
        f'<div id="customText{ident}" class="customShape customText context-menu jtk-managed '
        f'jtk-draggable editable" data-path="{ident}" style="position:absolute;left:{item["left"]}px;'
        f'top:{item["top"]}px;z-index:1001;height:auto;width:auto;" contenteditable="true">'
        f'<p style="text-align:{item.get("align", "center")};"><span style="color:{_color(item, "color", "#222222")};'
        f'font-size:{item.get("font_size", 16)}px;background-color:{_color(item, "background", "#ffffff")};">'
        f'<strong>{text}</strong></span></p></div>'
    )
    return {"name": item["name"], "type": "text", "data": _encode(value)}


def compiled_objects(document, identifiers=None):
    validate_presentation(document)
    identifiers = identifiers or {}
    objects = []
    for kind, builder in (("regions", _region), ("labels", _label)):
        for item in document.get(kind, []):
            objects.append(builder(item, str(identifiers.get(item["name"], 0))))
    return objects


def _indexed(data):
    if isinstance(data, dict):
        return {str(key): value for key, value in data.items()}
    if isinstance(data, list):
        return {str(value.get("id", index)): value for index, value in enumerate(data)}
    raise RuntimeError("Expected an EVE textobject collection")


def reconcile_presentation(client, path, document, changes):
    if document is None:
        return {"declared": 0, "matched": 0}
    validate_presentation(document)
    endpoint = path + "/textobjects"
    current = _indexed(client.request("GET", endpoint))
    by_name = {}
    for ident, item in current.items():
        name = item.get("name")
        if name in by_name:
            raise RuntimeError(f"Duplicate remote presentation object: {name}")
        by_name[name] = {**item, "id": ident}
    desired_names = {item["name"] for item in document.get("regions", []) + document.get("labels", [])}
    for name, item in list(by_name.items()):
        if name not in desired_names:
            client.request("DELETE", endpoint + "/" + item["id"])
            changes.append(f"pruned presentation object: {name}")
    current = _indexed(client.request("GET", endpoint))
    identifiers = {item.get("name"): ident for ident, item in current.items()}
    next_ident = max([int(ident) for ident in current if ident.isdigit()] or [0]) + 1
    for desired in compiled_objects(document, identifiers):
        existing = next((({**item, "id": ident}) for ident, item in current.items()
                         if item.get("name") == desired["name"]), None)
        if existing is None:
            provisional = compiled_objects(document, {**identifiers, desired["name"]: str(next_ident)})
            payload = next(item for item in provisional if item["name"] == desired["name"])
            client.request("POST", endpoint, payload)
            changes.append(f"created presentation object: {desired['name']}")
            current = _indexed(client.request("GET", endpoint))
            matches = [(ident, item) for ident, item in current.items() if item.get("name") == desired["name"]]
            if len(matches) != 1:
                raise RuntimeError(f"EVE did not create one presentation object named {desired['name']}")
            ident, existing = matches[0]
            identifiers[desired["name"]] = ident
            next_ident = max(next_ident + 1, int(ident) + 1 if ident.isdigit() else next_ident + 1)
        else:
            ident = existing["id"]
            identifiers[desired["name"]] = ident
        expected = next(item for item in compiled_objects(document, identifiers)
                        if item["name"] == desired["name"])
        live = current[str(ident)]
        if any(live.get(field) != expected[field] for field in ("name", "type", "data")):
            client.request("PUT", endpoint + "/" + str(ident), expected)
            changes.append(f"updated presentation object: {desired['name']}")
    final = _indexed(client.request("GET", endpoint))
    final_names = {item.get("name") for item in final.values()}
    if final_names != desired_names:
        raise RuntimeError(f"Presentation read-back mismatch: expected {sorted(desired_names)}, observed {sorted(final_names)}")
    return {"declared": len(desired_names), "matched": len(final_names)}
