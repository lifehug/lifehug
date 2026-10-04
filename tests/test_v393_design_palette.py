"""v393: the viewer adopts the design palette (lifehug#461, twin of lifehug-platform#996)."""

import hashlib
import json
import logging
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "system"))
sys.path.insert(0, str(ROOT / "tests"))

import serve_wiki
import test_wiki_views as twv
from design import palette

# The mirror rule: system/design/palette.yaml is byte-identical to
# lifehug-platform's architecture/design/palette.yaml. Recorded here AND in
# docs/design/palette.md; the platform pins the same digest on its side.
PALETTE_DIGEST = "da772bb6fa9a29fe85c910fa7c688c726547c83aedec97d43d405f4ea2b4227e"
GRAPH_TYPES = ["person", "place", "period", "object", "theme", "project", "event", "self", "lifes_work"]
# What TYPE_COLORS hard-coded before v393.
OLD_TYPE_HEXES = ["#7c4f1d", "#9a6b3f", "#5a7d9a", "#3f8f6a", "#8a7a3f", "#6b5d49",
                  "#9a5a7a", "#3f6f8f", "#8f6f3f", "#8a7a63", "#d8cdb8"]


def _graph_page() -> str:
    return serve_wiki.layout("Graph", serve_wiki._GRAPH_HTML, wide=True).decode("utf-8")


class PaletteFileTests(unittest.TestCase):
    def test_digest_is_pinned_here_and_in_the_doc(self):
        raw = (ROOT / "system/design/palette.yaml").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), PALETTE_DIGEST)
        self.assertEqual(palette.content_digest(), PALETTE_DIGEST)
        doc = (ROOT / "docs/design/palette.md").read_text(encoding="utf-8")
        self.assertIn(PALETTE_DIGEST, doc)
        self.assertIn("lifehug-platform", doc)

    def test_yaml_parses_and_the_stdlib_reader_agrees_with_pyyaml(self):
        data = palette.load()
        self.assertEqual(data["categorical"]["order"], GRAPH_TYPES)
        self.assertEqual(len(data["categorical"]["entries"]), 9)
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML not installed; the stdlib reader is the only reader")
        self.assertEqual(data, yaml.safe_load((ROOT / "system/design/palette.yaml").read_text()))

    def test_the_palette_ships_with_the_framework(self):
        files = json.loads((ROOT / "system/version.json").read_text())["framework_files"]
        for f in ("system/design/palette.yaml", "system/design/palette.py", "docs/design/palette.md"):
            self.assertIn(f, files)
            self.assertTrue((ROOT / f).exists())

    def test_every_graph_type_maps_to_its_own_token(self):
        tokens = [palette.type_color(t) for t in GRAPH_TYPES]
        self.assertEqual(len(set(tokens)), 9)
        for t, tok in zip(GRAPH_TYPES, tokens):
            self.assertTrue(tok.startswith("--graph-"), (t, tok))
        # The viewer's plural directory names and the hub resolve to the same tokens.
        self.assertEqual(palette.type_color("people"), "--graph-person")
        self.assertEqual(palette.type_color("life"), palette.type_color("self"))
        self.assertEqual(palette.type_color("relationships"), "--graph-relationship")
        for d in ("people", "places", "periods", "objects", "themes", "projects", "self", "lifes_work", "life"):
            self.assertNotEqual(palette.type_color(d), palette.fallback_token(), d)

    def test_unknown_type_is_the_fallback_and_warns(self):
        with self.assertLogs(palette.log, level=logging.WARNING) as cm:
            self.assertEqual(palette.type_color("zebra"), "--graph-fallback")
        self.assertIn("zebra", cm.output[0])

    def test_generated_css_has_light_and_dark_blocks(self):
        css = palette.css()
        self.assertIn(":root{", css)
        self.assertIn("@media (prefers-color-scheme: dark){:root{", css)
        light, dark = css.split("@media (prefers-color-scheme: dark)")
        for e in palette.load()["categorical"]["entries"]:
            self.assertIn(f"{e['token']}:{e['light']};", light)
            self.assertIn(f"{e['token']}:{e['dark']};", dark)
        for tok in ("--graph-fallback", "--graph-relationship", "--graph-link", "--lh-surface", "--lh-ink"):
            self.assertIn(tok + ":", light)
            self.assertIn(tok + ":", dark)

    def test_legend_follows_the_fixed_order_not_the_data_order(self):
        rows = palette.legend(["themes", "people", "themes", "places"])
        self.assertEqual([r["type"] for r in rows], ["person", "place", "theme"])


class ViewerGraphTests(unittest.TestCase):
    setUp = twv.WikiViewsTests.setUp
    tearDown = twv.WikiViewsTests.tearDown
    _write = twv.WikiViewsTests._write
    _populate = twv.WikiViewsTests._populate

    def test_graph_data_names_a_token_per_node_and_a_legend(self):
        self._populate()
        with mock.patch.object(serve_wiki, "load_config",
                               return_value={"name": "Me", "full_name": "My Life"}):
            g = serve_wiki.graph_data()
        for n in g["nodes"]:
            self.assertEqual(n["token"], palette.type_color(n["type"]))
            self.assertNotIn("#", n["token"])
        self.assertEqual({r["token"] for r in g["legend"]}, {n["token"] for n in g["nodes"]})
        self.assertEqual(g["edge_tokens"], {"relationship": "--graph-relationship", "link": "--graph-link"})

    def test_the_page_carries_the_generated_properties_not_hard_coded_type_hexes(self):
        page = _graph_page()
        self.assertIn(palette.css(), page)
        body = serve_wiki._GRAPH_HTML
        self.assertNotIn("TYPE_COLORS", body)
        for hexv in OLD_TYPE_HEXES:
            self.assertNotIn(hexv, body)
        # No palette hex (any entry, any mode) is spelled in the graph markup/script.
        for row in palette._tokened():
            self.assertNotIn(row["light"], body)
            self.assertNotIn(row["dark"], body)
        self.assertIn("tok(n.token)", body)
        self.assertNotIn("#fff'", body)

    def test_dark_values_reach_the_canvas_and_the_list(self):
        page = _graph_page()
        self.assertRegex(page, r"#graph \{[^}]*background: var\(--lh-surface\)")
        self.assertRegex(page, r"\.graph-list a \{[^}]*color: var\(--lh-ink\)")
        self.assertNotIn("#fffdf9; touch-action", page)
        self.assertIn("prefers-color-scheme: dark", page)

    def test_selection_is_a_ring_never_a_box(self):
        body = serve_wiki._GRAPH_HTML
        page = _graph_page()
        self.assertNotIn("'rect'", body)
        self.assertNotIn("<rect", body)
        self.assertNotRegex(body, r"outline")
        self.assertIn("#graph, #graph g { outline: none; }", page)
        # 2px at radius+4 for the selection, 1px at radius+3 for a neighbour.
        self.assertIn("n.outer + (isSel ? 4 : 3)", body)
        self.assertIn("isSel ? 2 : 1", body)
        self.assertIn("style: 'stroke:' + n.fill", body)
        # Keyboard focus draws the same ring.
        self.assertIn("g:focus-visible .focus-ring { opacity: 1; }", page)
        self.assertIn("tabindex: 0", body)
        self.assertIn("ev.key === 'Enter'", body)

    def test_legend_swatches_wear_the_same_tokens(self):
        body = serve_wiki._GRAPH_HTML
        self.assertIn('id="graph-types"', body)
        self.assertIn("sw.style.background = tok(row.token)", body)

    def test_controls_carry_the_shared_class_set_in_the_corner(self):
        body = serve_wiki._GRAPH_HTML
        page = _graph_page()
        corner = re.search(r'<div class="cornerControls".*?</div>', body, re.DOTALL).group(0)
        for ident in ("graph-fit", "graph-reset", "graph-full"):
            self.assertRegex(corner, rf'class="control graphControl" id="{ident}"')
        self.assertIn(".cornerControls { position: absolute; top: 0.45rem; right: 0.55rem;", page)
        self.assertIn("min-width: 2.75rem; min-height: 2.75rem", page)  # 44px targets
        self.assertIn("border: 1px solid var(--lh-rule); background: transparent; color: inherit;", page)
        self.assertIn("controls.module.css", page)  # the twin is named in a comment
        self.assertNotIn("zoomButton", page)


if __name__ == "__main__":
    unittest.main()
