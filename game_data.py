"""Canonical card data and UI-independent helpers for COMMAND GRID."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True, slots=True)
class UnitCard:
    id: str
    name: str
    branch: str
    symbol: str
    echelon: str
    cost: int
    control: int
    support: int
    recon: int
    supply: int
    rarity: str
    owned: bool
    tagline: str
    game_text: str
    military_note: str
    good_with: str
    difficulty: str = "かんたん"


@dataclass(frozen=True, slots=True)
class FormationScale:
    id: str
    name: str
    marker: str
    catalog_symbol_id: str


FORMATION_SCALES: tuple[FormationScale, ...] = (
    FormationScale("native", "カード固有", "", ""),
    FormationScale("battalion", "大隊", "III", "echelon_08"),
    FormationScale("brigade", "旅団", "X", "echelon_06"),
    FormationScale("division", "師団", "XX", "echelon_05"),
)
FORMATION_INDEX = {formation.id: formation for formation in FORMATION_SCALES}


def get_formation(formation_id: str | None) -> FormationScale:
    return FORMATION_INDEX.get(str(formation_id), FORMATION_INDEX["native"])


def formation_label(card: UnitCard, formation_id: str | None) -> tuple[str, str]:
    formation = get_formation(formation_id)
    if formation.id == "native":
        return card.echelon, card.echelon
    return formation.marker, formation.name


ROLE_INFO = {
    "歩兵": {
        "verb": "場所を取る",
        "plain": "戦線を確保し、守る基本役です。迷ったら前列に置きます。",
        "note": "歩兵は、地域や拠点を確保することを得意とする部隊です。",
        "color": "#60AFFF",
        "icon": "shield",
    },
    "機甲": {
        "verb": "一気に押す",
        "plain": "高い力で相手の守りを突破しますが、補給を多く使います。",
        "note": "機甲部隊は、装甲車両の機動力と防護力を生かして前進します。",
        "color": "#F4C95D",
        "icon": "speed",
    },
    "偵察": {
        "verb": "隠れた相手を見る",
        "plain": "未確認の相手カードを見つけ、味方の支援を当てやすくします。",
        "note": "偵察は、相手の位置や状況を調べて味方へ知らせる役割です。",
        "color": "#9A8CFF",
        "icon": "visibility",
    },
    "砲兵": {
        "verb": "遠くから助ける",
        "plain": "後方から前列を支援します。単独では戦線を確保できません。",
        "note": "砲兵は、離れた場所から火力を届けて地上部隊を支援します。",
        "color": "#FF8C82",
        "icon": "my_location",
    },
    "工兵": {
        "verb": "道と守りを整える",
        "plain": "陣地を作り、味方の移動や守備を助けます。",
        "note": "工兵は、施設・道路・橋・障害物などを扱う技術的な支援部隊です。",
        "color": "#55D39A",
        "icon": "construction",
    },
    "兵站": {
        "verb": "味方を動かし続ける",
        "plain": "補給を増やし、機甲などの重い部隊が力を出せるようにします。",
        "note": "兵站は、物資・輸送・整備などを通して部隊の活動を支えます。",
        "color": "#55C7D9",
        "icon": "local_shipping",
    },
}


CARDS: tuple[UnitCard, ...] = (
    UnitCard(
        "infantry_1", "第1歩兵中隊", "歩兵", "╳", "中隊", 2, 3, 1, 0, 0,
        "標準", True, "制圧と支援を備えた基本部隊",
        "配置した戦線に制圧力3と支援力1を加えます。自身に制圧力があるため、支援力も有効になります。",
        "中隊は複数の小隊からなる部隊規模の一つです。本作では遊びやすく簡略化しています。",
        "同じ戦線へ支援力の高いカードを加えると、制圧力を土台に戦線力を伸ばせます。",
    ),
    UnitCard(
        "infantry_2", "市街地警備隊", "歩兵", "╳", "小隊", 2, 4, 0, 0, 0,
        "専門", True, "高い制圧力で戦線を取る",
        "配置した戦線に制圧力4を加えます。場所を選ばず、単独でも安定した戦線力を出せます。",
        "歩兵は複雑な地形や建物がある場所でも拠点を保持する役割を担います。",
        "支援力を持つカードと同じ戦線に置くと、その支援を有効にできます。",
    ),
    UnitCard(
        "infantry_3", "空中機動歩兵班", "歩兵", "╳", "分隊", 3, 2, 1, 0, 0,
        "専門", False, "制圧と支援を一枚で補う",
        "配置した戦線に制圧力2と支援力1を加えます。自身の制圧力によって支援力も有効になります。",
        "空中機動は、航空輸送を利用して部隊を素早く移す考え方です。",
        "偵察カードと同じ戦線に置くと、情報を得ながら戦線力も確保できます。", "ふつう",
    ),
    UnitCard(
        "armor_1", "第4機甲中隊", "機甲", "⬭", "中隊", 4, 5, 0, 0, -2,
        "標準", True, "補給があれば高い突破力",
        "制圧力5と補給需要2を持ちます。需要を完全に満たすと機甲ボーナスで戦線力が2上がり、不足時は不足分だけ下がります。",
        "機甲部隊は、戦車などの装甲車両を中心に機動力と防護力を生かします。",
        "補給を2以上生み出す兵站カードと同じ戦線に置くのが基本です。", "ふつう",
    ),
    UnitCard(
        "armor_2", "機械化歩兵隊", "機甲", "╳◯", "小隊", 3, 4, 1, 0, -1,
        "標準", True, "制圧と支援を持つ軽い機甲",
        "制圧力4、支援力1、補給需要1を持ちます。完全補給なら機甲ボーナスで戦線力が2上がります。",
        "機械化歩兵は、装甲車両などで移動する歩兵を指します。",
        "補給を生み出す兵站カードと合わせると、不足を防ぎながら機甲ボーナスを得られます。",
    ),
    UnitCard(
        "armor_3", "重装甲突破隊", "機甲", "⬭", "大隊", 5, 6, 0, 0, -3,
        "司令部", False, "重いが最大級の突破役",
        "制圧力6と補給需要3を持ちます。完全補給なら機甲ボーナスで戦線力が2上がり、不足時は不足分だけ下がります。",
        "大隊は複数の中隊をまとめる規模です。本作ではカード1枚として抽象化しています。",
        "合計3以上の補給を同じ戦線で用意すると、最大の戦線力を発揮できます。", "むずかしい",
    ),
    UnitCard(
        "recon_1", "前方偵察班", "偵察", "╱", "分隊", 1, 1, 0, 3, 0,
        "標準", True, "同じ戦線の未確認部隊を探す",
        "偵察値3により、同じ戦線にいる未確認の相手カードを最大3枚公開します。制圧力1も加えます。",
        "偵察は戦う前に情報を集め、味方が判断しやすい状況を作ります。",
        "制圧力や支援力の高いカードと同じ戦線に置くと、情報と戦線力を両立できます。",
    ),
    UnitCard(
        "recon_2", "無人偵察隊", "偵察", "◇", "小隊", 2, 0, 1, 4, 0,
        "専門", True, "一つの戦線を広く偵察する",
        "偵察値4により、同じ戦線にいる未確認の相手カードを最大4枚公開します。味方の制圧力があれば支援力1も加わります。",
        "無人機などのセンサーを用いる偵察を、ゲーム向けに一つのカードで表現しています。",
        "制圧力を持つカードと同じ戦線に置くと、支援力を有効にしながら偵察できます。", "ふつう",
    ),
    UnitCard(
        "recon_3", "電子偵察班", "偵察", "EW", "班", 2, 0, 1, 3, 0,
        "専門", False, "未確認部隊を継続して探す",
        "偵察値3により、同じ戦線にいる未確認の相手カードを最大3枚公開します。味方の制圧力があれば支援力1も加わります。",
        "電子的な信号から情報を得る活動を、初心者向けに単純化しています。",
        "制圧力を持つカードと組み合わせると、偵察しながら支援力も戦線へ加えられます。", "むずかしい",
    ),
    UnitCard(
        "artillery_1", "野戦砲兵中隊", "砲兵", "●", "中隊", 3, 0, 4, 0, -1,
        "標準", True, "制圧部隊を強く支援する",
        "支援力4と補給需要1を持ちます。同じ戦線に味方の制圧力があると支援が有効になり、補給不足分は戦線力から引かれます。",
        "砲兵は、離れた位置から火力支援を行う役割です。",
        "歩兵など制圧力を持つカードと、補給を生む兵站カードを同じ戦線にそろえると安定します。",
    ),
    UnitCard(
        "artillery_2", "自走砲兵隊", "砲兵", "●◯", "小隊", 4, 0, 5, 0, -2,
        "専門", True, "大きな支援力を加える",
        "支援力5と補給需要2を持ちます。同じ戦線に味方の制圧力があると支援が有効になり、補給不足分は戦線力から引かれます。",
        "自走砲は車両に載せた砲で、移動しやすいことが特徴です。",
        "制圧力を持つカードと、補給を2以上生む兵站カードを同じ戦線に置くと力を出せます。", "ふつう",
    ),
    UnitCard(
        "artillery_3", "ロケット支援隊", "砲兵", "⌁", "中隊", 5, 0, 6, 0, -3,
        "専門", False, "最大級の支援力を加える",
        "支援力6と補給需要3を持ちます。同じ戦線に味方の制圧力があると支援が有効になり、補給不足分は戦線力から引かれます。",
        "ロケット砲は複数のロケット弾を発射し、離れた場所から火力支援を行う装備です。",
        "制圧力を持つカードと、合計3以上の補給を生む兵站カードを同じ戦線にそろえます。", "むずかしい",
    ),
    UnitCard(
        "engineer_1", "第2工兵中隊", "工兵", "Π", "中隊", 2, 2, 2, 0, 0,
        "標準", True, "制圧と支援を同時に加える",
        "配置した戦線に制圧力2と支援力2を加えます。自身の制圧力によって支援力も有効になります。",
        "工兵は道路・陣地・障害物などを扱い、味方の活動を支えます。",
        "支援力の高いカードを同じ戦線に加えると、制圧力を土台にさらに戦線力を伸ばせます。",
    ),
    UnitCard(
        "engineer_2", "架橋工兵隊", "工兵", "∩", "小隊", 2, 1, 2, 0, 0,
        "専門", True, "小さな制圧で支援を有効にする",
        "配置した戦線に制圧力1と支援力2を加えます。自身の制圧力があるため、支援力も有効になります。",
        "架橋は、部隊が川や溝を越えられるよう通路を作る支援です。",
        "偵察や兵站など制圧力が低いカードと同じ戦線に置くと、支援を有効にする土台になります。", "ふつう",
    ),
    UnitCard(
        "engineer_3", "陣地構築隊", "工兵", "Π", "小隊", 3, 1, 3, 0, 0,
        "専門", False, "高い支援力を自分で有効にする",
        "配置した戦線に制圧力1と支援力3を加えます。自身の制圧力があるため、支援力も有効になります。",
        "陣地構築とは、味方が守りやすい場所を整える活動です。",
        "制圧力の高いカードと同じ戦線に置くと、安定した土台へ支援力を追加できます。", "ふつう",
    ),
    UnitCard(
        "logistics_1", "前線補給中隊", "兵站", "→", "中隊", 2, 1, 1, 0, 3,
        "標準", True, "補給3で重い部隊を支える",
        "配置した戦線に補給3、制圧力1、支援力1を加えます。機甲の需要を完全に満たすと、その機甲は戦線力2のボーナスを得ます。",
        "補給部隊は、必要な物資を前方へ届けて活動を支えます。",
        "補給需要が3以下の機甲や砲兵と同じ戦線に置くと、不足による戦線力低下を防げます。",
    ),
    UnitCard(
        "logistics_2", "整備支援隊", "兵站", "⌁", "小隊", 2, 1, 2, 0, 3,
        "標準", True, "補給と支援をまとめて加える",
        "配置した戦線に補給3、制圧力1、支援力2を加えます。機甲を完全補給すると、その機甲は戦線力2のボーナスを得ます。",
        "整備は、装備を使い続けられる状態に保つ重要な後方支援です。",
        "補給を必要とする機甲や砲兵と同じ戦線に置くと、補給と戦線力を同時に補えます。",
    ),
    UnitCard(
        "logistics_3", "戦域輸送隊", "兵站", "↔", "中隊", 3, 0, 2, 0, 4,
        "専門", False, "一つの戦線へ補給4を届ける",
        "配置した戦線に補給4と支援力2を加えます。味方の制圧力があれば支援が有効になり、複数の補給需要もまとめて満たせます。",
        "輸送は、人員や物資を必要な場所へ動かす兵站の中心的な役割です。",
        "補給需要の大きい機甲や砲兵を同じ戦線へ集める構成に向いています。", "むずかしい",
    ),
)


CARD_INDEX = {card.id: card for card in CARDS}

STARTER_DECK: tuple[str, ...] = (
    "infantry_1", "infantry_2", "armor_1", "armor_2",
    "recon_1", "recon_2", "artillery_1", "artillery_2",
    "engineer_1", "engineer_2", "logistics_1", "logistics_2",
)


GLOSSARY = (
    ("戦線", "カードを置いて取り合う3つの場所です。左・中央・右に分かれます。"),
    ("制圧力", "その場所を確保するための数値です。大きい側が戦線を取りやすくなります。"),
    ("兵科", "部隊が得意とする仕事の種類です。本作では6種類から始めます。"),
    ("索敵", "隠れている相手カードを見ることです。普段の言葉では『相手を見つける』です。"),
    ("未確認部隊", "まだ種類が分からない相手カードです。偵察すると正体が分かります。"),
    ("支援", "前列にいる味方カードを助けることです。支援だけでは場所を取れません。"),
    ("補給", "重い部隊を動かし続けるために必要な支えです。"),
    ("兵站", "物資・輸送・整備などによって味方を動かし続ける仕事です。"),
    ("前列", "戦線を直接確保する部隊を置く場所です。"),
    ("支援列", "前列の味方を助ける部隊を置く場所です。"),
    ("同時命令", "両者が行動を伏せて選び、同時に公開する仕組みです。"),
    ("任務点", "指定された行動を達成すると得られる、もう一つの勝利用ポイントです。"),
    ("諸兵科連合", "違う得意分野を持つ部隊を組み合わせ、互いの弱点を補うことです。"),
    ("左翼・右翼", "盤面の左側・右側を指します。本作では左戦線・右戦線と併記します。"),
)


def get_card(card_id: str) -> UnitCard:
    """Return one card and fail loudly for an invalid card ID."""
    return CARD_INDEX[card_id]


def analyze_deck(card_ids: Iterable[str]) -> dict[str, object]:
    """Produce plain-language deck feedback without depending on NiceGUI."""
    cards = [get_card(card_id) for card_id in card_ids]
    branches = {name: 0 for name in ROLE_INFO}
    for card in cards:
        branches[card.branch] += 1

    front = min(5, round(sum(card.control for card in cards) / 8))
    vision = min(5, round(sum(card.recon for card in cards) / 3))
    support = min(5, round(sum(card.support for card in cards) / 5))
    supply_need = abs(sum(min(0, card.supply) for card in cards))
    supply_available = sum(max(0, card.supply) for card in cards)
    tips: list[str] = []

    if branches["偵察"] == 0:
        tips.append("偵察カードがありません。未確認の相手に対応しにくくなります。")
    if branches["歩兵"] == 0:
        tips.append("戦線を確保する歩兵がありません。前列カードを追加しましょう。")
    if branches["機甲"] and supply_available < supply_need:
        tips.append("機甲に対して兵站が少なめです。補給カードを1枚追加すると安定します。")
    if len(cards) < 12:
        tips.append(f"デッキはあと{12 - len(cards)}枚追加できます。")
    if not tips:
        tips.append("6つの役割がそろっています。初めての対戦にも使いやすい構成です。")

    return {
        "count": len(cards),
        "cost": sum(card.cost for card in cards),
        "front": front,
        "vision": vision,
        "support": support,
        "supply_need": supply_need,
        "supply_available": supply_available,
        "branches": branches,
        "tips": tips,
    }
