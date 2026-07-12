"""Card-by-card tutorial and official deck data for COMMAND GRID.

This module deliberately contains no NiceGUI or persistence code.  The UI can
therefore render the same lessons in several places, while the player-state
layer only has to remember a card ID and a stage number.

The lesson copy mirrors the rules implemented in :mod:`game_engine`:

* control is always counted;
* support is counted only when that player has control in the same lane;
* recon reveals hidden enemy cards in the same lane;
* unmet supply demand is subtracted from lane power; and
* every fully supplied armor card receives +2 lane power.

Cards do not have bespoke triggered abilities in the current game, so the
tutorials teach combinations and timing rather than promising extra effects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from game_data import CARDS, CARD_INDEX, UnitCard


@dataclass(frozen=True, slots=True)
class LaneExercise:
    """One selectable lane in a card tutorial's deployment exercise.

    The power values describe the board *before* the featured card is placed.
    ``situation`` carries information that cannot be expressed by power alone,
    such as unrevealed enemies, available supply, or inactive support.
    """

    id: str
    label: str
    situation: str
    player_power: int
    enemy_power: int


@dataclass(frozen=True, slots=True)
class TutorialStage:
    """One small, independently readable step in a card tutorial.

    ``choices`` is empty for reading/practice steps.  A stage with choices is
    a knowledge check; ``correct_choice`` contains the exact correct label.
    The final live exercise intentionally leaves the static choice fields
    empty because its nine turns are managed by the game UI.
    """

    id: str
    title: str
    summary: str
    explanation: str
    practice: str
    question: str = ""
    choices: tuple[str, ...] = ()
    correct_choice: str = ""
    success_message: str = ""
    exercise_lanes: tuple[LaneExercise, ...] = ()


@dataclass(frozen=True, slots=True)
class CardTutorial:
    """The complete staged lesson associated with one playable card."""

    card_id: str
    title: str
    intro: str
    stages: tuple[TutorialStage, ...]
    reward_deck_id: str


@dataclass(frozen=True, slots=True)
class OfficialDeck:
    """A twelve-slot official recipe awarded for a completed tutorial."""

    id: str
    featured_card_id: str
    name: str
    summary: str
    strategy: str
    card_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Guide:
    placement: str
    pairing: str
    caution: str
    question: str
    choices: tuple[str, str, str]
    correct_choice: str
    success_message: str


@dataclass(frozen=True, slots=True)
class _DeploymentExercise:
    question: str
    lanes: tuple[LaneExercise, LaneExercise, LaneExercise]
    correct_lane_id: str
    success_message: str


def _lane(
    lane_id: str,
    situation: str,
    player_power: int,
    enemy_power: int,
) -> LaneExercise:
    labels = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}
    return LaneExercise(lane_id, labels[lane_id], situation, player_power, enemy_power)


_GUIDES: dict[str, _Guide] = {
    "infantry_1": _Guide(
        "まだ味方の制圧力がない戦線に置けば、自身の制圧3で支援1まで有効になり、単独で戦線力4を作れます。",
        "後から砲兵など支援力の高いカードを同じ戦線へ加えると、歩兵の制圧を土台にして支援を有効化できます。",
        "すでに十分強い戦線へ重ねるだけでは、別の戦線を取る機会を失います。まず三つの戦線の強弱を見ます。",
        "味方カードがまだない戦線を安定させたいとき、最も素直な使い方はどれですか？",
        ("その戦線へ第1歩兵中隊を置く", "制圧0の支援カードだけを置く", "補給需要だけを増やす"),
        "その戦線へ第1歩兵中隊を置く",
        "正解です。制圧3と、自身で有効になる支援1が新しい戦線の土台になります。",
    ),
    "infantry_2": _Guide(
        "単独で制圧4を出せるため、味方がいない戦線や、あと少しで逆転できる戦線に向きます。",
        "野戦砲兵中隊や自走砲兵隊を同じ戦線に置くと、その大きな支援力を確実に有効化できます。",
        "支援・偵察・補給は持たないので、この一枚だけで情報や重い部隊の補給まで解決するわけではありません。",
        "支援力5の自走砲兵隊を生かす土台として必要なのはどれですか？",
        ("同じ戦線の制圧力", "別の戦線の偵察力", "相手側の補給力"),
        "同じ戦線の制圧力",
        "正解です。市街地警備隊の制圧4があれば、同じ戦線の味方支援が有効になります。",
    ),
    "infantry_3": _Guide(
        "制圧2と支援1を同時に持つので、空の戦線を単独で戦線力3にしたり、接戦へ少しずつ足したりできます。",
        "偵察カードと組み、情報を得ながら最低限の制圧を確保する使い方が扱いやすいです。",
        "カード名に『空中機動』とありますが、配置後に別の戦線へ移動する効果は現在のルールにはありません。",
        "このカードを配置した後、現在のルールでできることはどれですか？",
        ("置いた戦線に制圧2と支援1を加える", "毎ラウンド別の戦線へ移動する", "相手カードを手札へ戻す"),
        "置いた戦線に制圧2と支援1を加える",
        "正解です。名前ではなく、表示された制圧・支援の数値で働きを判断します。",
    ),
    "armor_1": _Guide(
        "ほかに補給需要がない場合、補給2以上がある戦線へ置くと、制圧5に機甲ボーナス2が加わり、このカードは戦線力7相当を出せます。",
        "前線補給中隊か整備支援隊は補給3を生みます。同じ戦線の味方全体の総需要が3以下なら、一枚で完全補給できます。",
        "補給が0なら需要不足2が引かれ、機甲ボーナスも得られないため、このカードの結果は戦線力3相当まで落ちます。",
        "第4機甲中隊を最大限に生かせる戦線はどれですか？",
        ("味方補給がその戦線の総需要以上ある戦線", "補給0の空の戦線", "相手だけが補給を持つ戦線"),
        "味方補給がその戦線の総需要以上ある戦線",
        "正解です。その戦線の総需要を完全に満たすと、不足が消えたうえで機甲ボーナス+2を得ます。",
    ),
    "armor_2": _Guide(
        "ほかに補給需要がない場合、補給1以上がある戦線なら、制圧4・支援1・機甲ボーナス2がすべて数えられ、戦線力7相当を作れます。",
        "補給3の兵站カードと組めば、このカードを動かしつつ、同じ戦線でもう一枚の需要を支える余地が残ります。",
        "補給なしでも制圧と支援はありますが、不足1が引かれ機甲ボーナスを失うため、本来の強さではありません。",
        "機械化歩兵隊が機甲ボーナスを得る条件はどれですか？",
        ("同じ戦線の味方補給が総需要以上", "別戦線に補給1がある", "相手の補給が総需要以上"),
        "同じ戦線の味方補給が総需要以上",
        "正解です。戦線内の総需要を完全に満たすことが機甲ボーナスの条件です。",
    ),
    "armor_3": _Guide(
        "ほかに補給需要がない場合、補給3以上を用意した戦線へ投入すると、制圧6と機甲ボーナス2で戦線力8相当を出せます。",
        "戦線内のすべての需要を足し、その総需要以上の補給を同じ戦線へそろえてから使います。",
        "補給0では不足3が引かれて戦線力3相当です。強い数値だけを見て空の戦線へ単独投入しないようにします。",
        "重装甲突破隊を含む戦線を完全補給する条件はどれですか？",
        ("同じ戦線の味方補給が総需要以上", "補給1だけ", "別の戦線に補給3"),
        "同じ戦線の味方補給が総需要以上",
        "正解です。同じ戦線の総需要をすべて満たせば、機甲ボーナスも有効になります。",
    ),
    "recon_1": _Guide(
        "相手の未確認カードがある戦線へ置くと、偵察3で新しいものから最大3枚を公開しつつ、制圧1も加えます。",
        "公開した情報を見て、次のラウンドに歩兵・機甲・支援のどれを足すか決めるのが基本です。",
        "未確認カードがいない戦線では偵察が空振りします。偵察は別の戦線には届きません。",
        "中央戦線に未確認の相手カードがあり、それを知りたい場合はどこへ置きますか？",
        ("中央戦線", "左戦線", "どこでも同じ"),
        "中央戦線",
        "正解です。偵察は配置したものと同じ戦線の未確認カードだけを公開します。",
    ),
    "recon_2": _Guide(
        "未確認カードが多い戦線へ置けば偵察4で最大4枚を公開できます。ただし制圧0なので単独の支援1は無効です。",
        "歩兵や工兵がいる戦線へ加えると、偵察に加えて支援1も戦線力へ数えられます。",
        "空の戦線へ単独配置すると情報は得られても戦線力は0です。今すぐ戦線を取るカードではありません。",
        "無人偵察隊の支援1を有効にする条件はどれですか？",
        ("同じ戦線に味方の制圧力がある", "別戦線に補給がある", "相手の制圧が0である"),
        "同じ戦線に味方の制圧力がある",
        "正解です。支援は同じ戦線の味方制圧を土台にして初めて戦線力へ入ります。",
    ),
    "recon_3": _Guide(
        "相手の未確認カードが残る戦線へ置き、偵察3で最大3枚を公開します。制圧0なので単独では支援1が働きません。",
        "制圧を持つ味方と同じ戦線に配置し、情報を取りながら支援1も有効にする形が安定します。",
        "『電子』という名前による妨害や無効化はありません。現在の効果は偵察3と条件付きの支援1です。",
        "電子偵察班が現在のルールで行うことはどれですか？",
        ("同じ戦線の未確認カードを最大3枚公開する", "相手の命令を取り消す", "全戦線のカードを公開する"),
        "同じ戦線の未確認カードを最大3枚公開する",
        "正解です。効果範囲は同じ戦線で、公開できる上限は偵察値3です。",
    ),
    "artillery_1": _Guide(
        "味方の制圧があり、味方補給がその戦線の総需要以上ある場所へ置くと、支援4を不足なしで戦線力へ加えられます。",
        "歩兵か工兵で制圧の土台を作り、兵站で戦線全体の総需要を満たしてから砲兵を重ねると安定します。",
        "単独では制圧0なので支援4が無効です。さらに補給0なら不足1も発生し、戦線を取れません。",
        "野戦砲兵中隊の支援4を有効にするため、同じ戦線に最低限必要なのはどれですか？",
        ("味方の制圧力", "相手の偵察力", "別戦線の支援力"),
        "味方の制圧力",
        "正解です。加えて同じ戦線の総需要以上の補給を用意すれば、不足による戦線力低下も防げます。",
    ),
    "artillery_2": _Guide(
        "味方の制圧があり、味方補給がその戦線の総需要以上ある場所へ置けば、支援5を不足なしで大きな上積みにできます。",
        "市街地警備隊の制圧4と、補給3を持つ兵站カードを同じ戦線へそろえる組み合わせが分かりやすいです。",
        "制圧がなければ支援5は数えられず、補給不足なら不足分も引かれます。単独投入は避けます。",
        "自走砲兵隊を置く前に確認する二つの条件はどれですか？",
        ("同じ戦線の味方制圧と総需要以上の補給", "別戦線の偵察と補給", "相手の支援と機甲"),
        "同じ戦線の味方制圧と総需要以上の補給",
        "正解です。制圧が支援を有効にし、総需要以上の補給が不足をなくします。",
    ),
    "artillery_3": _Guide(
        "制圧の土台があり、味方補給がその戦線の総需要以上ある場所へ置くと、支援6を不足なしで加えられます。",
        "制圧カードと、戦線全体の総需要以上を生む兵站カードを先にそろえ、勝負を決めたい戦線へ最後の上積みとして使います。",
        "補給0では不足3が発生し、制圧がなければ支援6も無効です。準備なしでは強みをほぼ出せません。",
        "ロケット支援隊の支援6を最大限に使える準備はどれですか？",
        ("同じ戦線に味方制圧と総需要以上の補給", "空の戦線へ単独配置", "別戦線だけに補給4"),
        "同じ戦線に味方制圧と総需要以上の補給",
        "正解です。支援を有効にする制圧と、戦線全体の総需要を満たす補給の両方が必要です。",
    ),
    "engineer_1": _Guide(
        "制圧2と支援2を持ち、自身の制圧で支援を有効にするため、単独で戦線力4を作れます。",
        "空の戦線の土台にも、砲兵を後から置くための制圧役にも使える、柔軟な一枚です。",
        "特別な防御・建設効果はまだありません。現在の働きは表示どおり制圧2と支援2です。",
        "第2工兵中隊を空の戦線へ置いたときの戦線力への基本加算はいくつですか？",
        ("4", "2", "0"),
        "4",
        "正解です。制圧2があるため、自身の支援2も有効になり、合計4です。",
    ),
    "engineer_2": _Guide(
        "制圧1が自分の支援2を有効にするため、空の戦線でも単独で戦線力3を出せます。",
        "制圧0の偵察や兵站輸送と同じ戦線に置けば、それらの支援を有効にする小さな土台にもなります。",
        "橋を架けて別戦線へ移動させる効果はありません。カード名と実装された数値を分けて考えます。",
        "架橋工兵隊が単独でも支援2を有効にできる理由はどれですか？",
        ("自身が制圧1を持つから", "偵察4を持つから", "補給需要があるから"),
        "自身が制圧1を持つから",
        "正解です。少量でも制圧があれば、同じ戦線の味方支援は有効になります。",
    ),
    "engineer_3": _Guide(
        "制圧1と支援3を持つため、自身だけで支援を有効にし、単独で戦線力4を加えます。",
        "制圧の高い歩兵と重ねて接戦を押し切るほか、制圧0の支援カードを生かす土台にもなります。",
        "陣地による永続防御や相手の弱体化はありません。毎回の戦線力計算では表示数値だけを使います。",
        "陣地構築隊が現在のルールで加える数値はどれですか？",
        ("制圧1と支援3", "制圧3と偵察1", "補給3だけ"),
        "制圧1と支援3",
        "正解です。自身の制圧1により支援3も有効になり、合計4を作れます。",
    ),
    "logistics_1": _Guide(
        "補給需要のある機甲・砲兵と同じ戦線へ置きます。補給3に加え、制圧1と支援1で単独でも戦線力2です。",
        "需要3以下なら一枚で不足を解消できます。機甲の総需要を満たせば、機甲一枚ごとに+2も得られます。",
        "補給は別の戦線へ送れません。需要のあるカードと異なる戦線に置くと、その需要を満たせません。",
        "左戦線の第4機甲中隊へ補給を届けたい場合、前線補給中隊をどこへ置きますか？",
        ("左戦線", "中央戦線", "どの戦線でも届く"),
        "左戦線",
        "正解です。補給は同じ戦線の需要だけに使われます。補給3なら需要2を満たせます。",
    ),
    "logistics_2": _Guide(
        "補給3、制圧1、支援2を持つため、重いカードを支えながら単独でも戦線力3を作れます。",
        "機甲や砲兵の需要を同じ戦線で満たしつつ、自身の制圧1で支援2も有効にできるのが強みです。",
        "補給3を超える総需要を一枚で満たすことはできません。戦線内の需要を足してから配置します。",
        "同じ戦線の補給需要が合計4あるとき、整備支援隊一枚だけではどうなりますか？",
        ("補給が1不足する", "完全補給になる", "補給が別戦線から自動で来る"),
        "補給が1不足する",
        "正解です。供給3に対して需要4なので、不足1が戦線力から引かれます。",
    ),
    "logistics_3": _Guide(
        "補給4で複数の需要をまとめて満たせます。制圧0なので、単独では支援2が無効で戦線力は0です。",
        "味方の制圧カードと、合計需要4までの機甲・砲兵が集まる戦線へ置くと、補給と支援を同時に生かせます。",
        "補給4は同じ戦線だけに作用します。また制圧0なので、支援2を数えるには別の味方制圧が必要です。",
        "戦域輸送隊の支援2を有効にしながら補給も使う配置はどれですか？",
        ("味方制圧と補給需要がある同じ戦線", "誰もいない別戦線", "相手だけが制圧する戦線"),
        "味方制圧と補給需要がある同じ戦線",
        "正解です。同じ戦線の味方制圧が支援2を有効にし、補給4が味方需要を満たします。",
    ),
}


_EXERCISES: dict[str, _DeploymentExercise] = {
    "infantry_1": _DeploymentExercise(
        "第1歩兵中隊で新しい足場を作り、今すぐ逆転できる戦線を選んでください。",
        (
            _lane("left", "味方はまだいません。敵の小部隊だけが確保しています。", 0, 3),
            _lane("center", "歩兵と工兵で十分に確保済みです。", 8, 2),
            _lane("right", "味方の偵察班だけで、敵主力との差が大きい場所です。", 1, 9),
        ),
        "left",
        "左戦線が正解です。単独戦線力4を加えると0対3から4対3となり、新しい戦線を一枚で確保できます。",
    ),
    "infantry_2": _DeploymentExercise(
        "市街地警備隊で、待機中の支援を生かして最も大きく逆転できる戦線を選んでください。",
        (
            _lane("left", "小差で負けていますが、ほかの味方支援はいません。", 2, 3),
            _lane("center", "支援5の自走砲兵隊がいますが、制圧0のため支援が無効です。", 0, 7),
            _lane("right", "すでに歩兵だけで安定して確保しています。", 7, 2),
        ),
        "center",
        "中央戦線が正解です。制圧4が土台となり、待機していた支援5も有効になるため、戦線力9で逆転できます。",
    ),
    "infantry_3": _DeploymentExercise(
        "空中機動歩兵班で、制圧のない偵察部隊を戦線力へ変えられる場所を選んでください。",
        (
            _lane("left", "味方歩兵がすでに余裕をもって確保しています。", 6, 1),
            _lane("center", "敵主力が集中し、一枚では届かない差があります。", 1, 8),
            _lane("right", "無人偵察隊の支援1がありますが、味方制圧は0です。", 0, 3),
        ),
        "right",
        "右戦線が正解です。自身の制圧2と支援1に、偵察隊の支援1も有効となり、戦線力4で0対3を逆転できます。",
    ),
    "armor_1": _DeploymentExercise(
        "第4機甲中隊を完全補給し、機甲ボーナスまで得られる戦線を選んでください。",
        (
            _lane("left", "補給2が余っており、味方の軽部隊が接戦を支えています。", 2, 8),
            _lane("center", "補給は0です。機甲を置くと需要2が不足します。", 3, 5),
            _lane("right", "補給はありますが、すでに大差で確保済みです。", 9, 1),
        ),
        "left",
        "左戦線が正解です。需要2を満たすため、制圧5と機甲ボーナス2が加わり、2対8から9対8へ逆転します。",
    ),
    "armor_2": _DeploymentExercise(
        "その戦線の総需要を確認し、機械化歩兵隊の需要1を満たしながら接戦を押し切れる場所を選んでください。",
        (
            _lane("left", "接戦ですが補給0で、配置すると機甲ボーナスを失います。", 4, 6),
            _lane("center", "補給1が余っており、味方の土台も残っています。", 3, 9),
            _lane("right", "すでに二枚の歩兵で確保しています。", 8, 2),
        ),
        "center",
        "中央戦線が正解です。制圧4・支援1・機甲ボーナス2の計7が働き、3対9から10対9へ逆転できます。",
    ),
    "armor_3": _DeploymentExercise(
        "重装甲突破隊の需要3を完全に満たし、その突破力が決着になる戦線を選んでください。",
        (
            _lane("left", "すでに砲兵支援で大きく勝っています。", 10, 3),
            _lane("center", "補給0で、敵との差も大きい場所です。", 1, 8),
            _lane("right", "補給3が余っており、味方の小部隊が踏みとどまっています。", 1, 8),
        ),
        "right",
        "右戦線が正解です。需要3を満たして制圧6と機甲ボーナス2を得るため、1対8から9対8へ逆転できます。",
    ),
    "recon_1": _DeploymentExercise(
        "前方偵察班で、次の命令に最も多くの情報を持ち帰れる戦線を選んでください。",
        (
            _lane("left", "相手の未確認部隊が3枚あり、味方は接戦中です。", 2, 4),
            _lane("center", "相手カードはすべて確認済みです。", 5, 5),
            _lane("right", "未確認部隊は1枚だけで、すでに確保しています。", 7, 2),
        ),
        "left",
        "左戦線が正解です。偵察3で未確認部隊を最大3枚公開しつつ、制圧1も接戦へ加えられます。",
    ),
    "recon_2": _DeploymentExercise(
        "無人偵察隊で四枚を偵察し、支援1も無駄にしない戦線を選んでください。",
        (
            _lane("left", "未確認部隊はなく、すでに味方が確保しています。", 8, 3),
            _lane("center", "未確認部隊が4枚あり、味方歩兵の制圧4があります。", 4, 7),
            _lane("right", "未確認部隊は1枚ですが、味方制圧は0です。", 0, 2),
        ),
        "center",
        "中央戦線が正解です。最大4枚を公開でき、同じ戦線の制圧4によって自身の支援1も戦線力へ加わります。",
    ),
    "recon_3": _DeploymentExercise(
        "電子偵察班で、情報と支援の両方を有効にできる戦線を選んでください。",
        (
            _lane("left", "相手はすべて確認済みで、情報を増やせません。", 4, 4),
            _lane("center", "未確認部隊が2枚いますが、味方制圧は0です。", 0, 3),
            _lane("right", "未確認部隊が3枚おり、味方工兵の制圧2があります。", 2, 5),
        ),
        "right",
        "右戦線が正解です。偵察3で三枚を公開し、工兵の制圧を土台に支援1も有効化できます。",
    ),
    "artillery_1": _DeploymentExercise(
        "野戦砲兵中隊の支援4と需要1を、どちらも正しく処理できる戦線を選んでください。",
        (
            _lane("left", "味方歩兵の制圧3と、余っている補給1があります。", 4, 7),
            _lane("center", "補給1はありますが、味方制圧は0です。", 0, 3),
            _lane("right", "制圧はありますが補給0で、すでに大差で確保済みです。", 9, 2),
        ),
        "left",
        "左戦線が正解です。歩兵の制圧で支援4が有効になり、補給1で需要も満たすため、4対7から8対7へ逆転します。",
    ),
    "artillery_2": _DeploymentExercise(
        "自走砲兵隊の支援5を不足なしで加え、中央の接戦を決める配置を選んでください。",
        (
            _lane("left", "補給0で味方制圧もなく、支援を生かせません。", 0, 2),
            _lane("center", "味方制圧4と、余っている補給2があります。", 5, 9),
            _lane("right", "補給2はありますが、すでに十分な差で確保しています。", 10, 3),
        ),
        "center",
        "中央戦線が正解です。制圧の土台と補給2がそろっているため支援5をそのまま加え、10対9にできます。",
    ),
    "artillery_3": _DeploymentExercise(
        "ロケット支援隊を、制圧・補給3・逆転余地の三条件がそろう戦線へ配備してください。",
        (
            _lane("left", "制圧はありますが、補給0で需要3が不足します。", 4, 6),
            _lane("center", "補給3はありますが、味方制圧0で支援が無効です。", 0, 4),
            _lane("right", "味方制圧2と補給3があり、あと少しで逆転できます。", 3, 8),
        ),
        "right",
        "右戦線が正解です。制圧で支援6を有効にし、補給3で不足も防ぐため、3対8から9対8へ逆転できます。",
    ),
    "engineer_1": _DeploymentExercise(
        "第2工兵中隊一枚で、新しい戦線を確保できる配置先を選んでください。",
        (
            _lane("left", "味方はまだおらず、敵の戦線力は3だけです。", 0, 3),
            _lane("center", "歩兵と砲兵ですでに十分確保しています。", 9, 2),
            _lane("right", "敵主力との差が大きく、一枚では届きません。", 1, 9),
        ),
        "left",
        "左戦線が正解です。自身の制圧2が支援2を有効にするため、単独戦線力4で0対3を逆転できます。",
    ),
    "engineer_2": _DeploymentExercise(
        "架橋工兵隊で、制圧のない味方支援までまとめて有効にできる戦線を選んでください。",
        (
            _lane("left", "歩兵がすでに戦線を安定して確保しています。", 7, 2),
            _lane("center", "偵察隊の支援1がありますが、味方制圧は0です。", 0, 3),
            _lane("right", "敵主力との差が大きく、支援する味方もいません。", 1, 8),
        ),
        "center",
        "中央戦線が正解です。自身の制圧1・支援2に偵察隊の支援1も加わり、戦線力4で逆転できます。",
    ),
    "engineer_3": _DeploymentExercise(
        "陣地構築隊で、止まっている支援を起動して接戦を取れる戦線を選んでください。",
        (
            _lane("left", "すでに機甲で大きく勝っています。", 9, 3),
            _lane("center", "味方支援はなく、敵との差が一枚では届きません。", 0, 8),
            _lane("right", "無人偵察隊の支援1がありますが、味方制圧は0です。", 0, 4),
        ),
        "right",
        "右戦線が正解です。制圧1と自身の支援3に偵察隊の支援1も加わり、戦線力5で0対4を逆転できます。",
    ),
    "logistics_1": _DeploymentExercise(
        "前線補給中隊で、補給不足と機甲ボーナス喪失を同時に解消できる戦線を選んでください。",
        (
            _lane("left", "第4機甲中隊が需要2を満たせず、補給不足のまま戦っています。", 3, 8),
            _lane("center", "補給需要のない歩兵だけが接戦中です。", 4, 5),
            _lane("right", "需要はなく、すでに砲兵支援で確保しています。", 9, 3),
        ),
        "left",
        "左戦線が正解です。補給3で需要2を満たし、不足2を消して機甲ボーナス2を戻し、自身の戦線力2も加えて逆転できます。",
    ),
    "logistics_2": _DeploymentExercise(
        "整備支援隊で、自走砲の補給不足を消しながら支援2も加えられる戦線を選んでください。",
        (
            _lane("left", "補給需要はなく、味方もいない空の戦線です。", 0, 2),
            _lane("center", "歩兵と自走砲がいますが、需要2を満たせず不足しています。", 7, 11),
            _lane("right", "補給需要はなく、すでに歩兵で確保済みです。", 8, 3),
        ),
        "center",
        "中央戦線が正解です。補給3で不足2を解消し、歩兵の制圧により自身の支援2も有効となって、7対11から12対11へ逆転できます。",
    ),
    "logistics_3": _DeploymentExercise(
        "戦域輸送隊の補給4を、一番多くの需要と支援へ変えられる戦線を選んでください。",
        (
            _lane("left", "補給需要は1だけで、味方制圧は0です。", 0, 2),
            _lane("center", "需要はなく、すでに歩兵が確保しています。", 7, 4),
            _lane("right", "味方制圧があり、機甲と砲兵の総需要4がすべて不足しています。", 6, 13),
        ),
        "right",
        "右戦線が正解です。総需要4を満たして不足を消し、機甲ボーナスと自身の支援2まで有効にするため、逆転できます。",
    ),
}


_DECK_SPECS: dict[str, tuple[str, str, str, tuple[str, ...]]] = {
    "infantry_1": (
        "公式・基本三戦線",
        "六つの役割を二枚ずつ入れた、最初の基準になる構成です。",
        "歩兵か工兵で制圧を作り、偵察で相手を確認し、兵站と重い部隊を同じ戦線へそろえます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "infantry_2": (
        "公式・制圧の壁",
        "歩兵を三枚に増やし、支援カードを確実に働かせる構成です。",
        "二つ以上の戦線に歩兵を置き、砲兵を重ねる戦線と機甲を補給する戦線を分けます。",
        ("infantry_1", "infantry_2", "infantry_3", "armor_1", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "infantry_3": (
        "公式・機動偵察線",
        "軽い制圧と偵察を組み、相手を見てから戦線を伸ばす構成です。",
        "空中機動歩兵班を偵察の土台にし、判明した戦線へ機甲か砲兵を追加します。",
        ("infantry_1", "infantry_2", "infantry_3", "armor_2", "recon_1", "recon_2", "recon_3", "artillery_1", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "armor_1": (
        "公式・機甲入門",
        "補給3の兵站二枚で、二種類の機甲を扱う基本構成です。",
        "兵站と機甲を同じ戦線へ重ね、別戦線は歩兵・工兵・砲兵で確保します。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "armor_2": (
        "公式・機械化混成",
        "三枚の機甲と三枚の兵站を入れ、完全補給を狙いやすくした構成です。",
        "先に兵站を置いた戦線へ機甲を追加し、総需要が補給を超えないようにします。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "armor_3", "recon_1", "artillery_1", "engineer_1", "engineer_2", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "armor_3": (
        "公式・重装甲突破",
        "重装甲突破隊を補給4と補助兵站で支える、集中型の構成です。",
        "重装甲を出す戦線の需要を先に計算し、完全補給できるときだけ勝負を仕掛けます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "armor_3", "recon_1", "artillery_1", "engineer_1", "logistics_1", "logistics_2", "logistics_3", "engineer_2"),
    ),
    "recon_1": (
        "公式・前方観測",
        "偵察で危険な戦線を見つけ、標準部隊で対応する基本構成です。",
        "未確認カードの多い戦線を先に偵察し、次の手を制圧・支援・補給から選びます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "recon_2": (
        "公式・広域偵察",
        "偵察三枚で未確認カードを早く減らし、判断しやすくする構成です。",
        "偵察は制圧カードと同じ戦線へ置き、情報と有効な支援を同時に得ます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "recon_3", "artillery_1", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "recon_3": (
        "公式・電子索敵網",
        "三種類の偵察を制圧の土台と組み、相手の配置を継続して確認する構成です。",
        "偵察だけを同じ戦線へ重ねず、歩兵・工兵の制圧がある場所へ分けて置きます。",
        ("infantry_1", "infantry_2", "armor_1", "recon_1", "recon_2", "recon_3", "artillery_1", "engineer_1", "engineer_2", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "artillery_1": (
        "公式・歩砲協同",
        "歩兵の制圧を土台に、二種類の砲兵で戦線力を伸ばす基本構成です。",
        "砲兵を単独で置かず、制圧と必要量の補給が同じ戦線にあることを確認します。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "artillery_2": (
        "公式・自走火力群",
        "砲兵三枚と兵站三枚を組み、補給不足を抑えて大きな支援を狙う構成です。",
        "制圧役を先に置き、砲兵と兵站を一つずつ同じ戦線へ追加します。",
        ("infantry_1", "infantry_2", "armor_1", "recon_1", "artillery_1", "artillery_2", "artillery_3", "engineer_1", "engineer_2", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "artillery_3": (
        "公式・集中火力",
        "ロケット支援隊の需要3を満たし、支援6を決定力にする構成です。",
        "制圧と、その戦線の総需要以上の補給がそろった場所にだけロケット支援隊を置きます。",
        ("infantry_1", "infantry_2", "armor_1", "recon_1", "artillery_1", "artillery_2", "artillery_3", "engineer_1", "logistics_1", "logistics_2", "logistics_3", "engineer_3"),
    ),
    "engineer_1": (
        "公式・工兵基幹線",
        "工兵を制圧と支援の両方に使い、どの戦線にも対応しやすい基本構成です。",
        "空の戦線は工兵で始め、相手の出方に合わせて偵察・砲兵・機甲を重ねます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "engineer_2": (
        "公式・渡河支援線",
        "工兵三枚で小さな制圧の土台を増やし、偵察と兵站の支援を有効にする構成です。",
        "制圧0のカードを置く予定の戦線へ、先に工兵を配備します。",
        ("infantry_1", "infantry_2", "armor_1", "recon_1", "recon_2", "artillery_1", "engineer_1", "engineer_2", "engineer_3", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "engineer_3": (
        "公式・陣地支援群",
        "工兵の自己完結した制圧と支援で、複数戦線へ安定して戦線力を置く構成です。",
        "工兵で二戦線の土台を作り、残りの一戦線へ機甲か砲兵を集中します。",
        ("infantry_1", "infantry_2", "armor_1", "recon_1", "recon_2", "artillery_1", "engineer_1", "engineer_2", "engineer_3", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "logistics_1": (
        "公式・前線補給",
        "補給3を二戦線へ配り、機甲と砲兵を一枚ずつ安全に使う基本構成です。",
        "重いカードを置く戦線と同じ場所へ兵站を置き、総需要を毎回確認します。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "recon_2", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2"),
    ),
    "logistics_2": (
        "公式・整備循環",
        "三種類の兵站で、機甲と砲兵の需要へ柔軟に対応する構成です。",
        "補給3は中程度の需要へ、補給4は複数の需要が集まる戦線へ使い分けます。",
        ("infantry_1", "infantry_2", "armor_1", "armor_2", "recon_1", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2", "logistics_3"),
    ),
    "logistics_3": (
        "公式・戦域輸送網",
        "補給4を中心に、需要の大きい機甲と砲兵を一つの戦線で支える構成です。",
        "制圧役を必ず同じ戦線へ置き、戦域輸送隊の支援2も有効にします。",
        ("infantry_1", "infantry_2", "armor_1", "armor_3", "recon_1", "artillery_1", "artillery_2", "engineer_1", "engineer_2", "logistics_1", "logistics_2", "logistics_3"),
    ),
}


def _stat_summary(card: UnitCard) -> str:
    supply = f"補給+{card.supply}" if card.supply >= 0 else f"補給需要{abs(card.supply)}"
    return (
        f"制圧{card.control} / 支援{card.support} / "
        f"偵察{card.recon} / {supply}"
    )


def _number_explanation(card: UnitCard) -> str:
    base = card.control + (card.support if card.control > 0 else 0)
    if card.branch == "機甲":
        demand = abs(card.supply)
        unsupported = max(0, base - demand)
        supplied = base + 2
        return (
            f"自身の制圧と有効な支援は合計{base}です。補給0なら需要不足{demand}が引かれて"
            f"戦線力{unsupported}相当、同じ戦線の総需要を全部満たせば不足が消え、機甲ボーナス+2で"
            f"戦線力{supplied}相当になります。"
        )
    if card.supply < 0:
        demand = abs(card.supply)
        if card.control == 0:
            return (
                f"補給需要は{demand}です。自身は制圧0なので単独では支援{card.support}が無効です。"
                "同じ戦線に味方の制圧があると支援が有効になり、補給不足分だけ戦線力から引かれます。"
            )
        return (
            f"自身の制圧と有効な支援は合計{base}です。補給需要{demand}を同じ戦線で満たさない場合、"
            "不足分だけ戦線力から引かれます。"
        )
    if card.supply > 0:
        if card.control == 0:
            return (
                f"同じ戦線へ補給{card.supply}を加えます。制圧0なので単独では支援{card.support}が無効ですが、"
                "味方の制圧があればその支援も戦線力へ加わります。"
            )
        return (
            f"補給{card.supply}を同じ戦線の需要へ使えます。自身の制圧{card.control}により支援"
            f"{card.support}も有効なので、単独の戦線力は{base}です。"
        )
    if card.recon > 0:
        support_note = (
            f"制圧{card.control}があるため、単独の戦線力は{base}です。"
            if card.control > 0
            else f"制圧0なので、単独では支援{card.support}は戦線力へ入りません。"
        )
        return (
            f"偵察{card.recon}は同じ戦線の未確認カードを新しいものから最大{card.recon}枚公開します。"
            + support_note
        )
    return (
        f"制圧{card.control}があるため、自身の支援{card.support}も有効です。"
        f"単独では戦線力{base}を加えます。"
    )


def _build_tutorial(card: UnitCard) -> CardTutorial:
    guide = _GUIDES[card.id]
    stages = (
        TutorialStage(
            "role",
            "1. このカードの役割",
            card.tagline,
            f"{card.name}は{card.branch}カードです。カードの名前を暗記するより、まず数値を読みます。{card.game_text}",
            f"カード詳細で「{_stat_summary(card)}」の四項目を順番に確認してください。",
        ),
        TutorialStage(
            "numbers",
            "2. 数字がどう働くか",
            _stat_summary(card),
            _number_explanation(card),
            "制圧・有効な支援・機甲ボーナスを足し、最後に補給不足を引く順番で計算してみましょう。戦線力は0未満にはなりません。",
        ),
        TutorialStage(
            "placement",
            "3. 置く戦線を選ぶ",
            "三つの戦線を見て、このカードが今必要な場所を選びます。",
            guide.placement,
            f"実戦では「{card.name}を置いた後、その戦線で何が有効になるか」を声に出して確認します。",
        ),
        TutorialStage(
            "combination",
            "4. 組み合わせと注意",
            "一枚の強さではなく、同じ戦線にいる味方との合計で考えます。",
            f"おすすめ: {guide.pairing}\n注意: {guide.caution}",
            "おすすめの相方と同じ戦線へ置く場面を一つ想像し、補給需要がある場合は合計需要も確認してください。",
        ),
        TutorialStage(
            "exercise",
            "5. 9ターン実戦演習",
            "両軍とも配備0枚から始め、9ターンで2戦線の確保を目指します。",
            (
                f"履修中の{card.name}は演習中に必ず手札へ入ります。"
                "通常の対戦と同じ手順で一手ずつ配備し、カードの役割を盤面で確かめます。"
            ),
            (
                f"{card.name}を少なくとも1回使用し、9ターン終了時に左・中央・右のうち"
                "2戦線以上を確保してください。"
            ),
        ),
    )
    return CardTutorial(
        card_id=card.id,
        title=f"{card.name} 基礎訓練",
        intro=f"{card.name}の数字と組み合わせを学び、最後に9ターンの実戦演習を行います。",
        stages=stages,
        reward_deck_id=card.id,
    )


def _build_official_deck(card: UnitCard) -> OfficialDeck:
    name, summary, strategy, card_ids = _DECK_SPECS[card.id]
    return OfficialDeck(
        id=card.id,
        featured_card_id=card.id,
        name=name,
        summary=summary,
        strategy=strategy,
        card_ids=card_ids,
    )


CARD_TUTORIALS: tuple[CardTutorial, ...] = tuple(_build_tutorial(card) for card in CARDS)
TUTORIAL_INDEX: dict[str, CardTutorial] = {
    tutorial.card_id: tutorial for tutorial in CARD_TUTORIALS
}

OFFICIAL_DECKS: tuple[OfficialDeck, ...] = tuple(_build_official_deck(card) for card in CARDS)
OFFICIAL_DECK_INDEX: dict[str, OfficialDeck] = {deck.id: deck for deck in OFFICIAL_DECKS}


def get_tutorial(card_id: str) -> CardTutorial:
    """Return a tutorial by card ID, raising ``KeyError`` for an invalid ID."""

    return TUTORIAL_INDEX[card_id]


def get_official_deck(deck_id_or_card_id: str) -> OfficialDeck:
    """Return the official deck awarded by the specified card tutorial.

    Deck IDs intentionally equal their featured card IDs, so either concept
    can be passed without a translation table in the persistence layer.
    """

    return OFFICIAL_DECK_INDEX[deck_id_or_card_id]


def _coerce_deck(deck: OfficialDeck | str) -> OfficialDeck:
    return get_official_deck(deck) if isinstance(deck, str) else deck


def deck_missing_card_ids(
    deck: OfficialDeck | str,
    owned_card_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return unowned recipe card IDs in their original twelve-slot order."""

    recipe = _coerce_deck(deck)
    owned = set(owned_card_ids)
    return tuple(card_id for card_id in recipe.card_ids if card_id not in owned)


def deck_missing_cards(
    deck: OfficialDeck | str,
    owned_card_ids: Iterable[str],
) -> tuple[UnitCard, ...]:
    """Return unowned card objects in recipe order for name-rich UI copy."""

    return tuple(CARD_INDEX[card_id] for card_id in deck_missing_card_ids(deck, owned_card_ids))


def deck_owned_cards_in_order(
    deck: OfficialDeck | str,
    owned_card_ids: Iterable[str],
) -> tuple[str, ...]:
    """Return only owned recipe IDs, preserving their official slot order.

    Missing positions are intentionally *not* replaced with a sentinel here:
    the player deck remains a valid sequence of real card IDs.  A UI that
    displays all twelve slots should iterate over ``OfficialDeck.card_ids``
    and mark IDs absent from ``owned_card_ids`` as empty placeholders.
    """

    recipe = _coerce_deck(deck)
    owned = set(owned_card_ids)
    return tuple(card_id for card_id in recipe.card_ids if card_id in owned)


def _validate_catalog() -> None:
    expected = set(CARD_INDEX)
    if set(_GUIDES) != expected:
        raise ValueError("Every card must have exactly one tutorial guide")
    if set(_DECK_SPECS) != expected:
        raise ValueError("Every card must have exactly one official deck")
    if len(TUTORIAL_INDEX) != len(CARD_TUTORIALS):
        raise ValueError("Tutorial card IDs must be unique")
    if len(OFFICIAL_DECK_INDEX) != len(OFFICIAL_DECKS):
        raise ValueError("Official deck IDs must be unique")
    for tutorial in CARD_TUTORIALS:
        if len(tutorial.stages) < 5:
            raise ValueError(f"Tutorial {tutorial.card_id} is not sufficiently staged")
        exercise = tutorial.stages[-1]
        if exercise.id != "exercise":
            raise ValueError(f"Tutorial {tutorial.card_id} needs a final live exercise")
        if (
            exercise.question
            or exercise.choices
            or exercise.correct_choice
            or exercise.success_message
            or exercise.exercise_lanes
        ):
            raise ValueError(f"Tutorial {tutorial.card_id} embeds obsolete exercise choices")
        exercise_copy = " ".join(
            (exercise.summary, exercise.explanation, exercise.practice)
        )
        for required in (
            "0枚",
            "9ターン",
            "2戦線",
            "少なくとも1回使用",
            CARD_INDEX[tutorial.card_id].name,
        ):
            if required not in exercise_copy:
                raise ValueError(
                    f"Tutorial {tutorial.card_id} exercise is missing {required}"
                )
    for deck in OFFICIAL_DECKS:
        if len(deck.card_ids) != 12 or len(set(deck.card_ids)) != 12:
            raise ValueError(f"Official deck {deck.id} must contain 12 unique cards")
        if deck.featured_card_id not in deck.card_ids:
            raise ValueError(f"Official deck {deck.id} must contain its featured card")
        if not set(deck.card_ids).issubset(expected):
            raise ValueError(f"Official deck {deck.id} contains an unknown card")


_validate_catalog()


__all__ = [
    "CARD_TUTORIALS",
    "OFFICIAL_DECKS",
    "OFFICIAL_DECK_INDEX",
    "TUTORIAL_INDEX",
    "CardTutorial",
    "LaneExercise",
    "OfficialDeck",
    "TutorialStage",
    "deck_missing_card_ids",
    "deck_missing_cards",
    "deck_owned_cards_in_order",
    "get_official_deck",
    "get_tutorial",
]
