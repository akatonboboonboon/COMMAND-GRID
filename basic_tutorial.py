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
            "盤面には左・中央・右の3戦線があります。9ラウンドが終わったとき、"
            "最終的に相手より強い戦線を多く持つ側が勝ちです。まずは2戦線を取ることだけを目指します。"
        ),
        task="最終戦線力は左6対4、中央5対3、右2対7です。結果を選んでください。",
        kind="choice",
        choices=(
            ("all", "敵軍が二戦線を確保する"),
            ("two", "自軍が二戦線を確保する"),
            ("cards", "両軍が一戦線ずつ確保する"),
        ),
        correct_choice="two",
        success_message="正解です。自軍は左と中央、敵軍は右を確保するため、自軍の2戦線対1戦線です。",
        hint="各戦線の二つの数値を比べ、どちらが高いかを一つずつ数えてください。",
    ),
    BasicLesson(
        id="card",
        title="カードの仕事を一つだけ見る",
        plain_goal="最初は『制圧』があるカードを選べば、単独でも戦線を取りにいけます。",
        explanation=(
            "制圧は戦線に立つ土台、支援はその土台を助ける力、偵察は隠れた相手を見る力です。"
            "全部を暗記せず、今は『制圧が1以上なら場所を取りにいける』だけ覚えましょう。"
        ),
        task="空の戦線へ単独配備し、戦線力4を作れるカードを選んでください。",
        kind="card_choice",
        choices=(("artillery_1", "野戦砲兵中隊"), ("recon_2", "無人偵察隊"), ("infantry_1", "第1歩兵中隊")),
        correct_choice="infantry_1",
        success_message="正解です。制圧3が自身の支援1を有効にするため、単独戦線力は4です。",
        hint="単独配置したときに有効になる数値だけを、カードごとに合計してください。",
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
            "中央には第1歩兵中隊と補給1があるため、制圧の土台と小さな補給余力があります。"
            "ここへ支援カードを重ねると、制圧を増やさずに戦線力を伸ばせます。配備したカードはその戦線に残ります。"
        ),
        task="中央は敵に3差で負けています。制圧を増やさず逆転できるカードを選んでください。",
        kind="card_choice",
        choices=(("artillery_1", "野戦砲兵中隊"), ("recon_2", "無人偵察隊"), ("logistics_3", "戦域輸送隊")),
        correct_choice="artillery_1",
        success_message=(
            "正解です。野戦砲兵中隊の支援4が有効になり、補給1で需要1も満たせるため、3差を逆転できます。"
        ),
        hint="追加後の制圧、有効な支援、補給不足の順に候補ごとの結果を計算してください。",
    ),
    BasicLesson(
        id="supply",
        title="重い部隊には補給を付ける",
        plain_goal="機甲や砲兵のマイナス補給は需要です。同じ戦線のプラス補給で満たします。",
        explanation=(
            "第4機甲中隊は補給を2必要とします。補給が足りないと不足分だけ戦線力が下がり、"
            "完全に満たすと機甲1枚につき戦線力が2上がります。"
        ),
        task="第4機甲中隊だけがいる戦線で、敵戦線力7、需要2、補給0です。配備後の戦線力が最大になるカードを選んでください。",
        kind="card_choice",
        choices=(("logistics_1", "前線補給中隊"), ("infantry_1", "第1歩兵中隊"), ("logistics_2", "整備支援隊")),
        correct_choice="logistics_2",
        success_message=(
            "正解です。整備支援隊の補給3で需要2を満たし、自身の制圧1・支援2と機甲ボーナスも加わります。"
        ),
        hint="各候補を置いた後、補給不足、機甲ボーナス、追加される戦線力まで計算してください。",
    ),
    BasicLesson(
        id="recon",
        title="見えない相手は、同じ戦線で偵察する",
        plain_goal="偵察は、同じ戦線にいる未確認の相手カードを公開します。",
        explanation=(
            "相手カードは、偵察されるまでは『未確認部隊』として隠れます。"
            "偵察値は戦線力そのものには加わりませんが、相手の正体を知って次の命令を決めやすくします。"
        ),
        task="未確認部隊は左1枚・中央3枚・右2枚です。最も多く確認できる配置を選んでください。",
        kind="choice",
        choices=(("left", "左戦線へ配置する"), ("center", "中央戦線へ配置する"), ("right", "右戦線へ配置する")),
        correct_choice="center",
        success_message="正解です。中央戦線なら偵察3を使い、未確認部隊を3枚公開できます。",
        hint="各戦線で公開できる枚数を、前方偵察班の偵察値と照らし合わせてください。",
    ),
    BasicLesson(
        id="rounds",
        title="これを9ラウンド繰り返す",
        plain_goal="1ラウンドに手札から1枚を使い、配備したカードは盤面に残ります。",
        explanation=(
            "1ラウンドごとに両者が1枚ずつ配備し、各戦線の結果と任務点を記録します。"
            "同じカードはその対戦中にもう一度使えないため、対戦には最低9枚のデッキが必要です。"
        ),
        task="12枚のデッキで3ラウンドを終えました。未使用カードの枚数を選んでください。",
        kind="choice",
        choices=(("six", "未使用は8枚になる"), ("nine", "未使用は9枚になる"), ("twelve", "未使用は10枚になる")),
        correct_choice="nine",
        success_message="正解です。3ラウンドで3枚を使うため、12枚から9枚が残ります。",
        hint="使用したカードの枚数を、開始時のデッキ枚数から引いてください。",
    ),
    BasicLesson(
        id="victory",
        title="最後に3戦線を数える",
        plain_goal="9ラウンド後の最終戦線力を比べ、取った戦線が多い側を決めます。",
        explanation=(
            "あなたが左と中央、相手が右を取っているなら、あなたの2対1で勝利です。"
            "取った戦線数が同じ場合だけ、各ラウンドで得た任務点の合計が決着に使われます。"
        ),
        task="最終結果は自軍1戦線・敵軍1戦線、任務点は自軍12・敵軍9です。勝敗を選んでください。",
        kind="choice",
        choices=(("player", "自軍の勝利になる"), ("opponent", "敵軍の勝利になる"), ("draw", "対戦は引き分けになる")),
        correct_choice="player",
        success_message="正解です。確保戦線数が同じため任務点を比べ、12対9で自軍の勝利です。",
        hint="確保戦線数を先に比べ、同数の場合だけ任務点を比較してください。",
    ),
)


BASIC_LESSON_INDEX = {lesson.id: lesson for lesson in BASIC_TUTORIAL_LESSONS}


def get_basic_lesson(lesson_id: str) -> BasicLesson:
    """Return one core-rules lesson by its stable ID."""

    return BASIC_LESSON_INDEX[lesson_id]
