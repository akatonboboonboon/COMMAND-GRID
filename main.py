"""COMMAND GRID — a multi-page NiceGUI UI prototype.

The current build intentionally keeps game data local to the browser session.
The UI and domain helpers are separated so PostgreSQL-backed multiplayer can be
added without rewriting the screens.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator

from nicegui import app, ui

from game_data import (
    CARDS,
    GLOSSARY,
    ROLE_INFO,
    STARTER_DECK,
    UnitCard,
    analyze_deck,
    get_card,
)


BASE_DIR = Path(__file__).resolve().parent
app.add_static_files("/static", BASE_DIR / "static")


NAV_ITEMS = (
    ("/", "ホーム", "grid_view"),
    ("/lobby", "対戦", "swords"),
    ("/cards", "カード図鑑", "style"),
    ("/deck", "デッキ編成", "view_carousel"),
    ("/profile", "記録・プロフィール", "military_tech"),
    ("/settings", "設定", "tune"),
    ("/learn", "遊び方・用語", "help_outline"),
)

PHASES = (
    ("索敵", "隠れているカードを見つけます。"),
    ("電子戦", "相手の情報や支援を妨げます。"),
    ("砲撃", "見つけた相手を遠くから支援します。"),
    ("機動", "部隊を移動し、突破を試みます。"),
    ("地上戦", "同じ戦線にいる部隊を比べます。"),
    ("制圧判定", "どちらがその戦線を確保したか決めます。"),
)

TUTORIAL_STEPS = (
    ("目的", "難しい軍事知識は不要です。まずは3つの場所のうち2つを取ることだけ覚えましょう。"),
    ("歩兵", "歩兵は場所を守る基本カードです。まず中央戦線の前列へ置きます。"),
    ("未確認部隊", "相手の伏せたカードは正体が分かるまで『未確認部隊』と表示されます。"),
    ("偵察", "偵察は相手の伏せたカードを見る役です。攻撃前に情報を集めます。"),
    ("砲兵", "砲兵は見つけた相手を遠くから支援します。単独では場所を取れません。"),
    ("工兵", "工兵は道や守りを整え、同じ戦線の味方を助けます。"),
    ("機甲と兵站", "機甲は突破役です。重い部隊なので兵站の補給があると本来の力を出せます。"),
    ("同時命令", "あなたと相手の命令は同時に公開されます。相手の行動を予想するのがポイントです。"),
)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok"}


def go(path: str) -> None:
    ui.navigate.to(path)


def chip(text: str, variant: str = "") -> ui.label:
    suffix = f" status-chip--{variant}" if variant else ""
    return ui.label(text).classes(f"status-chip{suffix}")


def section_heading(title: str, subtitle: str | None = None) -> None:
    with ui.row().classes("w-full items-end justify-between gap-4"):
        with ui.column().classes("gap-1"):
            ui.label(title).classes("section-title")
            if subtitle:
                ui.label(subtitle).classes("section-subtitle")


def primary_button(label: str, path: str | None = None, icon: str | None = None,
                   on_click: Callable | None = None) -> ui.button:
    handler = on_click or (lambda: go(path or "/"))
    return ui.button(label, icon=icon, on_click=handler).props("no-caps unelevated").classes("primary-button")


def secondary_button(label: str, path: str | None = None, icon: str | None = None,
                     on_click: Callable | None = None) -> ui.button:
    handler = on_click or (lambda: go(path or "/"))
    return ui.button(label, icon=icon, on_click=handler).props("no-caps flat").classes("secondary-button")


def unit_symbol(card: UnitCard, size: str = "md") -> None:
    with ui.element("div").classes(f"unit-symbol unit-symbol--{size}").props(
        f'data-echelon="{card.echelon}" role="img" aria-label="{card.branch}の部隊記号"'
    ):
        ui.label(card.symbol)


def card_stats(card: UnitCard) -> None:
    with ui.element("div").classes("card-stats"):
        for label, value in (
            ("制圧", card.control),
            ("支援", card.support),
            ("索敵", card.recon),
        ):
            with ui.element("div").classes("card-stat"):
                ui.label(label).classes("card-stat__label")
                ui.label(str(value)).classes("card-stat__value")


def card_detail_dialog(card: UnitCard) -> ui.dialog:
    with ui.dialog() as dialog, ui.card().classes("dialog-card"):
        with ui.row().classes("w-full items-start no-wrap gap-5"):
            unit_symbol(card, "lg")
            with ui.column().classes("gap-1 flex-1"):
                with ui.row().classes("items-center gap-2"):
                    chip(card.branch)
                    chip(card.rarity, "yellow" if card.rarity != "標準" else "")
                    if not card.owned:
                        chip("未入手", "red")
                ui.label(card.name).classes("text-2xl font-bold")
                ui.label(f"{card.echelon}・配備コスト {card.cost}・扱いやすさ {card.difficulty}").classes("muted text-sm")
        ui.separator().classes("bg-blue-grey-8 my-2")
        with ui.column().classes("gap-4"):
            with ui.column().classes("gap-1"):
                ui.label("ひとことで言うと").classes("blue-text text-xs font-bold")
                ui.label(card.tagline).classes("text-lg font-bold")
            with ui.column().classes("gap-1"):
                ui.label("ゲームでは").classes("blue-text text-xs font-bold")
                ui.label(card.game_text).classes("section-subtitle")
            with ui.column().classes("gap-1"):
                ui.label("相性がよい使い方").classes("blue-text text-xs font-bold")
                ui.label(card.good_with).classes("section-subtitle")
            with ui.column().classes("gap-1"):
                ui.label("軍事メモ").classes("yellow-text text-xs font-bold")
                ui.label(card.military_note).classes("section-subtitle")
            with ui.element("div").classes("beginner-callout"):
                ui.label("記号の見方").classes("font-bold")
                ui.label("外側の枠は部隊、中央は主な役割、上側の文字は本作での部隊規模を示します。").classes("text-sm")
        secondary_button("閉じる", icon="close", on_click=dialog.close)
    return dialog


def unit_card(card: UnitCard, *, selected: bool = False,
              action_label: str = "詳しく見る", action: Callable | None = None) -> None:
    dialog = card_detail_dialog(card)
    classes = "unit-card"
    if selected:
        classes += " unit-card--selected"
    if not card.owned:
        classes += " unit-card--locked"
    with ui.card().classes(classes):
        with ui.row().classes("w-full items-start justify-between no-wrap"):
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(card.branch).classes("unit-card__branch")
                ui.label(card.name).classes("unit-card__name")
            ui.label(str(card.cost)).classes("unit-card__cost").tooltip("配備コスト")
        with ui.element("div").classes("unit-card__symbol-area"):
            unit_symbol(card)
        ui.label(card.tagline).classes("unit-card__tagline")
        card_stats(card)
        handler = action or dialog.open
        ui.button(action_label, on_click=handler).props("flat no-caps").classes("card-action")


def metric_card(label: str, value: str, note: str, color_class: str = "") -> None:
    with ui.card().classes("metric-card"):
        ui.label(label).classes("metric-label")
        ui.label(value).classes(f"metric-value {color_class}")
        ui.label(note).classes("metric-note")


def role_card(role: str) -> None:
    info = ROLE_INFO[role]
    with ui.card().classes("role-card").style(f"--role-color: {info['color']}"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            with ui.element("div").classes("role-icon"):
                ui.icon(info["icon"], size="22px")
            with ui.column().classes("gap-0"):
                ui.label(role).classes("font-bold text-lg")
                ui.label(info["verb"]).classes("text-xs").style(f"color: {info['color']}")
        ui.label(info["plain"]).classes("section-subtitle mt-2")
        with ui.expansion("軍事メモ", icon="menu_book").classes("w-full text-sm"):
            ui.label(info["note"]).classes("section-subtitle px-2 pb-2")


@contextmanager
def page_shell(active: str, eyebrow: str, title: str, subtitle: str) -> Iterator[None]:
    ui.add_head_html('<link rel="stylesheet" href="/static/styles.css">')
    ui.colors(
        primary="#60AFFF",
        secondary="#55C7D9",
        accent="#F4C95D",
        dark="#07111C",
        positive="#55D39A",
        negative="#FF746A",
        warning="#F4C95D",
    )
    ui.page_title(f"{title} | COMMAND GRID")
    ui.query("body").classes("cg-body")

    drawer = ui.left_drawer(value=False).props("width=246 breakpoint=1024 show-if-above bordered").classes("cg-drawer")
    with drawer:
        with ui.row().classes("items-center no-wrap gap-3 px-2"):
            ui.label("CG").classes("brand-mark")
            with ui.column().classes("gap-0"):
                ui.label("COMMAND GRID").classes("brand-name")
                ui.label("統合戦線").classes("brand-subtitle")
        ui.label("OPERATIONS").classes("nav-caption")
        for route, label, icon in NAV_ITEMS:
            active_class = " nav-button--active" if route == active else ""
            ui.button(label, icon=icon, on_click=lambda path=route: go(path)).props(
                "flat no-caps align=left"
            ).classes(f"nav-button{active_class}")
        with ui.element("div").classes("drawer-brief"):
            with ui.row().classes("items-center gap-2"):
                ui.element("span").classes("online-dot")
                ui.label("初心者サポート ON").classes("font-bold text-xs")
            ui.label("用語の横に普段の言葉で説明を表示しています。設定からいつでも変更できます。")

    with ui.header().classes("cg-header items-center no-wrap"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat round aria-label=メニュー")
        with ui.row().classes("items-center no-wrap gap-3"):
            ui.label("CG").classes("brand-mark").style("width:34px;height:34px;flex-basis:34px;font-size:11px")
            with ui.column().classes("gap-0"):
                ui.label("COMMAND GRID").classes("font-bold text-sm")
                ui.label("統合戦線・UIプロトタイプ").classes("header-subtitle muted text-xs")
        ui.space()
        with ui.row().classes("items-center gap-2"):
            ui.element("span").classes("online-dot")
            ui.label("接続中").classes("header-mode-label muted text-xs")
            chip("初心者モード", "green")
            ui.button("OS", on_click=lambda: go("/profile")).props("round unelevated aria-label=プロフィール").classes(
                "bg-blue-9 text-white"
            )

    with ui.column().classes("cg-page"):
        with ui.column().classes("gap-1 w-full"):
            ui.label(eyebrow).classes("page-eyebrow")
            ui.label(title).classes("page-title")
            ui.label(subtitle).classes("page-subtitle")
        yield
        ui.label(
            "本作の部隊・記号・編制は、実在する軍事記号を参考にゲーム向けに簡略化したものです。"
            "実際の組織や作戦を正確に再現する教育資料ではありません。"
        ).classes("disclaimer")


@ui.page("/")
def home_page() -> None:
    with page_shell(
        "/", "OPERATIONS DESK", "作戦室へようこそ",
        "軍事知識は必要ありません。『見る・守る・支える』から始めて、3つの戦線を確保しましょう。",
    ):
        with ui.element("section").classes("hero"):
            with ui.element("div").classes("hero-main"):
                with ui.column().classes("hero-copy gap-0"):
                    ui.label("TACTICAL CARD GAME / 1 VS 1").classes("hero-kicker")
                    ui.label("記号を読み、役割を組み合わせ、戦線を確保する。").classes("hero-title")
                    ui.label(
                        "歩兵が場所を取り、偵察が相手を見つけ、砲兵が後ろから助けます。"
                        "カードの仕事を読むだけで遊べる、同時命令型の対戦ゲームです。"
                    ).classes("hero-description")
                    with ui.row().classes("gap-3 mt-6"):
                        primary_button("5分でわかる演習", "/learn", "school")
                        secondary_button("対戦を始める", "/lobby", "swords")
            with ui.card().classes("panel panel--strong"):
                with ui.row().classes("w-full items-center justify-between"):
                    ui.label("現在の任務").classes("font-bold")
                    chip("初任務", "yellow")
                ui.label("6つの役割を試す").classes("text-xl font-bold mt-2")
                ui.label("演習または対戦で、歩兵・機甲・偵察・砲兵・工兵・兵站を1回ずつ使います。").classes("section-subtitle")
                ui.linear_progress(value=4 / 6).props("rounded size=8px").classes("progress-track mt-4")
                with ui.row().classes("w-full justify-between muted text-xs"):
                    ui.label("4 / 6 兵科")
                    ui.label("報酬：青図フレーム")
                ui.separator().classes("bg-blue-grey-8 my-3")
                with ui.row().classes("w-full items-center justify-between"):
                    with ui.column().classes("gap-0"):
                        ui.label("前回の対戦").classes("muted text-xs")
                        ui.label("ラウンド 4 / 6・中央で優勢").classes("text-sm font-bold")
                    ui.button(icon="arrow_forward", on_click=lambda: go("/battle")).props("round flat aria-label=対戦に戻る")

        with ui.element("div").classes("metric-grid"):
            metric_card("現在のランク", "CADET II", "次のランクまで 120", "blue-text")
            metric_card("カード図鑑", "12 / 18", "ゲームカード収集率 67%")
            metric_card("今週の対戦", "7 戦", "4勝・3敗", "green-text")
            metric_card("主な役割", "偵察", "相手を見つけるのが得意", "yellow-text")

        with ui.element("div").classes("content-grid"):
            with ui.card().classes("panel"):
                section_heading("このゲームは何をするの？", "最初に覚えるのは3つだけです。")
                with ui.element("div").classes("three-grid mt-4"):
                    for number, heading, body in (
                        ("01", "3つの戦線に置く", "手札から部隊を選び、左・中央・右のどこかへ配置します。"),
                        ("02", "命令を同時公開", "相手も同時に選んでいるため、何をしてくるか予想します。"),
                        ("03", "2つ以上を確保", "6ラウンド後に多くの戦線を取った側が作戦成功です。"),
                    ):
                        with ui.card().classes("step-card"):
                            ui.label(number).classes("step-number")
                            ui.label(heading).classes("font-bold")
                            ui.label(body).classes("section-subtitle mt-2")
            with ui.card().classes("panel"):
                section_heading("覚え方", "6つの仕事は一つの文章で覚えられます。")
                with ui.element("div").classes("beginner-callout mt-4"):
                    ui.label("歩兵が取り、偵察が見つけ、砲兵が助ける。").classes("font-bold text-lg")
                    ui.label("工兵が整え、兵站が支え、機甲が突破します。").classes("text-sm mt-1")
                secondary_button("6つの役割を見る", "/learn", "menu_book").classes("mt-3")

        section_heading("おすすめの始め方", "まずは分かりやすいスターターデッキから。")
        with ui.element("div").classes("three-grid"):
            for title, level, body, icon in (
                ("はじめての統合部隊", "かんたん", "6つの役割を少しずつ試せる、迷いにくい基本デッキ。", "extension"),
                ("見つけて支援", "ふつう", "偵察で相手を見つけ、砲兵で支援する情報重視のデッキ。", "visibility"),
                ("守って前進", "かんたん", "歩兵と工兵で戦線を確保し、少しずつ前へ進むデッキ。", "shield"),
            ):
                with ui.card().classes("lobby-mode"):
                    with ui.row().classes("w-full justify-between items-start"):
                        ui.icon(icon, size="28px").classes("blue-text")
                        chip(level, "green" if level == "かんたん" else "yellow")
                    ui.label(title).classes("text-lg font-bold mt-2")
                    ui.label(body).classes("section-subtitle")


@ui.page("/learn")
def learn_page() -> None:
    with page_shell(
        "/learn", "FIELD MANUAL", "5分でわかる遊び方",
        "すべての記号を暗記する必要はありません。カードに書かれた『仕事』を見れば、そのまま遊べます。",
    ):
        with ui.element("div").classes("beginner-callout"):
            with ui.row().classes("items-start gap-3 no-wrap"):
                ui.icon("lightbulb", size="24px")
                with ui.column().classes("gap-1"):
                    ui.label("最初の目標は『3つの場所のうち2つを取る』だけ").classes("font-bold")
                    ui.label("専門用語は後から自然に覚えられます。分からない言葉はこのページにいつでも戻って確認できます。").classes("text-sm")

        section_heading("初回演習：8つのステップ", "上から順に読むと、一試合の考え方が分かります。")
        with ui.element("div").classes("three-grid"):
            for index, (title, body) in enumerate(TUTORIAL_STEPS, 1):
                with ui.card().classes("step-card"):
                    ui.label(f"{index:02}").classes("step-number")
                    ui.label(title).classes("font-bold")
                    ui.label(body).classes("section-subtitle mt-2")

        section_heading("6つの部隊の仕事", "普通のゲーム語を先に、軍事的な背景は折りたたんで表示します。")
        with ui.element("div").classes("role-grid"):
            for role in ROLE_INFO:
                role_card(role)

        section_heading("命令が解決される順番", "結果は一度に出さず、初心者モードでは一つずつ説明します。")
        with ui.element("div").classes("tutorial-timeline"):
            for index, (name, description) in enumerate(PHASES, 1):
                with ui.element("div").classes("timeline-item"):
                    ui.label(f"PHASE {index}").classes("page-eyebrow")
                    ui.label(name).classes("font-bold text-lg mt-1")
                    ui.label(description).classes("section-subtitle mt-2")

        section_heading("用語集", "専門用語を普段の言葉に置き換えて説明します。")
        with ui.column().classes("w-full gap-2"):
            for term, explanation in GLOSSARY:
                with ui.expansion(term, icon="help_outline").classes("glossary-expansion"):
                    ui.label(explanation).classes("section-subtitle px-4 pb-4")

        with ui.row().classes("gap-3"):
            primary_button("演習を始める", "/battle", "play_arrow")
            secondary_button("カード図鑑を見る", "/cards", "style")


@ui.page("/cards")
def cards_page() -> None:
    with page_shell(
        "/cards", "COLLECTION / 12 OF 18", "カード図鑑",
        "未入手のカードも能力と入手方法を確認できます。レア度は強さの順位ではありません。",
    ):
        with ui.element("div").classes("metric-grid"):
            metric_card("ゲームカード", "12 / 18", "未入手も能力を確認できます", "blue-text")
            metric_card("兵科図鑑", "6 / 6", "初期6兵科を発見済み", "green-text")
            metric_card("編制セット", "2 / 8", "次は『偵察支援群』")
            metric_card("外観コレクション", "7 / 24", "強さには影響しません", "yellow-text")

        filter_state = {"query": "", "branch": "すべて"}

        def set_query(event) -> None:
            filter_state["query"] = (event.value or "").strip().lower()
            card_grid.refresh()

        def set_branch(event) -> None:
            filter_state["branch"] = event.value or "すべて"
            card_grid.refresh()

        with ui.element("div").classes("filter-bar"):
            ui.input(
                "カード名や役割で検索", placeholder="例：歩兵、相手を見る、補給",
                on_change=set_query,
            ).props("outlined clearable debounce=250").classes("filter-control")
            ui.select(
                ["すべて", *ROLE_INFO.keys()], value="すべて", label="兵科で絞る",
                on_change=set_branch,
            ).props("outlined options-dense").classes("filter-control")

        @ui.refreshable
        def card_grid() -> None:
            query = filter_state["query"]
            branch = filter_state["branch"]
            visible = [
                card for card in CARDS
                if (branch == "すべて" or card.branch == branch)
                and (
                    not query
                    or query in card.name.lower()
                    or query in card.branch.lower()
                    or query in card.tagline.lower()
                    or query in card.game_text.lower()
                )
            ]
            ui.label(f"{len(visible)}枚を表示").classes("muted text-xs")
            if not visible:
                with ui.card().classes("panel"):
                    ui.icon("search_off", size="34px").classes("muted")
                    ui.label("条件に合うカードがありません").classes("font-bold")
                    ui.label("別の名前や役割で検索してください。").classes("section-subtitle")
                return
            with ui.element("div").classes("unit-card-grid"):
                for card in visible:
                    unit_card(card)

        card_grid()


@ui.page("/deck")
def deck_page() -> None:
    with page_shell(
        "/deck", "FORCE BUILDER", "デッキ編成",
        "役割の違うカードを組み合わせて、自分の部隊を作ります。実際の軍隊編制ではなくゲーム用の構成です。",
    ):
        app.storage.user.setdefault("deck", list(STARTER_DECK))

        def update_deck(new_deck: list[str], message: str | None = None) -> None:
            app.storage.user["deck"] = new_deck
            deck_view.refresh()
            if message:
                ui.notify(message, type="positive")

        def add_card(card_id: str) -> None:
            deck = list(app.storage.user.get("deck", []))
            if len(deck) >= 12:
                ui.notify("デッキは12枚までです。先に1枚外してください。", type="warning")
                return
            if card_id in deck:
                ui.notify("この試作版では同じカードを1枚まで入れられます。", type="warning")
                return
            deck.append(card_id)
            update_deck(deck)

        def remove_card(card_id: str) -> None:
            deck = list(app.storage.user.get("deck", []))
            if card_id in deck:
                deck.remove(card_id)
                update_deck(deck)

        @ui.refreshable
        def deck_view() -> None:
            deck_ids = list(app.storage.user.get("deck", list(STARTER_DECK)))
            analysis = analyze_deck(deck_ids)
            with ui.element("div").classes("deck-layout"):
                with ui.card().classes("panel"):
                    section_heading("所持カード", "＋を押すと右側のデッキへ追加します。")
                    with ui.column().classes("w-full gap-2 deck-list mt-3"):
                        for card in CARDS:
                            with ui.element("div").classes("deck-row"):
                                with ui.row().classes("w-full items-center no-wrap gap-3"):
                                    unit_symbol(card, "sm")
                                    with ui.column().classes("gap-0 min-w-0 flex-1"):
                                        with ui.row().classes("items-center gap-2"):
                                            ui.label(card.name).classes("font-bold text-sm")
                                            chip(card.branch)
                                        ui.label(card.tagline).classes("muted text-xs")
                                    add = ui.button(
                                        icon="add", on_click=lambda card_id=card.id: add_card(card_id)
                                    ).props("round flat aria-label=カードを追加")
                                    if not card.owned or card.id in deck_ids or len(deck_ids) >= 12:
                                        add.props("disable")

                with ui.column().classes("w-full gap-4"):
                    with ui.card().classes("panel"):
                        with ui.row().classes("w-full items-start justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label("はじめての統合部隊").classes("section-title")
                                ui.label(f"{analysis['count']} / 12枚・合計コスト {analysis['cost']}").classes("section-subtitle")
                            chip("使用中", "green")
                        ui.linear_progress(value=min(1, analysis["count"] / 12)).props("rounded size=8px").classes("progress-track mt-3")
                        with ui.column().classes("w-full gap-2 mt-4"):
                            for label, key in (
                                ("前線を取る力", "front"),
                                ("相手を見る力", "vision"),
                                ("支援する力", "support"),
                            ):
                                with ui.row().classes("w-full items-center gap-3 no-wrap"):
                                    ui.label(label).classes("muted text-xs w-28")
                                    ui.linear_progress(value=analysis[key] / 5).props("rounded size=6px").classes("progress-track flex-1")
                                    ui.label(f"{analysis[key]} / 5").classes("mono text-xs")
                        ui.separator().classes("bg-blue-grey-8 my-3")
                        ui.label("編成アドバイス").classes("font-bold text-sm")
                        for tip in analysis["tips"]:
                            ui.label(tip).classes("deck-tip")
                        with ui.row().classes("gap-2 mt-3"):
                            primary_button("保存して使用", icon="save", on_click=lambda: ui.notify("デッキを保存しました。", type="positive"))
                            secondary_button(
                                "元に戻す", icon="restart_alt",
                                on_click=lambda: update_deck(list(STARTER_DECK), "スターターデッキに戻しました。"),
                            )

                    with ui.card().classes("panel"):
                        section_heading("現在の12枚", "−を押すとデッキから外します。")
                        with ui.column().classes("w-full gap-2 mt-3"):
                            if not deck_ids:
                                ui.label("カードがありません。左側から追加してください。").classes("section-subtitle")
                            for card_id in deck_ids:
                                card = get_card(card_id)
                                with ui.element("div").classes("deck-row"):
                                    with ui.row().classes("w-full items-center no-wrap gap-3"):
                                        unit_symbol(card, "sm")
                                        with ui.column().classes("gap-0 flex-1"):
                                            ui.label(card.name).classes("font-bold text-sm")
                                            ui.label(f"{card.branch}・コスト {card.cost}").classes("muted text-xs")
                                        ui.button(
                                            icon="remove", on_click=lambda cid=card_id: remove_card(cid)
                                        ).props("round flat aria-label=カードを外す")

        deck_view()


@ui.page("/lobby")
def lobby_page() -> None:
    with page_shell(
        "/lobby", "MATCH CONTROL", "対戦の準備",
        "遊ぶモードとデッキを選びます。最初は時間制限のない演習がおすすめです。",
    ):
        with ui.dialog() as match_dialog, ui.card().classes("dialog-card"):
            with ui.column().classes("w-full items-center text-center gap-3"):
                ui.spinner("dots", size="54px", color="primary")
                ui.label("対戦相手が見つかりました").classes("text-2xl font-bold")
                ui.label("Aoi-17・CADET II").classes("muted")
                with ui.element("div").classes("beginner-callout"):
                    ui.label("6ラウンド / 3戦線 / 同時命令").classes("font-bold")
                    ui.label("勝利条件：2つの戦線を確保、または任務点5点").classes("text-sm")
                primary_button("準備完了", "/battle", "check_circle")
                secondary_button("戻る", icon="close", on_click=match_dialog.close)

        section_heading("遊ぶモード", "カードの性能はどのモードでも同じです。")
        with ui.element("div").classes("three-grid"):
            for title, badge, body, icon, recommended in (
                ("演習", "ひとり用", "ゆっくり操作を覚えられます。時間制限もありません。", "school", True),
                ("カジュアル対戦", "オンライン", "勝敗を気にせず、他のプレイヤーと遊びます。", "public", False),
                ("ランク対戦", "競技", "実力が近い相手と競い、ランクを上げます。", "leaderboard", False),
            ):
                with ui.card().classes("lobby-mode"):
                    with ui.row().classes("w-full items-start justify-between"):
                        ui.icon(icon, size="30px").classes("blue-text")
                        chip("おすすめ" if recommended else badge, "green" if recommended else "")
                    ui.label(title).classes("text-xl font-bold mt-2")
                    ui.label(body).classes("section-subtitle")
                    ui.button("このモードを選ぶ", on_click=match_dialog.open).props("flat no-caps").classes("card-action")

        with ui.element("div").classes("content-grid"):
            with ui.card().classes("panel"):
                section_heading("使用デッキ", "現在選択中のデッキです。")
                with ui.row().classes("w-full items-center justify-between gap-4 mt-3"):
                    with ui.column().classes("gap-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label("はじめての統合部隊").classes("text-xl font-bold")
                            chip("かんたん", "green")
                        ui.label("得意：守備と支援　/　苦手：すばやい突破").classes("section-subtitle")
                        ui.label("12 / 12枚・補給バランス 良好").classes("mono text-xs blue-text")
                    secondary_button("デッキを確認", "/deck", "view_carousel")
                ui.separator().classes("bg-blue-grey-8 my-4")
                with ui.row().classes("gap-3"):
                    primary_button("このデッキで対戦", icon="swords", on_click=match_dialog.open)
                    secondary_button("初心者ヒント ON", icon="tips_and_updates", on_click=lambda: ui.notify("対戦中もおすすめ行動を表示します。"))
            with ui.card().classes("panel"):
                section_heading("フレンド対戦", "合言葉または招待URLで友人と遊べます。")
                ui.label("GRID-4821").classes("mono text-3xl font-bold blue-text mt-3")
                ui.label("参加者を待っています（1 / 2）").classes("section-subtitle")

                def copy_invite() -> None:
                    ui.run_javascript("navigator.clipboard.writeText(window.location.origin + '/lobby?code=GRID-4821')")
                    ui.notify("招待URLをコピーしました。", type="positive")

                secondary_button("招待URLをコピー", icon="content_copy", on_click=copy_invite).classes("mt-3")


def initial_battle_state() -> dict[str, object]:
    return {
        "round": 2,
        "selected": None,
        "planned_lane": None,
        "complete": False,
        "mission_points": 2,
        "lanes": {
            "left": {"friendly": 3, "enemy": 2, "unit": "第1歩兵中隊", "unknown": True},
            "center": {"friendly": 2, "enemy": 3, "unit": "第2工兵中隊", "unknown": True},
            "right": {"friendly": 1, "enemy": 1, "unit": "前線補給中隊", "unknown": False},
        },
        "log": [
            "第1ラウンド：左戦線に第1歩兵中隊を配置しました。",
            "中央戦線に未確認部隊を確認。偵察すると正体が分かります。",
            "右戦線は現在互角です。",
        ],
    }


@ui.page("/battle")
def battle_page() -> None:
    with page_shell(
        "/lobby", "LIVE OPERATION", "第04演習区域・対戦中",
        "カードを1枚選び、配置する戦線を選んでから命令を確定します。",
    ):
        app.storage.user.setdefault("battle", initial_battle_state())
        hand_ids = ("recon_1", "infantry_2", "artillery_1", "armor_1", "logistics_1")

        def mutate(**changes) -> dict[str, object]:
            state = dict(app.storage.user.get("battle", initial_battle_state()))
            state.update(changes)
            app.storage.user["battle"] = state
            return state

        def select_card(card_id: str) -> None:
            mutate(selected=card_id)
            battle_board.refresh()

        def plan_lane(lane_id: str) -> None:
            state = app.storage.user.get("battle", initial_battle_state())
            if not state.get("selected"):
                ui.notify("先に手札からカードを選んでください。", type="warning")
                return
            mutate(planned_lane=lane_id)
            battle_board.refresh()

        def confirm_order() -> None:
            state = dict(app.storage.user.get("battle", initial_battle_state()))
            card_id = state.get("selected")
            lane_id = state.get("planned_lane")
            if not card_id or not lane_id:
                ui.notify("カードと配置先の戦線を選んでください。", type="warning")
                return
            card = get_card(str(card_id))
            lanes = {key: dict(value) for key, value in state["lanes"].items()}
            lane = lanes[str(lane_id)]
            gain = max(1, card.control + card.support)
            lane["friendly"] += gain
            lane["unit"] = card.name
            if card.branch == "偵察":
                lane["unknown"] = False
            logs = list(state["log"])
            lane_names = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}
            logs.insert(0, f"第{state['round']}ラウンド：{card.name}を{lane_names[str(lane_id)]}へ配置。制圧・支援が{gain}増えました。")
            next_round = int(state["round"]) + 1
            complete = next_round > 6
            state.update(
                lanes=lanes,
                log=logs[:6],
                round=min(next_round, 6),
                selected=None,
                planned_lane=None,
                complete=complete,
                mission_points=min(5, int(state["mission_points"]) + (1 if gain >= 4 else 0)),
            )
            app.storage.user["battle"] = state
            ui.notify("命令を公開し、結果を解決しました。", type="positive")
            battle_board.refresh()

        def reset_battle() -> None:
            app.storage.user["battle"] = initial_battle_state()
            battle_board.refresh()
            ui.notify("演習を最初の状態に戻しました。")

        @ui.refreshable
        def battle_board() -> None:
            state = app.storage.user.get("battle", initial_battle_state())
            selected_id = state.get("selected")
            planned_lane = state.get("planned_lane")

            with ui.element("div").classes("battle-status"):
                with ui.column().classes("gap-0"):
                    ui.label("あなた / OSATO").classes("font-bold")
                    ui.label(f"任務点 {state['mission_points']} / 5").classes("mono blue-text text-xs")
                with ui.column().classes("items-center gap-0"):
                    ui.label(f"ROUND {state['round']} / 6").classes("mono text-xl font-bold")
                    ui.label("命令を選んでください").classes("muted text-xs")
                with ui.column().classes("items-end gap-0"):
                    ui.label("AOI-17 / 相手").classes("font-bold")
                    ui.label("命令を選択中・接続済み").classes("green-text text-xs")

            if state.get("complete"):
                with ui.element("div").classes("result-banner"):
                    ui.label("作戦成功").classes("page-eyebrow green-text")
                    ui.label("左戦線と中央戦線の2か所を確保しました").classes("text-2xl font-bold mt-1")
                    ui.label("偵察から砲兵へつないだ支援が、中央戦線の確保に貢献しました。").classes("text-sm mt-2")
                    with ui.row().classes("gap-2 mt-4"):
                        primary_button("同じ条件でもう一度", icon="replay", on_click=reset_battle)
                        secondary_button("デッキを調整", "/deck", "view_carousel")
                        secondary_button("ホームへ", "/", "home")
                return

            with ui.element("div").classes("phase-strip"):
                for index, (name, _) in enumerate(PHASES):
                    ui.label(f"{index + 1} {name}").classes(
                        "phase-item" + (" phase-item--active" if index == 0 else "")
                    )

            with ui.element("div").classes("battle-layout"):
                with ui.column().classes("w-full gap-4"):
                    with ui.element("div").classes("lane-grid"):
                        lane_labels = {
                            "left": ("左戦線（左翼）", "森林"),
                            "center": ("中央戦線", "市街地"),
                            "right": ("右戦線（右翼）", "平地"),
                        }
                        for lane_id, (lane_name, terrain) in lane_labels.items():
                            lane = state["lanes"][lane_id]
                            planned_class = " battle-lane--planned" if planned_lane == lane_id else ""
                            with ui.element("div").classes(f"battle-lane{planned_class}"):
                                with ui.row().classes("lane-header items-center justify-between"):
                                    with ui.column().classes("gap-0"):
                                        ui.label(lane_name).classes("font-bold")
                                        ui.label(terrain).classes("muted text-xs")
                                    difference = lane["friendly"] - lane["enemy"]
                                    if difference > 0:
                                        chip(f"あなたが優勢 +{difference}", "green")
                                    elif difference < 0:
                                        chip(f"相手が優勢 +{abs(difference)}", "red")
                                    else:
                                        chip("互角", "yellow")
                                ui.label("相手・前列").classes("muted text-xs mt-3")
                                if lane["unknown"]:
                                    with ui.element("div").classes("unknown-unit"):
                                        ui.icon("help_outline", size="24px")
                                        ui.label("未確認部隊 1")
                                else:
                                    with ui.element("div").classes("unknown-unit"):
                                        ui.icon("visibility", size="22px").classes("danger-text")
                                        ui.label("機械化歩兵隊・発見済み")
                                with ui.element("div").classes("control-meter mt-3"):
                                    ui.label(f"味方 {lane['friendly']}").classes("blue-text")
                                    ui.label("制圧").classes("muted")
                                    ui.label(f"敵 {lane['enemy']}").classes("danger-text text-right")
                                ui.label("あなた・前列").classes("muted text-xs mt-3")
                                with ui.element("div").classes("front-line"):
                                    ui.label(lane["unit"]).classes("font-bold text-sm")
                                    ui.label("この場所を確保する部隊").classes("muted text-xs")
                                ui.button(
                                    "ここに配置", icon="place", on_click=lambda lid=lane_id: plan_lane(lid)
                                ).props("flat no-caps").classes("card-action mt-3")

                    with ui.card().classes("panel"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label("手札").classes("section-title")
                                ui.label("カードを選択してから、配置先の戦線を選びます。").classes("section-subtitle")
                            chip("補給 6", "green")
                        with ui.element("div").classes("hand-strip mt-3"):
                            for card_id in hand_ids:
                                card = get_card(card_id)
                                selected_class = " hand-card--selected" if selected_id == card_id else ""
                                with ui.card().classes(f"hand-card{selected_class}").on(
                                    "click", lambda cid=card_id: select_card(cid)
                                ):
                                    with ui.row().classes("w-full items-start justify-between no-wrap"):
                                        ui.label(card.branch).classes("unit-card__branch")
                                        ui.label(str(card.cost)).classes("unit-card__cost")
                                    ui.label(card.name).classes("font-bold text-sm min-h-10")
                                    with ui.element("div").classes("unit-card__symbol-area").style("min-height:72px"):
                                        unit_symbol(card, "sm")
                                    ui.label(card.tagline).classes("text-xs font-bold")
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.column().classes("gap-0 flex-1"):
                                if selected_id and planned_lane:
                                    card = get_card(str(selected_id))
                                    lane_name = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}[str(planned_lane)]
                                    ui.label(f"予定：{card.name}を{lane_name}へ配置").classes("font-bold")
                                    ui.label("確定すると相手の命令と同時に公開されます。").classes("muted text-xs")
                                else:
                                    ui.label("カードと配置先を選んでください").classes("muted text-sm")
                            primary_button("命令を確定", icon="check", on_click=confirm_order)
                            secondary_button("やり直す", icon="undo", on_click=lambda: (mutate(selected=None, planned_lane=None), battle_board.refresh()))

                with ui.column().classes("battle-side w-full gap-4"):
                    with ui.card().classes("panel"):
                        section_heading("いま何をすればいい？")
                        with ui.element("div").classes("beginner-callout mt-3"):
                            ui.label("今回のおすすめ").classes("font-bold")
                            ui.label("中央に偵察カードを置くと、未確認の相手カードを確認できます。").classes("text-sm mt-1")
                        ui.label("1. 手札の『前方偵察班』を選ぶ").classes("text-sm mt-3")
                        ui.label("2. 中央戦線の『ここに配置』を押す").classes("text-sm")
                        ui.label("3. 『命令を確定』を押す").classes("text-sm")
                    with ui.card().classes("panel"):
                        section_heading("戦闘ログ", "専門用語だけにせず、何が起きたか文章で表示します。")
                        with ui.column().classes("w-full gap-2 mt-3"):
                            for entry in state["log"]:
                                ui.label(entry).classes("log-entry")
                    secondary_button("演習をリセット", icon="restart_alt", on_click=reset_battle)

        battle_board()


@ui.page("/profile")
def profile_page() -> None:
    with page_shell(
        "/profile", "PLAYER RECORD", "プロフィール / プレイ記録",
        "勝率だけが上達の目安ではありません。索敵や補給など、自分の得意な役割も確認できます。",
    ):
        with ui.element("div").classes("profile-hero"):
            ui.label("OS").classes("avatar-command")
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("OSATO").classes("text-2xl font-bold")
                    chip("CADET II", "green")
                ui.label("登録 3日目・初心者モード使用中").classes("section-subtitle")
                ui.label("ひとこと：偵察から覚えています").classes("text-sm")
            secondary_button("プロフィールを編集", icon="edit", on_click=lambda: ui.notify("編集画面は次の実装段階で接続します。"))

        with ui.element("div").classes("metric-grid"):
            metric_card("対戦", "18 戦", "10勝・8敗")
            metric_card("偵察成功率", "72%", "前週より +8%", "green-text")
            metric_card("補給切れなし", "11 戦", "機甲を安定運用")
            metric_card("試したデッキ", "4 種", "次は『守って前進』", "yellow-text")

        with ui.element("div").classes("content-grid"):
            with ui.card().classes("panel"):
                section_heading("最近の対戦", "結果を押すと詳しい振り返りを確認できます。")
                for result, color, detail, deck, time in (
                    ("勝利", "green", "左・中央を確保", "見つけて支援", "今日 20:41"),
                    ("敗北", "red", "右戦線のみ確保", "はじめての統合部隊", "昨日 22:13"),
                    ("勝利", "green", "任務点5点を達成", "守って前進", "7月8日 19:32"),
                ):
                    with ui.element("div").classes("history-row"):
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.row().classes("items-center gap-3"):
                                chip(result, color)
                                with ui.column().classes("gap-0"):
                                    ui.label(detail).classes("font-bold text-sm")
                                    ui.label(f"使用デッキ：{deck}").classes("muted text-xs")
                            with ui.row().classes("items-center gap-2"):
                                ui.label(time).classes("muted text-xs")
                                ui.button(icon="chevron_right", on_click=lambda: go("/battle")).props("round flat aria-label=対戦を振り返る")
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("お気に入りカード")
                    favorite = get_card("recon_1")
                    with ui.row().classes("items-center gap-4 mt-3"):
                        unit_symbol(favorite)
                        with ui.column().classes("gap-0"):
                            ui.label(favorite.name).classes("font-bold")
                            ui.label("使用 14回・索敵成功 21回").classes("section-subtitle")
                            chip("熟練度 4 / 10", "yellow")
                    ui.linear_progress(value=0.4).props("rounded size=8px").classes("progress-track mt-4")
                with ui.card().classes("panel"):
                    section_heading("獲得した部隊章")
                    with ui.row().classes("gap-3 mt-3"):
                        for icon, label in (("visibility", "初索敵"), ("shield", "二戦線確保"), ("local_shipping", "補給維持")):
                            with ui.column().classes("items-center gap-1"):
                                with ui.element("div").classes("role-icon").style("--role-color:#60afff"):
                                    ui.icon(icon)
                                ui.label(label).classes("muted text-xs")


def setting_switch(title: str, description: str, value: bool = True) -> None:
    with ui.row().classes("setting-row items-center no-wrap gap-4"):
        with ui.column().classes("gap-0 flex-1"):
            ui.label(title).classes("font-bold text-sm")
            ui.label(description).classes("section-subtitle")
        ui.switch(value=value, on_change=lambda e: ui.notify(f"{title}を{'オン' if e.value else 'オフ'}にしました。"))


@ui.page("/settings")
def settings_page() -> None:
    with page_shell(
        "/settings", "PREFERENCES", "設定",
        "説明の量や表示方法を、自分が遊びやすい状態に調整できます。",
    ):
        with ui.element("div").classes("content-grid"):
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("初心者サポート", "最初はすべてオンがおすすめです。")
                    setting_switch("初心者モード", "カードの役割とおすすめ行動を常に表示します。")
                    setting_switch("軍事用語の説明", "専門用語の横に、普段の言葉で意味を表示します。")
                    setting_switch("おすすめ行動", "選べる行動に迷ったとき、候補を1つ表示します。")
                    setting_switch("解決順をゆっくり表示", "索敵や砲撃の結果を一つずつ説明します。")
                    secondary_button("チュートリアルをもう一度見る", "/learn", "school").classes("mt-3")
                with ui.card().classes("panel"):
                    section_heading("対戦")
                    setting_switch("命令確定前に確認する", "誤操作を防ぐため、確定内容を文章で表示します。")
                    setting_switch("残り10秒で警告する", "時間制限のある対戦で音と文章を表示します。")
                    setting_switch("戦闘ログを自動表示", "各ラウンドで起きたことを自動で開きます。")
                    setting_switch("観戦を許可する", "フレンドがあなたの対戦を観戦できます。", False)
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("表示とアクセシビリティ")
                    ui.select(
                        ["標準", "大きめ", "最大"], value="標準", label="文字サイズ"
                    ).props("outlined").classes("filter-control w-full mt-3")
                    setting_switch("高コントラスト", "境界線と文字の差をさらに大きくします。", False)
                    setting_switch("アニメーションを減らす", "カード公開などの動きを短くします。", False)
                    setting_switch("カード記号を大きくする", "カードの中央にある兵科記号を拡大します。", False)
                    setting_switch("色以外でも陣営を区別", "模様と『味方・敵』の文字も必ず表示します。")
                with ui.card().classes("panel"):
                    section_heading("公開範囲")
                    ui.select(
                        ["全員に公開", "フレンドのみ", "自分だけ"], value="フレンドのみ", label="プロフィール"
                    ).props("outlined").classes("filter-control w-full mt-3")
                    setting_switch("対戦履歴を公開", "フレンドが最近の対戦を確認できます。")
                    setting_switch("所持カードを公開", "プロフィールにコレクションを表示します。", False)


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        title="COMMAND GRID — 統合戦線",
        favicon="🎖️",
        dark=True,
        language="ja",
        storage_secret=os.getenv("STORAGE_SECRET", "command-grid-local-development-only"),
        reload=os.getenv("NICEGUI_RELOAD", "false").lower() == "true",
        show=False,
    )
