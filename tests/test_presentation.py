import copy
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from eve_lab.presentation import compiled_objects, reconcile_presentation, validate_presentation
from eve_lab.topology import load_topology


class FakeTextObjects:
    def __init__(self):
        self.objects = {}
        self.writes = []

    def request(self, method, path, payload=None):
        self.writes.append((method, path, copy.deepcopy(payload)))
        base = "labs/test.unl/textobjects"
        if path == base and method == "GET":
            return copy.deepcopy(self.objects) if self.objects else []
        if path == base and method == "POST":
            ident = str(max([int(value) for value in self.objects] or [0]) + 1)
            self.objects[ident] = {"id": int(ident), **payload}
            return None
        if path.startswith(base + "/"):
            ident = path.rsplit("/", 1)[1]
            if method == "PUT":
                self.objects[ident].update(payload)
                return None
            if method == "DELETE":
                del self.objects[ident]
                return None
        raise AssertionError((method, path, payload))


class PresentationTests(unittest.TestCase):
    def document(self):
        return {
            "version": 1,
            "regions": [{
                "name": "site-1", "left": 10, "top": 20,
                "width": 300, "height": 200, "stroke": "#112233",
                "fill": "#abcdef", "fill_opacity": 0.2,
                "stroke_width": 2, "radius": 12,
            }],
            "labels": [{
                "name": "site-1-label", "left": 30, "top": 40,
                "text": "Site <1>\n10.1.0.0/24", "font_size": 18,
                "color": "#ffffff", "background": "#445566",
            }],
        }

    def test_compile_validates_and_escapes(self):

        document = self.document()
        objects = compiled_objects(document, {"site-1": "4", "site-1-label": "5"})
        self.assertEqual([item["type"] for item in objects], ["square", "text"])
        import base64
        label = base64.b64decode(objects[1]["data"]).decode()
        self.assertIn("Site &lt;1&gt;<br>10.1.0.0/24", label)
        document["labels"][0]["color"] = "red"
        with self.assertRaisesRegex(ValueError, "#RRGGBB"):
            validate_presentation(document)

    def test_optional_style_fields_use_defaults(self):
        document = {
            "version": 1,
            "regions": [{
                "name": "site", "left": 0, "top": 0,
                "width": 100, "height": 100,
            }],
            "labels": [{
                "name": "label", "left": 0, "top": 0, "text": "Site",
            }],
        }
        objects = compiled_objects(document)
        self.assertEqual([item["type"] for item in objects], ["square", "text"])

    def test_reconcile_create_repeat_update_and_prune(self):
        client = FakeTextObjects()
        changes = []
        result = reconcile_presentation(client, "labs/test.unl", self.document(), changes)
        self.assertEqual(result, {"declared": 2, "matched": 2})
        self.assertEqual(len(client.objects), 2)
        client.writes.clear()
        changes.clear()
        reconcile_presentation(client, "labs/test.unl", self.document(), changes)
        self.assertEqual(changes, [])
        self.assertEqual(client.writes, [
            ("GET", "labs/test.unl/textobjects", None),
            ("GET", "labs/test.unl/textobjects", None),
            ("GET", "labs/test.unl/textobjects", None),
        ])
        changed = self.document()
        changed["labels"] = []
        changed["regions"][0]["width"] = 320
        changes.clear()
        reconcile_presentation(client, "labs/test.unl", changed, changes)
        self.assertEqual(set(changes), {
            "pruned presentation object: site-1-label",
            "updated presentation object: site-1",
        })
        self.assertEqual(len(client.objects), 1)

    def test_topology_loader_keeps_presentation_separate(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            lab = root / "labs" / "test"
            lab.mkdir(parents=True)
            (lab / "topology.yaml").write_text(
                "name: test\nnodes: []\nnetworks: []\nlinks: []\n")
            (lab / "presentation.yaml").write_text(
                "version: 1\nregions: []\nlabels: []\n")
            loaded = load_topology(root, "test")
            self.assertEqual(loaded["presentation"], {
                "version": 1, "regions": [], "labels": []})


if __name__ == "__main__":
    unittest.main()
