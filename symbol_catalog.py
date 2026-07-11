"""Expandable catalog for every symbol family in the supplied reference sheet.

The UI shows only the six core jobs to new players. This module keeps the
complete catalog separate, so every source cell can receive a game purpose
without forcing beginners to learn it immediately.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum


class PlayKind(StrEnum):
    UNIT = "部隊カード"
    SUPPORT = "支援カード"
    FACILITY = "施設カード"
    ENTITY = "装備・トークン"
    TASK_FORCE = "編成カード"
    VISUAL = "編制・表示要素"


class Domain(StrEnum):
    JOINT = "統合"
    LAND = "陸上"
    AIR = "航空・宇宙"
    SEA = "海上"
    SPECIAL = "特殊作戦"
    GENERIC = "共通"


class UnlockStage(IntEnum):
    INTRO = 1
    MOBILITY = 2
    SUPPORT = 3
    JOINT = 4
    SPECIALIST = 5


STAGE_LABELS = {
    UnlockStage.INTRO: "導入：基本6兵科",
    UnlockStage.MOBILITY: "機動編：派生部隊",
    UnlockStage.SUPPORT: "支援編：後方・情報",
    UnlockStage.JOINT: "統合作戦編：陸海空",
    UnlockStage.SPECIALIST: "専門編：特殊・編制",
}


@dataclass(frozen=True, slots=True)
class SymbolFamily:
    id: str
    name: str
    play_kind: PlayKind
    domain: Domain
    unlock_stage: UnlockStage
    token: str
    plain_role: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SymbolDefinition:
    id: str
    source_cell_id: str
    visual_id: str
    name: str
    family_id: str
    family_name: str
    play_kind: PlayKind
    domain: Domain
    unlock_stage: UnlockStage
    token: str
    plain_role: str


SYMBOL_FAMILIES: tuple[SymbolFamily, ...] = (
    SymbolFamily(
        "frames", "枠の種類", PlayKind.VISUAL, Domain.GENERIC,
        UnlockStage.SPECIALIST, "□", "記号が部隊、人、活動、どの空間の存在なのかを見分けます。",
        (
            "部隊・施設の枠", "人の枠", "活動・事象の枠", "地表エンティティの枠",
            "空中エンティティの枠", "表面下エンティティの枠", "宇宙エンティティの枠",
        ),
    ),
    SymbolFamily(
        "joint", "統合・任務部隊", PlayKind.TASK_FORCE, Domain.JOINT,
        UnlockStage.JOINT, "JTF", "複数の得意分野をまとめ、デッキ全体の方針を決めます。",
        (
            "基本・不詳部隊", "統合任務部隊（JTF）", "海上任務部隊（MTF）",
            "陸上任務部隊（LTF）", "航空任務部隊（ATF）", "諸兵科連合機械化部隊",
            "諸兵科連合空挺部隊", "空中強襲部隊", "海兵空地任務部隊",
            "輸送任務部隊", "水陸両用任務部隊",
        ),
    ),
    SymbolFamily(
        "naval_units", "海軍組織", PlayKind.UNIT, Domain.SEA,
        UnlockStage.JOINT, "⚓", "海上の戦線、輸送路、上陸地点を確保します。",
        (
            "海軍基地・沿岸組織", "航空母艦", "揚陸艦", "水上戦闘艦", "戦艦",
            "巡洋艦", "駆逐艦", "フリゲート", "コルベット", "潜水艦", "給油艦",
        ),
    ),
    SymbolFamily(
        "aviation_units", "航空組織", PlayKind.UNIT, Domain.AIR,
        UnlockStage.JOINT, "✦", "戦線を越えて索敵・輸送・支援を行います。",
        (
            "空軍・軍用航空隊", "固定翼航空隊", "戦闘・攻撃航空隊", "輸送航空隊",
            "長距離哨戒航空隊", "回転翼航空隊", "攻撃ヘリコプター隊",
            "汎用ヘリコプター隊", "偵察ヘリコプター隊", "空中給油隊", "無人航空隊",
        ),
    ),
    SymbolFamily(
        "special_operations", "特殊作戦組織", PlayKind.UNIT, Domain.SPECIAL,
        UnlockStage.SPECIALIST, "SOF", "条件を満たしたときに、通常とは違う任務を実行します。",
        (
            "特殊作戦部隊", "特殊作戦支援部隊", "特殊作戦歩兵部隊",
            "特殊作戦偵察部隊", "特殊作戦航空部隊", "特殊作戦砲兵部隊",
            "特殊作戦潜水部隊", "特殊作戦CBRN対処部隊", "特殊作戦工兵部隊",
            "特殊作戦補給支援部隊", "特殊作戦衛生部隊",
        ),
    ),
    SymbolFamily(
        "infantry", "歩兵組織", PlayKind.UNIT, Domain.LAND,
        UnlockStage.INTRO, "╳", "戦線を取り、確保した場所を守ります。",
        (
            "歩兵", "軽歩兵", "自動車化歩兵", "機械化歩兵（装軌式）", "機甲歩兵",
            "軽装甲機動歩兵", "機械化歩兵（装輪式）", "空挺歩兵", "空中機動歩兵",
            "水陸両用歩兵", "極寒地歩兵",
        ),
    ),
    SymbolFamily(
        "infantry_support", "歩兵・偵察支援", PlayKind.SUPPORT, Domain.LAND,
        UnlockStage.MOBILITY, "CS", "歩兵の索敵、火力、移動を補助します。",
        (
            "歩兵戦闘支援部隊", "軽歩兵戦闘支援部隊", "歩兵兵器部隊",
            "歩兵狙撃部隊", "歩兵迫撃砲部隊", "施設整備工兵", "偵察部隊",
            "軽偵察部隊", "空挺偵察部隊", "水陸両用偵察部隊", "極寒地偵察部隊",
        ),
    ),
    SymbolFamily(
        "armor", "機甲組織", PlayKind.UNIT, Domain.LAND,
        UnlockStage.INTRO, "⬭", "補給を使って、相手の守りを一気に突破します。",
        (
            "機甲部隊", "軽機甲部隊", "重機甲部隊", "機甲部隊（装軌式）",
            "機甲部隊（装輪式）", "機甲偵察部隊", "重機甲偵察部隊",
            "自動車化偵察部隊", "軽装甲偵察部隊（装輪式）",
            "軽装甲兵員輸送部隊（装軌式）", "水陸両用兵員輸送部隊（装軌式）",
            "水陸両用兵員輸送部隊（装輪式）",
        ),
    ),
    SymbolFamily(
        "engineer", "工兵組織", PlayKind.SUPPORT, Domain.LAND,
        UnlockStage.INTRO, "Π", "道、橋、陣地を整えて味方を動きやすくします。",
        (
            "工兵", "戦闘工兵", "戦闘工兵（装軌式）", "戦闘工兵（装輪式）",
            "自動車化工兵", "機甲工兵", "工兵支援部隊", "爆発物処理工兵",
            "工兵物資部隊", "偵察工兵", "建設工兵",
        ),
    ),
    SymbolFamily(
        "artillery", "砲兵組織", PlayKind.SUPPORT, Domain.LAND,
        UnlockStage.INTRO, "●", "同じ戦線の制圧部隊を、大きな支援力で助けます。",
        (
            "砲兵", "機械化砲兵", "自走砲（装軌式）", "自走砲（装輪式）",
            "牽引砲", "ロケット砲", "迫撃砲", "機械化迫撃砲（装輪式）",
            "野戦観測部隊", "目標捕捉部隊", "レーザー・無人機目標捕捉部隊",
        ),
    ),
    SymbolFamily(
        "air_antiarmor", "防空・対戦車・ミサイル", PlayKind.SUPPORT, Domain.LAND,
        UnlockStage.SUPPORT, "AA", "航空や装甲など、特定の相手への対策を担当します。",
        (
            "対空・対戦車砲部隊", "対空砲部隊", "ミサイル装備対空部隊",
            "短距離対空部隊", "対戦車砲部隊", "自動車化対戦車部隊",
            "機械化対戦車部隊", "ミサイル装備対戦車部隊", "地対地ミサイル部隊",
            "沿岸対艦ミサイル部隊", "航空管制部隊",
        ),
    ),
    SymbolFamily(
        "information_support", "情報・通信・治安支援", PlayKind.SUPPORT, Domain.GENERIC,
        UnlockStage.SUPPORT, "EW", "相手の情報を調べ、味方の連携を守ります。",
        (
            "戦闘支援部隊", "CBRN防護部隊", "軍事情報部隊", "通信・情報システム部隊",
            "電子戦部隊", "航空通信管制部隊", "通信システム復旧部隊", "サイバー部隊",
            "憲兵部隊", "治安部隊", "レンジャー部隊",
        ),
    ),
    SymbolFamily(
        "logistics", "後方支援組織", PlayKind.SUPPORT, Domain.GENERIC,
        UnlockStage.INTRO, "→", "補給、整備、輸送によって味方を動かし続けます。",
        (
            "後方支援部隊", "兵站部隊", "輸送部隊", "兵站・輸送部隊", "弾薬部隊",
            "燃料・潤滑剤部隊", "武器補給所", "給食・糧食部隊", "整備部隊",
            "航空整備部隊", "衛生部隊",
        ),
    ),
    SymbolFamily(
        "ground_entities", "地上の装備・エンティティ", PlayKind.ENTITY, Domain.LAND,
        UnlockStage.MOBILITY, "▣", "部隊が使用する車両や装備として盤面に置きます。",
        (
            "戦車", "軽戦車", "中戦車", "重戦車", "装甲戦闘車両", "装甲偵察車両",
            "榴弾砲", "中榴弾砲", "重榴弾砲", "装甲兵員輸送車", "装甲救急車",
        ),
    ),
    SymbolFamily(
        "air_space_entities", "航空・宇宙のエンティティ", PlayKind.ENTITY, Domain.AIR,
        UnlockStage.JOINT, "△", "航空支援、迎撃、輸送、観測のトークンとして使います。",
        (
            "戦闘機（飛行中）", "戦闘機（待機中）", "爆撃機", "回転翼機（飛行中）",
            "回転翼機（待機中）", "固定翼哨戒機", "固定翼早期警戒機", "地対空ミサイル",
            "空対空ミサイル", "弾道ミサイル", "衛星",
        ),
    ),
    SymbolFamily(
        "sea_entities", "海上のエンティティ", PlayKind.ENTITY, Domain.SEA,
        UnlockStage.JOINT, "◡", "艦艇、機雷、潜水艦を任務目標や支援として使います。",
        (
            "重巡洋艦", "誘導ミサイル巡洋艦", "誘導ミサイル駆逐艦",
            "誘導ミサイルフリゲート", "対潜フリゲート", "対潜コルベット", "機雷",
            "潜水艦", "攻撃型潜水艦", "弾道ミサイル潜水艦", "海上補給艦",
        ),
    ),
    SymbolFamily(
        "echelon", "部隊規模・編制", PlayKind.VISUAL, Domain.GENERIC,
        UnlockStage.SPECIALIST, "Ⅱ", "カードの使用実績や編制の大きさを表します。序盤の強さには影響しません。",
        (
            "総軍", "軍集団", "軍", "軍団", "師団", "旅団", "連隊", "大隊",
            "中隊", "小隊", "分隊（Section）", "分隊（Squad）", "班", "階梯（echelon）",
        ),
    ),
    SymbolFamily(
        "task_organizations", "司令部・任務部隊組織", PlayKind.TASK_FORCE, Domain.JOINT,
        UnlockStage.SPECIALIST, "HQ", "司令部、基地、任務部隊の編制単位として使います。",
        (
            "司令部", "基地・駐屯地", "遠征軍", "任務軍団", "任務師団",
            "任務旅団", "任務大隊", "任務中隊", "任務小隊", "階梯グループ",
        ),
    ),
    SymbolFamily(
        "other_organizations", "その他の組織", PlayKind.FACILITY, Domain.GENERIC,
        UnlockStage.SPECIALIST, "HQ", "司令部や訓練施設など、戦場の外側を支える要素です。",
        ("司令部部隊", "訓練部隊", "教育部隊", "国家憲兵隊"),
    ),
)


FAMILY_INDEX = {family.id: family for family in SYMBOL_FAMILIES}


def _build_catalog() -> tuple[SymbolDefinition, ...]:
    catalog: list[SymbolDefinition] = []
    for family in SYMBOL_FAMILIES:
        for index, name in enumerate(family.items, 1):
            catalog.append(
                SymbolDefinition(
                    id=f"{family.id}_{index:02d}",
                    source_cell_id=f"{family.id}/{index:02d}",
                    visual_id=f"reference_7.{family.id}.{index:02d}",
                    name=name,
                    family_id=family.id,
                    family_name=family.name,
                    play_kind=family.play_kind,
                    domain=family.domain,
                    unlock_stage=family.unlock_stage,
                    token=family.token,
                    plain_role=family.plain_role,
                )
            )
    return tuple(catalog)


SYMBOL_CATALOG = _build_catalog()
SYMBOL_INDEX = {symbol.id: symbol for symbol in SYMBOL_CATALOG}

# Existing playable cards already point into the complete reference manifest.
# Future cards should add one entry here before they can be shipped.
CARD_SYMBOL_IDS = {
    "infantry_1": "infantry_01",
    "infantry_2": "infantry_02",
    "infantry_3": "infantry_09",
    "armor_1": "armor_01",
    "armor_2": "infantry_04",
    "armor_3": "armor_03",
    "recon_1": "infantry_support_07",
    "recon_2": "aviation_units_11",
    "recon_3": "information_support_05",
    "artillery_1": "artillery_01",
    "artillery_2": "artillery_03",
    "artillery_3": "artillery_06",
    "engineer_1": "engineer_01",
    "engineer_2": "engineer_11",
    "engineer_3": "engineer_11",
    "logistics_1": "logistics_02",
    "logistics_2": "logistics_09",
    "logistics_3": "logistics_03",
}


def symbols_for_family(family_id: str) -> tuple[SymbolDefinition, ...]:
    return tuple(symbol for symbol in SYMBOL_CATALOG if symbol.family_id == family_id)
