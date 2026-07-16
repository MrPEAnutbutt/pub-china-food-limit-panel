import importlib.util
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "260715_extract_additive_raw.py"
SPEC = importlib.util.spec_from_file_location("extract_additive_raw", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


class AdditiveNameRecoveryTests(unittest.TestCase):
    def test_trailing_footnote_does_not_absorb_previous_table_rows(self):
        recent = [
            "1 6. 0 1 果冻 0. 1",
            "使用量",
            "阿斯巴甜( 又名天门冬酰苯丙氨酸甲酯) 3)",
            "a s p a r t a m e",
        ]

        self.assertEqual(MODULE.name_from(recent), "阿斯巴甜")

    def test_second_footnoted_name_is_recovered(self):
        recent = [
            "1 5. 0 2 配制酒 0. 3 5",
            "1 6. 0 1 果冻 0. 3",
            "使用量",
            "氨基乙酸( 又名甘氨酸) 5)",
            "g l y c i n e",
        ]

        self.assertEqual(MODULE.name_from(recent), "氨基乙酸")

    def test_multiline_chemical_name_is_not_reduced_to_its_last_fragment(self):
        recent = [
            "1 6. 0 6 膨化食品 0. 2 以油脂中的含量计",
            "N -[ N - ( 3, 3 - 二甲基丁基) ] - L - α - 天门冬氨 - L - 苯丙氨",
            "酸1 - 甲酯( 又名纽甜)",
            "n e o t a m e",
        ]

        self.assertEqual(
            MODULE.name_from(recent),
            "N-[N-(3,3-二甲基丁基)]-L-α-天门冬氨-L-苯丙氨酸1-甲酯",
        )

    def test_ascii_stereochemical_prefix_is_retained(self):
        recent = [
            "表 A. 1( 续)",
            "L( +) - 酒石酸, d l - 酒石酸 L( +) - t a r t a r i ca c i d",
        ]

        self.assertEqual(MODULE.name_from(recent), "L(+)-酒石酸,dl-酒石酸")

    def test_grouped_sulfites_are_recovered_across_translation_lines(self):
        recent = [
            "以每千克黄豆的使用量计",
            "二氧化硫，焦亚硫酸钾，焦亚硫酸钠， sulfurdioxide",
            "sodiummetabisulphite, sodiumsulfite, sodium",
            "亚硫酸钠，亚硫酸氢钠，低亚硫酸钠 hydrogensulfite",
        ]

        self.assertEqual(
            MODULE.name_from(recent),
            "二氧化硫，焦亚硫酸钾，焦亚硫酸钠，亚硫酸钠，亚硫酸氢钠，低亚硫酸钠",
        )

    def test_each_alias_is_removed_without_dropping_later_group_members(self):
        recent = [
            "山梨醇酐单月桂酸酯（又名司盘20），山梨醇",
            "酐单棕榈酸酯（又名司盘40），山梨醇酐单硬",
            "脂酸酯（又名司盘60），山梨醇酐三硬脂酸酯",
            "（又名司盘65），山梨醇酐单油酸酯（又名司",
            "盘80）",
            "Sorbitanmonolaurate, sorbitanmonopalmitate",
        ]

        self.assertEqual(
            MODULE.name_from(recent),
            "山梨醇酐单月桂酸酯，山梨醇酐单棕榈酸酯，山梨醇酐单硬脂酸酯，"
            "山梨醇酐三硬脂酸酯，山梨醇酐单油酸酯",
        )

    def test_nested_chemical_alias_is_removed_as_one_parenthetical(self):
        recent = [
            "阿力甜( 又名 L - α - 天冬氨酰 - N - ( 2, 2, 4, 4 -",
            "四甲基 - 3 - 硫化三亚甲基) - D - 丙氨酰胺)",
            "alitame",
        ]

        self.assertEqual(MODULE.name_from(recent), "阿力甜")

    def test_ascii_alias_and_translation_are_both_excluded(self):
        self.assertEqual(
            MODULE.name_from(
                ["丁基羟基茴香醚(简称“BHA”) butylated hydroxyanisole"]
            ),
            "丁基羟基茴香醚",
        )

    def test_interleaved_group_translations_are_excluded_line_by_line(self):
        recent = [
            "聚氧乙烯山梨醇酐单月桂酸酯(又名吐温20)， polyoxyethylene sorbitan monolaurate,",
            "聚氧乙烯山梨醇酐单棕榈酸酯(又名吐温40) polyoxyethylene sorbitan monopalmitate",
        ]

        self.assertEqual(
            MODULE.name_from(recent),
            "聚氧乙烯山梨醇酐单月桂酸酯，聚氧乙烯山梨醇酐单棕榈酸酯",
        )

    def test_internal_english_translation_is_removed_from_grouped_name(self):
        recent = [
            "单，双甘油脂肪酸酯(油酸、亚油酸、 mono-and diglycerides of fatty acids",
            "亚麻酸、棕榈酸、山嵛酸、硬脂酸、月桂酸)",
        ]

        self.assertEqual(
            MODULE.name_from(recent),
            "单，双甘油脂肪酸酯(油酸、亚油酸、亚麻酸、棕榈酸、山嵛酸、硬脂酸、月桂酸)",
        )

    def test_trailing_translation_prefix_is_not_part_of_chinese_name(self):
        self.assertEqual(
            MODULE.name_from(["β-阿朴-8'-胡萝卜素醛 β-apo-8'-carotenal"]),
            "β-阿朴-8'-胡萝卜素醛",
        )

    def test_numeric_english_translation_prefix_is_not_repeated(self):
        self.assertEqual(MODULE.name_from(["4-苯基苯酚 4-phenylphenol"]), "4-苯基苯酚")
        self.assertEqual(
            MODULE.name_from(["2,4-二氯苯氧乙酸 2,4-dichlorophenoxy acetic acid"]),
            "2,4-二氯苯氧乙酸",
        )

    def test_unmatched_numbered_footnote_is_removed(self):
        self.assertEqual(MODULE.name_from(["迷迭香提取物8)", "rosemaryextract"]), "迷迭香提取物")

    def test_residue_note_is_a_hard_name_boundary(self):
        recent = [
            "以亚硝酸钠计，残留量≤",
            "50mg/kg",
            "胭脂虫红 carminecochineal",
        ]

        self.assertEqual(MODULE.name_from(recent), "胭脂虫红")

    def test_split_basis_note_is_a_hard_name_boundary(self):
        recent = [
            "用量以磷酸根(PO4 3-)计",
            "磷酸化二淀粉磷酸酯 distarch phosphate",
        ]

        self.assertEqual(MODULE.name_from(recent), "磷酸化二淀粉磷酸酯")

    def test_split_food_category_is_a_hard_name_boundary(self):
        recent = ["橘类)70", "乙酸钠 sodium acetate"]

        self.assertEqual(MODULE.name_from(recent), "乙酸钠")

    def test_note_prefix_can_complete_a_split_food_name(self):
        food, note = MODULE.repair_food_and_note(
            "装饰糖果(如工艺造型，或用于蛋糕装饰)、顶饰(非水果",
            "材料)和甜汁",
        )

        self.assertEqual(
            food,
            "装饰糖果(如工艺造型，或用于蛋糕装饰)、顶饰(非水果材料)和甜汁",
        )
        self.assertEqual(note, "")

    def test_page_continuation_starting_with_product_completes_food_name(self):
        food, note = MODULE.repair_food_and_note(
            "可可制品、巧克力和巧克力制",
            "品，包括代可可脂巧克力及制品",
        )

        self.assertEqual(food, "可可制品、巧克力和巧克力制品，包括代可可脂巧克力及制品")
        self.assertEqual(note, "")

    def test_interleaved_dilution_note_is_removed_from_food_parenthesis(self):
        food, note = MODULE.repair_food_and_note(
            "果蔬汁(肉)饮料(包括发酵",
            "固体饮料按稀释型产品等)倍数增加使用量",
        )

        self.assertEqual(food, "果蔬汁(肉)饮料(包括发酵型产品等)")
        self.assertEqual(note, "固体饮料按稀释倍数增加使用量")

    def test_continued_header_token_in_dilution_note_is_repaired(self):
        food, note = MODULE.repair_food_and_note(
            "果蔬汁(浆)类饮料",
            "固体饮料按照稀释备注增加使用量",
        )

        self.assertEqual(food, "果蔬汁(浆)类饮料")
        self.assertEqual(note, "固体饮料按照稀释倍数增加使用量")

    def test_interleaved_residue_note_is_removed_from_food_parenthesis(self):
        food, note = MODULE.repair_food_and_note(
            "经表面处理的鲜水果(仅限柑",
            "残留量≤橘类)70mg/kg",
        )

        self.assertEqual(food, "经表面处理的鲜水果(仅限柑橘类)")
        self.assertEqual(note, "残留量≤70mg/kg")

    def test_split_dilution_note_does_not_enter_the_next_name(self):
        recent = [
            "使用量仅限粉状产品, 液态产",
            "品按照稀释倍数折算",
            "新红及其铝色淀 new red, new red aluminum lake",
        ]

        self.assertEqual(MODULE.name_from(recent), "新红及其铝色淀")

    def test_ins_heading_without_hao_is_recognised(self):
        match = MODULE.CNS_LINE.fullmatch("CNS号19.002INS952")

        self.assertIsNotNone(match)
        self.assertEqual(match.groups(), ("19.002", "952"))

    def test_empty_and_grouped_cns_headings_are_still_boundaries(self):
        empty = MODULE.CNS_LINE.fullmatch("CNS号INS号—")
        grouped = MODULE.CNS_LINE.fullmatch("CNS号01.106，15.008INS号338，450i")
        missing_hao = MODULE.CNS_LINE.fullmatch("CNS17.033INS号242")

        self.assertEqual(empty.groups(), ("", "—"))
        self.assertEqual(grouped.groups(), ("01.106，15.008", "338，450i"))
        self.assertEqual(missing_hao.groups(), ("17.033", "242"))

    def test_per_serving_unit_is_parsed_as_an_inline_unit(self):
        match = MODULE.INLINE.fullmatch("0.05g/份")

        self.assertEqual(match.groups(), ("0.05", "g/份"))

    def test_next_additive_heading_is_removed_from_previous_note(self):
        note = "固体饮料按稀释倍数增加使用量卡拉胶carrageenan"

        self.assertEqual(
            MODULE.strip_following_heading(note, "卡拉胶"),
            "固体饮料按稀释倍数增加使用量",
        )

    def test_measurement_basis_with_next_additive_name_is_preserved(self):
        note = "以姜黄素计姜黄素curcumin"

        self.assertEqual(MODULE.strip_following_heading(note, "姜黄素"), "以姜黄素计")

    def test_carrier_note_is_a_boundary_before_diphenyl_ether(self):
        recent = [
            "以即食食品计, 作为花生",
            "四烯酸( A R A) 和 二 十 二",
            "碳六烯酸( DHA) 载体",
            "联苯醚( 又名二苯醚) diphenyl ether",
        ]

        self.assertEqual(MODULE.name_from(recent), "联苯醚")

    def test_single_trailing_usage_character_is_not_part_of_next_name(self):
        recent = ["按稀释10倍计", "算", "琼珀酸二钠 disodium succinate"]

        self.assertEqual(MODULE.name_from(recent), "琼珀酸二钠")

    def test_previous_food_continuation_is_not_part_of_next_name(self):
        recent = [
            "可可制品、巧克力和巧克力制",
            "品(包括代可可脂巧克力及制品)以及糖果",
            "硬脂酸钙 calcium stearate",
        ]

        self.assertEqual(MODULE.name_from(recent), "硬脂酸钙")

    def test_physical_class_heading_can_differ_from_canonical_group_name(self):
        note = "司盘类[包括山梨醇酐单月桂酸酯(又名司盘20)"

        self.assertEqual(
            MODULE.strip_following_heading(
                note,
                "山梨醇酐单月桂酸酯，山梨醇酐单棕榈酸酯",
                ["司盘类[包括山梨醇酐单月桂酸酯(又名司"],
            ),
            "",
        )

    def test_page_number_is_not_a_partial_food_code_match(self):
        self.assertIsNone(MODULE.CODE.fullmatch("601"))
        self.assertIsNotNone(MODULE.CODE.fullmatch("16.06"))
        self.assertFalse(MODULE.food_row_start("65"))
        self.assertFalse(MODULE.food_row_start("80.0"))
        self.assertTrue(MODULE.food_row_start("16.06"))

    def test_adjacent_category_codes_are_split_after_character_collapse(self):
        self.assertEqual(
            MODULE.split_concatenated_food_codes("02.0302.02"),
            ["02.03", "02.02"],
        )

    def test_nested_category_exclusions_are_not_treated_as_leaked_values(self):
        self.assertFalse(
            MODULE.food_has_unexplained_number(
                "饮料类[14.01包装饮用水、14.02.01果蔬汁(浆)除外]"
            )
        )
        self.assertFalse(
            MODULE.food_has_unexplained_number(
                "除04.01.02.05外的果酱(如印度酸辣酱)"
            )
        )
        self.assertFalse(
            MODULE.food_has_unexplained_number("脂肪含量80%以上的乳化制品")
        )

    def test_value_leaked_after_parenthesis_remains_rejected(self):
        self.assertTrue(
            MODULE.food_has_unexplained_number(
                "液体复合调味料(不包括12.03、)2.5"
            )
        )
        self.assertTrue(
            MODULE.food_has_unexplained_number(
                "经表面处理的鲜水果(仅限柑橘类)70"
            )
        )

    def test_page_break_and_multiline_metadata_do_not_merge_two_additives(self):
        raw = "\n".join(
            [
                "磷酸化二淀粉磷酸酯 phosphate distarch phosphate",
                "CNS号20.017 INS号1413",
                "功能 增稠剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "14.06 固体饮料 0.5",
                "7)",
                "包括磷酸(湿法),最大使用量以磷酸根计。",
                "磷酸及磷酸盐[包括磷酸7),焦磷酸二氢二钠,",
                "磷酸三钾,磷酸三钠]",
                "phosphoric acid, phosphates",
                "17",
                "GB2760—2024\fCNS号01.106,15.008,",
                "15.004,15.007",
                "INS号338,450(i),342",
                "(ii),450(iii)",
                "功能 水分保持剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "01.0 乳及乳制品 5.0",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2024")

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][1], "磷酸化二淀粉磷酸酯")
        self.assertEqual(rows[0][8], "")
        self.assertEqual(rows[1][1], "磷酸及磷酸盐[包括磷酸,焦磷酸二氢二钠,磷酸三钾,磷酸三钠]")
        self.assertEqual(rows[1][2], "01.106,15.008,15.004,15.007")
        self.assertEqual(rows[1][3], "338,450(i),342(ii),450(iii)")
        self.assertIn("7)包括磷酸(湿法)", rows[1][8])

    def test_phosphate_entity_footnote_closes_outer_basis_parenthesis(self):
        note = (
            "7)包括磷酸(湿法),磷酸湿法仅用于14.04.01可乐型碳酸饮料,"
            "最大使用量为5.0g/kg(以即饮状态计,最大使用量以磷酸根(PO43-)计。"
        )

        repaired = MODULE.repair_entity_note(note)

        self.assertIn("磷酸根(PO43-)计)。", repaired)
        self.assertEqual(MODULE._unclosed_brackets(repaired.removeprefix("7)")), [])

    def test_gmp_food_name_continues_after_a_page_break(self):
        raw = "\n".join(
            [
                "淀粉磷酸酯钠 sodium starch phosphate",
                "CNS号20.013 INS号—",
                "功能 增稠剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "06.0 粮食和粮食制品，包括大米、 按生产需要适量使用",
                "17",
                "GB2760—2011\f表A.1(续)",
                "面粉、杂粮、块根植物、豆类和玉米提取的淀粉等",
                "(不包括06.01原粮及07.0类焙烤制品)",
                "07.01 面包 0.1",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "06.0",
                "粮食和粮食制品，包括大米、面粉、杂粮、块根植物、豆类和玉米提取的淀粉等"
                "(不包括06.01原粮及07.0类焙烤制品)",
                "GMP",
                "",
                "",
            ),
        )

    def test_gmp_row_retains_its_residue_note(self):
        raw = "\n".join(
            [
                "桂醛 cinnamaldehyde",
                "CNS号18.012 INS号—",
                "功能 防腐剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "04.01.01.02 经表面处理的鲜水果 按生产需要适量使用",
                "残留量≤0.3mg/kg",
                "05.02 糖果 0.1",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "04.01.01.02",
                "经表面处理的鲜水果",
                "GMP",
                "",
                "残留量≤0.3mg/kg",
            ),
        )

    def test_gmp_open_food_scope_closes_before_its_note(self):
        raw = "\n".join(
            [
                "硫酸铝钾 potassium aluminium sulfate",
                "CNS号06.004 INS号522",
                "功能 膨松剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "04.01.02.08 蜜饯凉果（仅限 按生产需要适量使用",
                "话化类） 铝的残留量≤100mg/kg（干样品，以Al计）",
                "05.02 糖果 0.1",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "04.01.02.08",
                "蜜饯凉果（仅限话化类）",
                "GMP",
                "",
                "铝的残留量≤100mg/kg（干样品，以Al计）",
            ),
        )

    def test_merged_food_cell_can_hold_numeric_and_gmp_rules(self):
        raw = "\n".join(
            [
                "海藻酸钠 sodium alginate",
                "CNS号20.004 INS号401",
                "功能 增稠剂、稳定剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "13.03 其他特殊膳食用食品（仅限13月龄~10岁特殊医学用途配方食品）",
                "1.0",
                "适用于13月龄~36月龄幼儿的产品",
                "按生产需要适量使用 适用于37月龄~10岁人群的产品",
                "核黄素 riboflavin",
                "CNS号08.148 INS号101(i)",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2024")

        self.assertEqual(
            [row[4:9] for row in rows],
            [
                (
                    "13.03",
                    "其他特殊膳食用食品（仅限13月龄~10岁特殊医学用途配方食品）",
                    "1.0",
                    "g/kg",
                    "适用于13月龄~36月龄幼儿的产品",
                ),
                (
                    "13.03",
                    "其他特殊膳食用食品（仅限13月龄~10岁特殊医学用途配方食品）",
                    "GMP",
                    "",
                    "适用于37月龄~10岁人群的产品",
                ),
            ],
        )

    def test_all_food_gmp_marker_completes_the_same_rule(self):
        raw = "\n".join(
            [
                "抗坏血酸钠 sodium ascorbate",
                "CNS号04.015 INS号301",
                "功能 抗氧化剂",
                "食品分类号 食品名称 最大使用量 备注",
                "各类食品，表A.2中编号为1~62、68",
                "的食品类别除外",
                "按生产需要适量使用",
                "抗坏血酸棕榈酸酯 ascorbyl palmitate",
                "CNS号04.011 INS号304",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2024")

        self.assertEqual(
            rows[0][4:9],
            (
                "00",
                "各类食品，表A.2中编号为1~62、68的食品类别除外",
                "GMP",
                "",
                "",
            ),
        )

    def test_bracketed_category_reference_before_gmp_is_not_a_numeric_rule(self):
        raw = "\n".join(
            [
                "麦芽糖醇和麦芽糖醇液 maltitol and maltitol syrup",
                "CNS号19.005,19.022 INS号965(i),965(ii)",
                "功能 甜味剂",
                "食品分类号 食品名称 最大使用量 备注",
                "12.10.03 液体复合调味料（不包括12.03，",
                "12.04）",
                "按生产需要适量使用",
                "麦芽酚 maltol",
                "CNS号12.008 INS号636",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2014")

        self.assertEqual(len(rows), 1)
        self.assertEqual(
            rows[0][4:9],
            (
                "12.10.03",
                "液体复合调味料（不包括12.03，12.04）",
                "GMP",
                "",
                "",
            ),
        )

    def test_page_footnote_is_relocated_to_named_additive(self):
        footnote = (
            "3)添加该添加剂的食品应标明:阿斯巴甜(含苯丙氨酸)。"
        )
        rows = [
            ("2024", "阿拉伯胶", "20.008", "414", "00", "各类食品", "GMP", "", footnote),
            ("2024", "阿斯巴甜", "19.004", "951", "11.04", "餐桌甜味料", "GMP", "", ""),
            ("2024", "阿斯巴甜", "19.004", "951", "16.01", "果冻", "1.0", "g/kg", "果冻粉备注"),
        ]

        relocated = MODULE.relocate_misordered_entity_notes(rows)

        self.assertEqual(relocated[0][8], "")
        self.assertEqual(relocated[1][8], footnote)
        self.assertEqual(relocated[2][8], footnote + " 果冻粉备注")

    def test_cross_page_food_scope_is_removed_from_numeric_note(self):
        raw = "\n".join(
            [
                "磷酸及磷酸盐 phosphoric acid, phosphates",
                "CNS号01.106,15.008 INS号338,450(i)",
                "功能 水分保持剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "02.05 其他油脂或油脂制品 20.0 可单独或混合使用，最大使",
                "17",
                "GB2760—2011\f表A.1(续)",
                "（仅限植脂末） 用量以磷酸根（PO4 3-）计",
                "03.0 冷冻饮品 1.0",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "02.05",
                "其他油脂或油脂制品（仅限植脂末）",
                "20.0",
                "g/kg",
                "可单独或混合使用，最大使用量以磷酸根（PO43-）计",
            ),
        )

    def test_cross_page_note_is_removed_from_open_food_parenthesis(self):
        raw = "\n".join(
            [
                "胭脂虫红 carmine cochineal",
                "CNS号08.145 INS号120",
                "功能 着色剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "12.10 复合调味料（12.10.02半固体 1.0 以胭脂红酸计",
                "78",
                "GB2760—2011\f表A.1(续)",
                "复合调味料除外）",
                "12.10.02 半固体复合调味料 0.05 以胭脂红酸计",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "12.10",
                "复合调味料（12.10.02半固体复合调味料除外）",
                "1.0",
                "g/kg",
                "以胭脂红酸计",
            ),
        )

    def test_cross_page_trailing_exclusion_moves_from_note_to_food(self):
        raw = "\n".join(
            [
                "胭脂红及其铝色淀 ponceau 4R",
                "CNS号08.002 INS号124",
                "功能 着色剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "12.10.02 半固体复合调味料 0.5 以胭脂红计",
                "79",
                "GB2760—2011\f表A.1(续)",
                "（12.10.02.01蛋黄酱、沙拉酱除外）",
                "12.10.02.01 蛋黄酱、沙拉酱 0.2 以胭脂红计",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            rows[0][4:9],
            (
                "12.10.02",
                "半固体复合调味料（12.10.02.01蛋黄酱、沙拉酱除外）",
                "0.5",
                "g/kg",
                "以胭脂红计",
            ),
        )

    def test_table_footnote_is_not_attached_to_the_last_rule(self):
        for marker in (
            "a在表A.1中使用范围以食品分类号和食品名称表示。",
            "1)在表A.1中使用范围以食品分类号和食品名称表示。",
        ):
            with self.subTest(marker=marker):
                food, note = MODULE.repair_food_and_note("鲜蛋", marker)
                self.assertEqual((food, note), ("鲜蛋", ""))

    def test_separate_note_sentences_keep_a_boundary(self):
        food, note = MODULE.repair_food_and_note(
            "饮料类（14.01包装饮用水类除外）",
            "可单独或混合使用，最大使用量以磷酸根（PO43-）计"
            "固体饮料按稀释倍数增加使用量",
        )

        self.assertEqual(food, "饮料类（14.01包装饮用水类除外）")
        self.assertEqual(
            note,
            "可单独或混合使用，最大使用量以磷酸根（PO43-）计；"
            "固体饮料按稀释倍数增加使用量",
        )

    def test_printed_duplicate_in_source_note_is_preserved(self):
        food, note = MODULE.repair_food_and_note(
            "果冻",
            "以胭脂红酸计，如用于果冻粉，按冲调倍数增加使用量使用量",
        )

        self.assertEqual(food, "果冻")
        self.assertTrue(note.endswith("使用量使用量"))

    def test_standalone_ten_is_value_after_split_category_description(self):
        raw = "\n".join(
            [
                "蔗糖脂肪酸酯 sucrose esters of fatty acid",
                "CNS号10.001 INS号473",
                "功能 乳化剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "02.02 水油状脂肪乳化制品 10.0",
                "02.03 02.02 类以外的脂肪乳化制品",
                "10.0 以脂肪酸计",
                "03.0 冷冻饮品 1.5",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(
            [(row[4], row[5], row[6]) for row in rows],
            [
                ("02.02", "水油状脂肪乳化制品", "10.0"),
                ("02.03", "02.02类以外的脂肪乳化制品", "10.0"),
                ("03.0", "冷冻饮品", "1.5"),
            ],
        )

    def test_value_interleaved_inside_food_parenthesis_is_recovered(self):
        raw = "\n".join(
            [
                "天然苋菜红 natural amaranthus red",
                "CNS号08.130 INS号—",
                "功能 着色剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "14.02.03 果蔬汁(肉)饮料(包括发酵 0.25 固体饮料按稀释",
                "型产品等) 倍数增加使用量",
                "15.02 配制酒 0.25",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(rows[0][4:9], (
            "14.02.03",
            "果蔬汁(肉)饮料(包括发酵型产品等)",
            "0.25",
            "g/kg",
            "固体饮料按稀释倍数增加使用量",
        ))

    def test_residue_limit_does_not_replace_interleaved_main_limit(self):
        raw = "\n".join(
            [
                "乙萘酚 beta-naphthol",
                "CNS号17.021 INS号—",
                "功能 防腐剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "04.01.01.02 经表面处理的鲜水果(仅限柑 0.1 残留量≤",
                "橘类) 70mg/kg",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2011")

        self.assertEqual(rows[0][4:9], (
            "04.01.01.02",
            "经表面处理的鲜水果(仅限柑橘类)",
            "0.1",
            "g/kg",
            "残留量≤70mg/kg",
        ))

    def test_category_exclusion_continues_across_an_open_parenthesis(self):
        raw = "\n".join(
            [
                "苯甲酸及其钠盐 benzoic acid",
                "CNS号17.001 INS号210",
                "功能 防腐剂",
                "食品分类号 食品名称 最大使用量/(g/kg) 备注",
                "12.10.03 液体复合调味料(不包括12.03,",
                "12.04 ) 1.0 以苯甲酸计",
                "15.02 配制酒 0.4",
            ]
        )
        completed = SimpleNamespace(stdout=raw.encode("utf-8"))

        MODULE.QUAR.clear()
        with patch.object(MODULE.subprocess, "run", return_value=completed):
            rows = MODULE.extract("unused.pdf", "2014")

        self.assertEqual(rows[0][4], "12.10.03")
        self.assertEqual(rows[0][5], "液体复合调味料(不包括12.03,12.04)")
        self.assertEqual(rows[0][6:9], ("1.0", "g/kg", "以苯甲酸计"))


if __name__ == "__main__":
    unittest.main()
