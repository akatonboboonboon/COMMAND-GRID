"""Beginner-first lessons for the core COMMAND GRID rules.

The lessons deliberately teach one decision at a time.  They contain no UI
state, which keeps the wording and answer keys easy to test independently of
NiceGUI.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class BasicLesson:
    """One saved step in the guided core-rules course."""

    id: str
    title: str
    plain_goal: str
    explanation: str
    task: str
    kind: str
    choices: tuple[tuple[str, str], ...] = ()
    correct_choice: str = ""
    success_message: str = ""
    hint: str = "もう一度、青く強調された説明を確認してみましょう。"


BASIC_TUTORIAL_LESSONS: tuple[BasicLesson, ...] = (
    BasicLesson(
        id="objective",
        title="まず、勝ち方を知る",
        plain_goal="3つの戦線のうち、相手より多くを取るゲームです。",
        explanation=(
            "盤面には左・中央・右の3戦線があります。6ラウンドが終わったとき、"
            "最終的に相手より強い戦線を多く持つ側が勝ちです。まずは2戦線を取ることだけを目指します。"
        ),
        task="最初に目指すものを選んでください。",
        kind="choice",
        choices=(("all", "3戦線を全部取る"), ("two", "3戦線のうち2つを取る"), ("cards", "カードを全部使う")),
        correct_choice="two",
        success_message="その通りです。3つすべてを取る必要はありません。2戦線を取れば勝ちに近づきます。",
        hint="勝つために必要なのは、3戦線の『過半数』です。",
    ),
    BasicLesson(
        id="card",
        title="カードの仕事を一つだけ見る",
        plain_goal="最初は『制圧』があるカードを選べば、単独でも戦線を取りにいけます。",
        explanation=(
            "制圧は戦線に立つ土台、支援はその土台を助ける力、偵察は隠れた相手を見る力です。"
            "全部を暗記せず、今は『制圧が1以上なら場所を取りにいける』だけ覚えましょう。"
        ),
        task="1枚だけで戦線を取りにいきやすいカードを選んでください。",
        kind="card_choice",
        choices=(("infantry_1", "第1歩兵中隊"), ("artillery_1", "野戦砲兵中隊"), ("recon_2", "無人偵察隊")),
        correct_choice="infantry_1",
        success_message="正解です。第1歩兵中隊は制圧3を持つため、単独でも戦線の土台になります。",
        hint="カードの『制圧』を比べてください。支援だけでは戦線の土台になりません。",
    ),
    BasicLesson(
        id="deploy",
        title="1回の命令を出してみる",
        plain_goal="毎ラウンドの操作は『カード → 戦線 → 確定』の3回です。",
        explanation=(
            "手札からカードを1枚選び、左・中央・右のどこへ置くか決め、最後に命令を確定します。"
            "この練習では、第1歩兵中隊を中央戦線へ配置してください。"
        ),
        task="第1歩兵中隊を選ぶ → 中央戦線を選ぶ → 命令を確定、の順に操作してください。",
        kind="deploy",
        success_message="初めての命令を出せました。本番でも操作はまったく同じです。",
        hint="先に第1歩兵中隊、その次に中央戦線を選んでください。",
    ),
    BasicLesson(
        id="simultaneous",
        title="両者の配置先が同時に決まる",
        plain_goal="確定するまでは相手の配置先が分からず、カードの正体は配置後も未確認です。",
        explanation=(
            "あなたと相手は、それぞれカードと配置先を伏せて選びます。両方が確定すると配置先が同時に分かります。"
            "相手カードの名前と数値はまだ『未確認部隊』のままで、同じ戦線を偵察すると公開されます。"
            "相手の配置先を見てから自分だけ変えることはできないため、読み合いが生まれます。"
        ),
        task="両者の配置先を公開し、相手の未確認部隊がどの戦線に置かれたか確認してください。",
        kind="reveal",
        success_message="相手の未確認部隊は右戦線へ配置されました。正体はまだ分からず、後の偵察で公開できます。",
    ),
    BasicLesson(
        id="support",
        title="制圧がある同じ戦線へ、支援を重ねる",
        plain_goal="支援は、同じ戦線に制圧を持つ味方がいると戦線力へ加わります。",
        explanation=(
            "中央には第1歩兵中隊がいるので、すでに制圧の土台があります。"
            "ここへ支援の高いカードを重ねると、中央をさらに強くできます。配備したカードはその戦線に残ります。"
        ),
        task="中央の歩兵を一番大きく助けるカードを選んでください。",
        kind="card_choice",
        choices=(("artillery_1", "野戦砲兵中隊"), ("recon_1", "前方偵察班"), ("infantry_1", "第1歩兵中隊")),
        correct_choice="artillery_1",
        success_message=(
            "正解です。歩兵の制圧3と支援1に砲兵の支援4が加わります。"
            "ただし今は砲兵の補給が1不足するため、合計は3＋1＋4－1＝7です。補給は次章で試します。"
        ),
        hint="今回は、すでに制圧の土台があります。『支援』が最も高いカードを探してください。",
    ),
    BasicLesson(
        id="supply",
        title="重い部隊には補給を付ける",
        plain_goal="機甲や砲兵のマイナス補給は需要です。同じ戦線のプラス補給で満たします。",
        explanation=(
            "第4機甲中隊は補給を2必要とします。補給が足りないと不足分だけ戦線力が下がり、"
            "完全に満たすと機甲1枚につき戦線力が2上がります。"
        ),
        task="第4機甲中隊と同じ戦線へ置く相棒を選んでください。",
        kind="card_choice",
        choices=(("recon_2", "無人偵察隊"), ("logistics_1", "前線補給中隊"), ("artillery_1", "野戦砲兵中隊")),
        correct_choice="logistics_1",
        success_message=(
            "正解です。この練習では他に補給需要がないため、前線補給中隊の補給3で戦線の総需要2を満たし、"
            "補給不足を防いで機甲ボーナスも得られます。"
        ),
        hint="カードの補給がプラスになっている兵站カードを探してください。",
    ),
    BasicLesson(
        id="recon",
        title="見えない相手は、同じ戦線で偵察する",
        plain_goal="偵察は、同じ戦線にいる未確認の相手カードを公開します。",
        explanation=(
            "相手カードは、偵察されるまでは『未確認部隊』として隠れます。"
            "偵察値は戦線力そのものには加わりませんが、相手の正体を知って次の命令を決めやすくします。"
        ),
        task="右戦線に未確認部隊がいます。前方偵察班をどこへ置きますか？",
        kind="choice",
        choices=(("left", "左戦線"), ("center", "中央戦線"), ("right", "右戦線")),
        correct_choice="right",
        success_message="正解です。偵察したい相手と同じ右戦線へ置くと、未確認部隊を公開できます。",
        hint="偵察は盤面全体ではなく、『同じ戦線』の相手に働きます。",
    ),
    BasicLesson(
        id="rounds",
        title="これを6ラウンド繰り返す",
        plain_goal="1ラウンドに手札から1枚を使い、配備したカードは盤面に残ります。",
        explanation=(
            "1ラウンドごとに両者が1枚ずつ配備し、各戦線の結果と任務点を記録します。"
            "同じカードはその対戦中にもう一度使えないため、対戦には最低6枚のデッキが必要です。"
        ),
        task="6ラウンドの対戦に最低何枚のカードが必要でしょう？",
        kind="choice",
        choices=(("three", "3枚"), ("six", "6枚"), ("twelve", "必ず12枚")),
        correct_choice="six",
        success_message="正解です。最低6枚あれば対戦でき、デッキには最大12枚まで入れられます。",
        hint="1ラウンドに1枚を使い、全部で6ラウンドです。",
    ),
    BasicLesson(
        id="victory",
        title="最後に3戦線を数える",
        plain_goal="6ラウンド後の最終戦線力を比べ、取った戦線が多い側を決めます。",
        explanation=(
            "あなたが左と中央、相手が右を取っているなら、あなたの2対1で勝利です。"
            "取った戦線数が同じ場合だけ、各ラウンドで得た任務点の合計が決着に使われます。"
        ),
        task="あなたが左・中央、相手が右を取った場合、勝つのはどちらですか？",
        kind="choice",
        choices=(("player", "あなた"), ("opponent", "相手"), ("draw", "必ず引き分け")),
        correct_choice="player",
        success_message="その通りです。これで一試合の流れを理解できました。次は好きなカード1枚を練習できます。",
        hint="左と中央の2戦線を取っている側を数えてください。",
    ),
)


BASIC_LESSON_INDEX = {lesson.id: lesson for lesson in BASIC_TUTORIAL_LESSONS}


def get_basic_lesson(lesson_id: str) -> BasicLesson:
    """Return one core-rules lesson by its stable ID."""

    return BASIC_LESSON_INDEX[lesson_id]
