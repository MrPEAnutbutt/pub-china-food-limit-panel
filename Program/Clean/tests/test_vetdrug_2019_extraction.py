import importlib.util
import sys
import unittest
from pathlib import Path


CLEAN_DIR = Path(__file__).resolve().parents[1]
if str(CLEAN_DIR) not in sys.path:
    sys.path.insert(0, str(CLEAN_DIR))
SPEC = importlib.util.spec_from_file_location(
    "rebuild_vetdrug_2019", CLEAN_DIR / "260716_rebuild_vetdrug.py"
)
VETDRUG = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(VETDRUG)

# Layout text shaped like GB 31650-2019 tables 60 and 63: one label wraps
# inside its cell, the other across a page break.
LAYOUT = """\
4.1.1 阿苯达唑（Albendazole）
        动物种类                       靶组织    残留限量 μg/kg
牛                                      肌肉       100
羊                                      肌肉       200
4.1.60 卡那霉素（Kanamycin）
        动物种类                       靶组织    残留限量 μg/kg
所有食品动物（产蛋期禁用，不                      肌肉       100
       包括鱼）                        皮＋脂       100
                                    肝        600
4.1.63 左旋咪唑（Levamisole）
        动物种类                       靶组织    残留限量 μg/kg
 牛/羊/猪/家禽（泌乳期禁用、产                   肌肉        10

                                                         23
                                                   GB31650-2019
       蛋期禁用）                       脂肪             10
                                   肝             100
4.1.64 林可霉素（Lincomycin）
"""


class WrappedAnimalLabelTest(unittest.TestCase):
    def setUp(self):
        self.original = VETDRUG.pdftotext_layout
        VETDRUG.pdftotext_layout = lambda path, executable: LAYOUT

    def tearDown(self):
        VETDRUG.pdftotext_layout = self.original

    def animals(self):
        rows, quarantine = VETDRUG.extract_2019(Path("unused.pdf"), pdftotext="pdftotext")
        self.assertEqual(quarantine, [])
        return [(row[1], row[3], row[5]) for row in rows]

    def test_wrapped_label_is_joined_for_every_tissue(self):
        rows = self.animals()
        self.assertEqual(
            [r for r in rows if r[0] == "卡那霉素"],
            [("卡那霉素", "所有食品动物（产蛋期禁用，不包括鱼）", tissue)
             for tissue in ("肌肉", "皮＋脂", "肝")],
        )
        self.assertEqual(
            [r for r in rows if r[0] == "左旋咪唑"],
            [("左旋咪唑", "牛/羊/猪/家禽（泌乳期禁用、产蛋期禁用）", tissue)
             for tissue in ("肌肉", "脂肪", "肝")],
        )

    def test_closed_label_is_not_extended_by_the_next_animal(self):
        rows = self.animals()
        self.assertEqual(
            [r for r in rows if r[0] == "阿苯达唑"],
            [("阿苯达唑", "牛", "肌肉"), ("阿苯达唑", "羊", "肌肉")],
        )


if __name__ == "__main__":
    unittest.main()
