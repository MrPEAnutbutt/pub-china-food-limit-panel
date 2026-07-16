import importlib.util
import unittest
from pathlib import Path


UTILS_PATH = Path(__file__).resolve().parents[1] / "release_panel_utils.py"
SPEC = importlib.util.spec_from_file_location("release_entity_ids", UTILS_PATH)
UTILS = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(UTILS)


class ReleaseEntityIdTests(unittest.TestCase):
    def test_pesticide_id_ignores_spacing_and_unicode_typography(self):
        first = UTILS.pesticide_entity_id("2,4-D and 2,4-D Na", "")
        second = UTILS.pesticide_entity_id("２，４－Ｄand２，４－Ｄ Na", "不同中文")

        self.assertEqual(first, second)
        self.assertRegex(first, r"^PST-[0-9a-f]{16}$")

    def test_pesticide_id_retains_chemical_form(self):
        acid = UTILS.pesticide_entity_id("glyphosate", "草甘膦")
        salt = UTILS.pesticide_entity_id(
            "glyphosate ammonium salt", "草甘膦铵盐"
        )

        self.assertNotEqual(acid, salt)

    def test_pesticide_id_has_explicit_chinese_fallback(self):
        first = UTILS.pesticide_entity_id("", "百菌清")
        second = UTILS.pesticide_entity_id("", " 百 菌 清 ")

        self.assertEqual(first, second)

    def test_food_scope_variants_share_a_base_identifier(self):
        values = {
            UTILS.food_entity_id("柑橘类水果"),
            UTILS.food_entity_id("柑橘类水果（柑、橘、橙除外）"),
            UTILS.food_entity_id("柑橘类水果(仅限鲜果)"),
        }

        self.assertEqual(len(values), 1)
        self.assertRegex(values.pop(), r"^FOD-[0-9a-f]{16}$")

    def test_food_qualifiers_remain_distinct_in_scope_signature(self):
        unqualified = {"food_raw": "柑橘类水果"}
        excluded = {"food_raw": "柑橘类水果(柠檬除外)"}

        self.assertEqual(
            UTILS.food_entity_id(unqualified["food_raw"]),
            UTILS.food_entity_id(excluded["food_raw"]),
        )
        self.assertNotEqual(
            UTILS._pesticide_v2_scope_signature(unqualified),
            UTILS._pesticide_v2_scope_signature(excluded),
        )

    def test_empty_and_unknown_entities_fail(self):
        with self.assertRaisesRegex(ValueError, "pesticide entity"):
            UTILS.pesticide_entity_id("", "")
        with self.assertRaisesRegex(ValueError, "food entity"):
            UTILS.food_entity_id("")
        with self.assertRaisesRegex(ValueError, "unsupported entity type"):
            UTILS._stable_entity_id("unknown", "key")


if __name__ == "__main__":
    unittest.main()
