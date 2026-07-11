"""COMMAND GRID — a playable NiceGUI tactical card game."""

from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Callable, Iterator

from nicegui import app, ui

from account_store import (
    AccountStoreError,
    AccountValidationError,
    AuthenticationError,
    DuplicateUsernameError,
    get_default_account_store,
)
from advanced_game_data import (
    ADVANCED_CARDS,
    ADVANCED_STARTER_DECK,
    AdvancedCard,
    get_advanced_card,
    search_advanced_cards,
)
from basic_tutorial import BASIC_TUTORIAL_LESSONS, BasicLesson
from game_data import (
    CARDS,
    FORMATION_SCALES,
    GLOSSARY,
    ROLE_INFO,
    STARTER_DECK,
    UnitCard,
    analyze_deck,
    formation_label,
    get_card,
    get_formation,
)
from tutorial_data import (
    CARD_TUTORIALS,
    OFFICIAL_DECKS,
    CardTutorial,
    OfficialDeck,
    deck_missing_cards,
    deck_owned_cards_in_order,
    get_official_deck,
    get_tutorial,
)
from symbol_catalog import (
    STAGE_LABELS,
    SYMBOL_CATALOG,
    SYMBOL_FAMILIES,
    SYMBOL_INDEX,
    symbols_for_family,
)
from player_state import (
    ACCOUNT_SESSION_STORAGE_KEY,
    ACCOUNT_SYNC_ERROR_STORAGE_KEY,
    ACCOUNT_USERNAME_STORAGE_KEY,
    complete_basic_tutorial,
    complete_card_tutorial,
    default_player_state,
    ensure_player_state,
    normalize_player_state,
    record_result,
    store_player_state,
    update_basic_tutorial_stage,
    update_card_tutorial_stage,
    update_advanced_deck as update_state_advanced_deck,
    update_deck as update_state_deck,
    update_formation as update_state_formation,
    update_mode as update_state_mode,
    update_preference as update_state_preference,
    update_profile as update_state_profile,
    update_selected_symbol as update_state_selected_symbol,
)
from game_engine import MAX_ROUNDS, Phase, RuleViolation, calculate_lane_power
from simulation_engine import (
    THEATER_IDS,
    THEATER_LABELS,
    SimulationPhase,
    SimulationRuleError,
    SimulationState,
    calculate_simulation_power,
    new_simulation,
    play_simulation_round,
)
from match_service import (
    AI_PLAYER_ID,
    HUMAN_PLAYER_ID,
    abandon_match,
    collection_rewards_for_outcome,
    get_match_context,
    load_match,
    play_player_round,
    restart_match,
    start_match,
)
from multiplayer_service import (
    MultiplayerError,
    cancel_waiting,
    claim_result as claim_multiplayer_result,
    close_session as close_multiplayer_session,
    create_friend_room,
    disconnect as disconnect_multiplayer,
    join_friend_room,
    join_queue,
    leave as leave_multiplayer,
    poll as poll_multiplayer,
    submit_player_order,
)


BASE_DIR = Path(__file__).resolve().parent
app.add_static_files("/static", BASE_DIR / "static")


NAV_ITEMS = (
    ("/", "ホーム", "grid_view"),
    ("/lobby", "遊ぶ", "play_circle"),
    ("/simulation", "本格シミュレーション", "hub"),
    ("/cards", "コレクション", "style"),
    ("/tutorials", "チュートリアル", "school"),
)

MORE_NAV_ITEMS = (
    ("/account", "アカウント", "person"),
    ("/deck", "デッキ編成", "view_carousel"),
    ("/learn", "説明書・用語集", "menu_book"),
    ("/profile", "記録・プロフィール", "military_tech"),
    ("/settings", "設定", "tune"),
)

PHASES = (
    ("配置決定", "両者の配置先が同時に決まります。相手カードの正体はまだ未確認です。"),
    ("索敵", "偵察値のぶん、同じ戦線の未確認部隊を公開します。"),
    ("補給", "補給の生成量と、機甲・砲兵が必要とする量を比べます。"),
    ("戦線力", "制圧に、有効な支援と完全補給の機甲ボーナスを加えます。"),
    ("確保判定", "戦線力が高い側が、そのラウンドの戦線を確保します。"),
)

TUTORIAL_STEPS = (
    ("目的", f"難しい軍事知識は不要です。{MAX_ROUNDS}ラウンド後に相手より多くの戦線を取れば勝ちです。"),
    ("制圧", "制圧力は場所を取る土台です。最初は制圧力を持つカードを選びます。"),
    ("未確認部隊", "相手の伏せたカードは正体が分かるまで『未確認部隊』と表示されます。"),
    ("偵察", "偵察値は、同じ戦線にいる未確認の相手カードを公開します。"),
    ("支援", "支援力は、同じ戦線に味方の制圧力があるときだけ戦線力へ加わります。"),
    ("補給", "補給需要を満たせないと不足分だけ戦線力が下がります。"),
    ("機甲", "機甲は補給需要を完全に満たすと、1部隊につき戦線力が2上がります。"),
    ("同時命令", "あなたと相手の配置先は同時に決まります。相手カードの正体は偵察まで未確認です。"),
)

SIMULATION_MATCH_STORAGE_KEY = "advanced_simulation_match"
SIMULATION_RECORDED_STORAGE_KEY = "advanced_simulation_recorded"
SIMULATION_REWARDS_STORAGE_KEY = "advanced_simulation_rewards"


def signed_in_username() -> str | None:
    username = app.storage.user.get(ACCOUNT_USERNAME_STORAGE_KEY)
    token = app.storage.user.get(ACCOUNT_SESSION_STORAGE_KEY)
    if not isinstance(username, str) or not username or not isinstance(token, str):
        return None
    try:
        account = get_default_account_store().resolve_session(token)
    except AccountStoreError:
        return None
    if account is None or account.username.casefold() != username.casefold():
        return None
    return account.username


def account_backend_label() -> str:
    try:
        backend = get_default_account_store().backend
    except AccountStoreError:
        return "保存先に接続できません"
    return "PostgreSQL 永続保存" if backend == "postgresql" else "ローカルSQLite保存"


def establish_account_session(username: str) -> dict[str, object]:
    """Load an authenticated account into this NiceGUI user session."""

    store = get_default_account_store()
    raw_state = store.load_player_state(username)
    state = normalize_player_state(raw_state)
    token = store.create_session(username)
    app.storage.user[ACCOUNT_USERNAME_STORAGE_KEY] = username
    app.storage.user[ACCOUNT_SESSION_STORAGE_KEY] = token
    stored = store_player_state(app.storage.user, state)
    return stored


def log_out_account() -> None:
    token = app.storage.user.get(ACCOUNT_SESSION_STORAGE_KEY)
    if isinstance(token, str):
        try:
            get_default_account_store().delete_session(token)
        except AccountStoreError:
            pass
    app.storage.user.pop(ACCOUNT_USERNAME_STORAGE_KEY, None)
    app.storage.user.pop(ACCOUNT_SESSION_STORAGE_KEY, None)
    app.storage.user.pop(ACCOUNT_SYNC_ERROR_STORAGE_KEY, None)
    store_player_state(app.storage.user, default_player_state())

def get_preferences() -> dict[str, object]:
    return dict(ensure_player_state(app.storage.user)["preferences"])


def apply_preferences(preferences: dict[str, object]) -> None:
    removable = (
        "cg-beginner-off cg-terms-off cg-recommendations-off cg-high-contrast "
        "cg-reduce-motion cg-large-symbols cg-patterns-off"
    )
    active: list[str] = []
    if not preferences["beginner_mode"]:
        active.append("cg-beginner-off")
    if not preferences["explain_military_terms"]:
        active.append("cg-terms-off")
    if not preferences["recommended_actions"]:
        active.append("cg-recommendations-off")
    if preferences["high_contrast"]:
        active.append("cg-high-contrast")
    if preferences["reduce_motion"]:
        active.append("cg-reduce-motion")
    if preferences["large_symbols"]:
        active.append("cg-large-symbols")
    if not preferences["faction_patterns"]:
        active.append("cg-patterns-off")
    ui.query("body").classes(add=" ".join(active), remove=removable)
    font_class = {
        "standard": "",
        "large": "cg-font-large",
        "maximum": "cg-font-maximum",
    }[str(preferences["font_size"])]
    ui.query("html").classes(add=font_class, remove="cg-font-large cg-font-maximum")


def set_preference(key: str, value: object) -> None:
    state = ensure_player_state(app.storage.user)
    try:
        state = update_state_preference(state, key, value)  # type: ignore[arg-type]
    except ValueError:
        return
    stored = store_player_state(app.storage.user, state)
    apply_preferences(stored["preferences"])


@app.get("/healthz")
def healthz() -> dict[str, str]:
    # Render must only consider the service healthy after persistent account
    # storage has been configured and initialized successfully.
    get_default_account_store()
    return {"status": "ok"}


def go(path: str) -> None:
    ui.navigate.to(path)


def begin_training(*, reset: bool = True) -> None:
    online_view = poll_multiplayer(app.storage.user)
    online_status = online_view.get("status")
    if online_status in {"playing", "complete", "opponent_left"}:
        ui.notify("先に進行中のオンライン対戦を確認してください。", type="warning")
        go("/pvp")
        return
    if online_status in {"waiting", "waiting_friend"}:
        try:
            cancel_waiting(app.storage.user)
        except MultiplayerError:
            pass
    elif online_status == "left":
        try:
            close_multiplayer_session(app.storage.user)
        except MultiplayerError:
            pass
    state = update_state_mode(ensure_player_state(app.storage.user), "training")
    store_player_state(app.storage.user, state)
    try:
        if reset:
            restart_match(app.storage.user)
        else:
            start_match(app.storage.user)
    except RuleViolation:
        ui.notify(f"演習にはカードを{MAX_ROUNDS}枚以上入れたデッキが必要です。", type="warning")
        go("/deck")
        return
    go("/battle")


def register_client_poll(
    callback: Callable[[], None], *, cleanup: Callable[[], None] | None = None
) -> None:
    """Start a per-page poller only after the browser socket connects."""

    client = ui.context.client
    holder: dict[str, object] = {"timer": None}

    def stop() -> None:
        timer = holder.get("timer")
        if timer is not None:
            timer.cancel(with_current_invocation=True)
            holder["timer"] = None

    def start() -> None:
        stop()
        with client:
            holder["timer"] = ui.timer(1.0, callback, immediate=False)

    client.on_connect(start)
    client.on_delete(stop)
    if cleanup is not None:
        client.on_delete(cleanup)


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


def unit_symbol(card: UnitCard, size: str = "md", formation_id: str | None = None) -> None:
    marker, formation_name = formation_label(card, formation_id)
    with ui.element("div").classes(f"unit-symbol unit-symbol--{size}").props(
        f'data-echelon="{marker}" role="img" aria-label="{card.branch}・{formation_name}の部隊記号"'
    ):
        ui.label(card.symbol)


def account_icon(
    symbol_id: object,
    fallback: str,
    *,
    classes: str = "battle-account__icon",
) -> None:
    """Render the collection symbol selected as an account avatar."""

    symbol = SYMBOL_INDEX.get(str(symbol_id or ""))
    token = symbol.token if symbol else str(fallback or "?")[:2].upper()
    label = f"アカウントアイコン：{symbol.name}" if symbol else "アカウントアイコン"
    ui.label(token).classes(classes).props(f'role="img" aria-label="{label}"')


def advanced_symbol(card: AdvancedCard, *, classes: str = "simulation-card__symbol") -> None:
    symbol = SYMBOL_INDEX.get(card.symbol_id)
    ui.label(symbol.token if symbol else "□").classes(classes).props(
        f'role="img" aria-label="{card.name}の記号"'
    )


def primary_card_stats(
    card: UnitCard | AdvancedCard,
) -> tuple[tuple[str, str], ...]:
    """Return the four combat values shown on every playable card face."""

    return (
        ("制圧", str(card.control)),
        ("支援", str(card.support)),
        ("偵察", str(card.recon)),
        ("補給", f"{card.supply:+d}"),
    )


def advanced_stats(card: AdvancedCard) -> None:
    with ui.element("div").classes("simulation-card__stats"):
        for label, value in primary_card_stats(card):
            with ui.element("div").classes(
                "simulation-card__stat simulation-card__stat--primary"
            ):
                ui.label(label).classes("muted")
                ui.label(value).classes("mono font-bold")
        for label, value in (("指揮", card.command), ("機動", card.mobility)):
            with ui.element("div").classes(
                "simulation-card__stat simulation-card__stat--extra"
            ):
                ui.label(label).classes("muted")
                ui.label(str(value)).classes("mono font-bold")


def card_stats(card: UnitCard) -> None:
    with ui.element("div").classes("card-stats"):
        for label, value in primary_card_stats(card):
            with ui.element("div").classes("card-stat"):
                ui.label(label).classes("card-stat__label")
                ui.label(value).classes("card-stat__value")


def card_detail_dialog(card: UnitCard) -> ui.dialog:
    preferences = get_preferences()
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
                ui.label(f"{card.echelon}・扱いやすさ {card.difficulty}").classes("muted text-sm")
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
            if preferences["explain_military_terms"]:
                with ui.column().classes("gap-1 term-explanation"):
                    ui.label("軍事メモ").classes("yellow-text text-xs font-bold")
                    ui.label(card.military_note).classes("section-subtitle")
                with ui.element("div").classes("beginner-callout term-explanation"):
                    ui.label("記号の見方").classes("font-bold")
                    ui.label("外側の枠は部隊、中央は主な役割、上側の文字は本作での部隊規模を示します。").classes("text-sm")
        with ui.row().classes("gap-2"):
            if card.owned:
                primary_button(
                    "このカードを練習",
                    icon="school",
                    on_click=lambda: go(f"/tutorials/card/{card.id}"),
                )
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


def beginner_card(card: UnitCard) -> None:
    """A low-information card used before the player opens full details."""
    dialog = card_detail_dialog(card)
    info = ROLE_INFO[card.branch]
    with ui.card().classes("beginner-card"):
        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            unit_symbol(card)
            with ui.column().classes("gap-1 min-w-0 flex-1"):
                ui.label(card.branch).classes("page-eyebrow")
                ui.label(info["verb"]).classes("text-xl font-bold")
                ui.label(info["plain"]).classes("section-subtitle")
        ui.button("このカードだけ詳しく見る", icon="arrow_forward", on_click=dialog.open).props(
            "flat no-caps"
        ).classes("card-action")
        if card.owned:
            ui.button(
                "使い方を5章で練習",
                icon="school",
                on_click=lambda: go(f"/tutorials/card/{card.id}"),
            ).props("flat no-caps").classes("card-action")


def action_step(number: int, label: str, *, active: bool = False, done: bool = False) -> None:
    state_class = " action-step--active" if active else " action-step--done" if done else ""
    with ui.element("div").classes(f"action-step{state_class}"):
        ui.label("✓" if done else str(number)).classes("action-step__number")
        ui.label(label).classes("action-step__label")


def tutorial_progress(completed_steps: int, total_steps: int) -> tuple[int, float]:
    """Clamp persisted progress for safe display after future course edits."""

    completed = max(0, min(total_steps, int(completed_steps)))
    return completed, completed / total_steps if total_steps else 1.0


def apply_official_deck(
    deck: OfficialDeck, *, on_applied: Callable[[], None] | None = None
) -> None:
    """Select the owned portion of an unlocked twelve-slot official recipe."""

    state = ensure_player_state(app.storage.user)
    if deck.id not in state["tutorials"]["unlocked_official_decks"]:
        ui.notify("この公式デッキは、対応するカード訓練を終えると選べます。", type="warning")
        return
    owned = set(state["collection"]["owned_cards"])
    selected_cards = list(deck_owned_cards_in_order(deck, owned))
    missing = deck_missing_cards(deck, owned)
    try:
        state = update_state_deck(state, selected_cards)
    except ValueError as error:
        ui.notify(str(error), type="negative")
        return
    store_player_state(app.storage.user, state)
    if missing:
        ui.notify(
            f"所持している{len(selected_cards)}枚をセットしました。未所持の{len(missing)}枠は空白です。",
            type="warning",
        )
    else:
        ui.notify("公式デッキ12枚をセットしました。", type="positive")
    if on_applied is not None:
        on_applied()


def official_deck_preview(
    deck: OfficialDeck,
    *,
    allow_apply: bool = True,
    on_applied: Callable[[], None] | None = None,
) -> None:
    """Render all recipe positions, preserving unowned cards as named blanks."""

    player = ensure_player_state(app.storage.user)
    owned = set(player["collection"]["owned_cards"])
    missing = deck_missing_cards(deck, owned)
    selected_cards = list(deck_owned_cards_in_order(deck, owned))
    is_selected = list(player["deck"]) == selected_cards

    with ui.column().classes("w-full gap-3"):
        with ui.row().classes("w-full items-start justify-between gap-3"):
            with ui.column().classes("gap-1 flex-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(deck.name).classes("section-title")
                    if is_selected:
                        chip("選択中", "green")
                ui.label(deck.summary).classes("section-subtitle")
            chip(f"{len(selected_cards)} / 12枚", "green" if not missing else "yellow")

        if missing:
            with ui.element("div").classes("missing-card-notice"):
                ui.icon("inventory_2", size="22px")
                with ui.column().classes("gap-1"):
                    ui.label(f"未所持カード：{'・'.join(card.name for card in missing)}").classes("font-bold text-sm")
                    ui.label("選択すると、この場所は代用品を入れず空白のままになります。").classes("text-xs")
        else:
            with ui.element("div").classes("beginner-callout"):
                ui.label("12枚すべて所持しています。完成した形で使えます。").classes("text-sm font-bold")

        with ui.element("div").classes("official-deck-grid"):
            for slot, card_id in enumerate(deck.card_ids, 1):
                card = get_card(card_id)
                if card_id in owned:
                    with ui.element("div").classes("official-deck-slot"):
                        ui.label(f"{slot:02}").classes("official-deck-slot__number")
                        unit_symbol(card, "sm")
                        ui.label(card.name).classes("official-deck-slot__name")
                        ui.label(card.branch).classes("muted text-xs")
                else:
                    with ui.element("div").classes("official-deck-slot official-deck-slot--missing"):
                        ui.label(f"{slot:02}").classes("official-deck-slot__number")
                        ui.icon("crop_square", size="34px")
                        ui.label("空白").classes("font-bold")
                        ui.label(f"未所持：{card.name}").classes("official-deck-slot__missing-name")

        with ui.element("div").classes("tutorial-strategy"):
            ui.label("このデッキの基本作戦").classes("blue-text text-xs font-bold")
            ui.label(deck.strategy).classes("section-subtitle")

        if allow_apply:
            with ui.row().classes("items-center gap-3"):
                primary_button(
                    "この公式デッキを選択",
                    icon="check_circle",
                    on_click=lambda: apply_official_deck(deck, on_applied=on_applied),
                )
                if missing and len(selected_cards) < MAX_ROUNDS:
                    ui.label(f"空白が多いため、対戦前に{MAX_ROUNDS}枚以上へ調整してください。").classes("danger-text text-xs")
                elif missing:
                    ui.label(f"空白があっても、所持分が{MAX_ROUNDS}枚以上なら対戦できます。").classes("muted text-xs")


def card_tutorial_tile(tutorial: CardTutorial, player: dict[str, object]) -> None:
    """Render one compact course card for the tutorial hub."""

    card = get_card(tutorial.card_id)
    tutorials = player["tutorials"]  # type: ignore[index]
    completed_cards = set(tutorials["completed_cards"])  # type: ignore[index]
    saved_steps = tutorials["card_stages"].get(card.id, 0)  # type: ignore[index]
    complete = card.id in completed_cards
    completed, value = tutorial_progress(
        len(tutorial.stages) if complete else saved_steps, len(tutorial.stages)
    )
    reward = get_official_deck(tutorial.reward_deck_id)
    with ui.card().classes("tutorial-course-card"):
        with ui.row().classes("items-center gap-3 no-wrap"):
            unit_symbol(card, "sm")
            with ui.column().classes("gap-0 min-w-0 flex-1"):
                ui.label(card.name).classes("font-bold")
                ui.label(f"{card.branch}・全{len(tutorial.stages)}章").classes("muted text-xs")
            chip("完了", "green") if complete else chip(f"{completed}/{len(tutorial.stages)}")
        ui.linear_progress(value=value).props("rounded size=7px").classes("progress-track")
        ui.label(f"修了報酬：{reward.name}").classes("section-subtitle")
        ui.button(
            "報酬を見る・復習" if complete else "続きから始める" if completed else "このカードを学ぶ",
            icon="school",
            on_click=lambda: go(f"/tutorials/card/{card.id}"),
        ).props("flat no-caps").classes("card-action")


@contextmanager
def page_shell(active: str, eyebrow: str, title: str, subtitle: str) -> Iterator[None]:
    ui.add_head_html('<link rel="stylesheet" href="/static/styles.css?v=20260711-2">')
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
    player_state = ensure_player_state(app.storage.user)
    preferences = dict(player_state["preferences"])
    selected_symbol_id = str(player_state["profile"].get("selected_symbol", ""))
    selected_symbol = SYMBOL_INDEX.get(selected_symbol_id)
    profile_mark = selected_symbol.token if selected_symbol else str(player_state["profile"]["display_name"])[:2].upper()
    account_username = signed_in_username()
    profile_path = "/profile" if account_username else "/account"
    apply_preferences(preferences)

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
        more_routes = {route for route, _, _ in MORE_NAV_ITEMS}
        with ui.expansion(
            "その他", icon="more_horiz", value=active in more_routes,
        ).classes("w-full muted text-sm mt-2"):
            for route, label, icon in MORE_NAV_ITEMS:
                active_class = " nav-button--active" if route == active else ""
                ui.button(label, icon=icon, on_click=lambda path=route: go(path)).props(
                    "flat no-caps align=left"
                ).classes(f"nav-button{active_class}")
        if preferences["beginner_mode"]:
            with ui.element("div").classes("drawer-brief beginner-only"):
                with ui.row().classes("items-center gap-2"):
                    ui.label("初心者サポート ON").classes("font-bold text-xs")
                ui.label("まず青いボタンだけ見れば進めます。詳しい説明は必要なときに開けます。")
        with ui.element("div").classes("drawer-account"):
            ui.label(profile_mark).classes("drawer-account__icon")
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(
                    f"@{account_username}" if account_username else "ゲストプレイ"
                ).classes("font-bold text-xs")
                ui.label(
                    "進行状況をDBへ保存" if account_username else "ログインすると端末を閉じても復元できます"
                ).classes("muted text-xs")

    with ui.header().classes("cg-header items-center no-wrap"):
        ui.button(icon="menu", on_click=drawer.toggle).props("flat round aria-label=メニュー")
        ui.button(icon="home", on_click=lambda: go("/")).props("flat round aria-label=ホームへ戻る").tooltip("ホーム")
        with ui.row().classes("items-center no-wrap gap-3"):
            ui.label("CG").classes("brand-mark").style("width:34px;height:34px;flex-basis:34px;font-size:11px")
            with ui.column().classes("gap-0"):
                ui.label("COMMAND GRID").classes("font-bold text-sm")
                ui.label("統合戦線・ONLINE CARD GAME").classes("header-subtitle muted text-xs")
        ui.space()
        with ui.row().classes("items-center gap-2"):
            chip(
                "上級解放" if player_state["progression"]["simulation_unlocked"]
                else "初心者モード" if preferences["beginner_mode"] else "標準表示",
                "yellow" if player_state["progression"]["simulation_unlocked"] else "green" if preferences["beginner_mode"] else "",
            )
            ui.button(profile_mark, on_click=lambda: go(profile_path)).props("round unelevated aria-label=アカウント").classes(
                "bg-blue-9 text-white"
            )

    with ui.element("nav").classes("mobile-bottom-nav"):
        for route, label, icon in (
            ("/", "ホーム", "home"),
            ("/lobby", "対戦", "swords"),
            ("/tutorials", "練習", "school"),
            ("/cards", "収集", "style"),
            (profile_path, "アカウント", "person"),
        ):
            active_class = " mobile-bottom-nav__button--active" if route == active else ""
            with ui.button(
                icon=icon, on_click=lambda path=route: go(path)
            ).props(f"flat no-caps aria-label={label}").classes(
                f"mobile-bottom-nav__button{active_class}"
            ):
                ui.label(label).classes("mobile-bottom-nav__label")

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


@ui.page("/home")
@ui.page("/")
def home_page() -> None:
    player = ensure_player_state(app.storage.user)
    needs_basic_tutorial = not bool(player["tutorials"]["basic_completed"])
    active_match = load_match(app.storage.user)
    online_view = poll_multiplayer(app.storage.user)
    online_status = str(online_view.get("status", "idle"))
    online_active = online_status in {
        "waiting", "waiting_friend", "playing", "complete", "opponent_left"
    }
    online_path = (
        "/online" if online_status == "waiting"
        else "/friend" if online_status == "waiting_friend"
        else "/pvp"
    )
    stats = player["stats"]
    rank_label = ("CADET I", "CADET II", "CADET III", "OFFICER I", "OFFICER II")[
        min(4, stats["wins"] // 3)
    ]
    cta_label = (
        "オンライン待機へ戻る" if online_status in {"waiting", "waiting_friend"}
        else "オンライン対戦を続ける" if online_active
        else "演習を続ける" if active_match and active_match.phase is not Phase.COMPLETE
        else "遊び方を一つずつ練習する" if needs_basic_tutorial
        else "5分演習を始める"
    )

    def home_primary_action() -> None:
        if online_active:
            go(online_path)
            return
        if needs_basic_tutorial and not (
            active_match and active_match.phase is not Phase.COMPLETE
        ):
            go("/tutorials/basic")
            return
        begin_training(reset=not (active_match and active_match.phase is not Phase.COMPLETE))
    with page_shell(
        "/", "START HERE", "まずはここから",
        "最初は青いボタンを一つ押すだけで大丈夫です。ほかの情報は必要になってから開けます。",
    ):
        with ui.element("section").classes("start-here"):
            with ui.column().classes("start-here__copy gap-2"):
                chip("最初に見る場所", "green")
                ui.label(
                    "9章で遊び方を一つずつ試す" if needs_basic_tutorial
                    else "5分演習で、カードを1枚置いてみる"
                ).classes("start-here__title")
                ui.label(
                    "勝ち方から始め、一画面に一つの課題だけを表示します。数値や用語を一度に覚える必要はありません。"
                    if needs_basic_tutorial else
                    "覚えるのは『カードを選ぶ → 場所を選ぶ → 決定する』の3つだけ。"
                    "軍事用語や細かい数値は、まだ読まなくて構いません。"
                ).classes("start-here__description")
                primary_button(
                    cta_label, icon="play_arrow", on_click=home_primary_action,
                ).classes("start-here__button")
            with ui.element("div").classes("start-here__steps"):
                if needs_basic_tutorial:
                    action_step(1, "勝ち方を知る", active=True)
                    action_step(2, "一手を操作する")
                    action_step(3, "結果を理解する")
                else:
                    action_step(1, "カードを選ぶ", active=True)
                    action_step(2, "場所を選ぶ")
                    action_step(3, "決定する")

        with ui.card().classes("panel simple-rule"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon("flag", size="28px").classes("blue-text")
                with ui.column().classes("gap-0"):
                    ui.label("ゲームの目的").classes("font-bold")
                    ui.label(f"{MAX_ROUNDS}ラウンド後に、相手より多くの戦線を取れば勝ちです。").classes("section-subtitle")

        with ui.expansion("ほかの情報を見る", icon="unfold_more").classes("details-expansion"):
            with ui.element("div").classes("metric-grid mt-3"):
                metric_card("プレイヤー階級", rank_label, f"勝利 {stats['wins']}回", "blue-text")
                metric_card("カード図鑑", f"{len(player['collection']['owned_cards'])} / {len(CARDS)}", "対戦完了ごとに増えます")
                metric_card("対戦記録", f"{stats['battles_played']} 戦", f"{stats['wins']}勝・{stats['losses']}敗", "green-text")
                metric_card("記号図鑑", f"{len(player['collection']['unlocked_symbols'])} / {len(SYMBOL_CATALOG)}", "一度に覚えなくて大丈夫", "yellow-text")
            with ui.row().classes("gap-3 mt-4"):
                secondary_button("チュートリアル", "/tutorials", "school")
                secondary_button("通常対戦へ", "/lobby", "swords")
                secondary_button("カードを見る", "/cards", "style")


@ui.page("/tutorials")
def tutorials_page() -> None:
    with page_shell(
        "/tutorials", "TRAINING CENTER", "一つずつ覚える訓練所",
        "最初にゲーム全体を9章で練習し、その後は所持カードを1枚ずつ試せます。今必要な課題だけ開きます。",
    ):
        player = ensure_player_state(app.storage.user)
        tutorial_state = player["tutorials"]
        basic_complete = bool(tutorial_state["basic_completed"])
        basic_done, basic_value = tutorial_progress(
            len(BASIC_TUTORIAL_LESSONS) if basic_complete else tutorial_state["basic_stage"],
            len(BASIC_TUTORIAL_LESSONS),
        )

        with ui.element("section").classes("tutorial-hero"):
            with ui.column().classes("gap-2 flex-1"):
                chip("最初はこちら", "green" if not basic_complete else "")
                ui.label("はじめての作戦").classes("start-here__title")
                ui.label(
                    "勝ち方から、カードを選ぶ・戦線を選ぶ・命令を確定するところまで、"
                    "一画面に一つの操作だけで練習します。"
                ).classes("start-here__description")
                with ui.row().classes("items-center gap-3 w-full max-w-2xl mt-2"):
                    ui.linear_progress(value=basic_value).props("rounded size=9px").classes("progress-track flex-1")
                    ui.label(f"{basic_done} / {len(BASIC_TUTORIAL_LESSONS)}章").classes("mono text-sm")
                primary_button(
                    "完了内容を見る" if basic_complete else "続きから始める" if basic_done else "第1章から始める",
                    "/tutorials/basic",
                    "play_arrow",
                ).classes("start-here__button")
            with ui.element("div").classes("tutorial-hero__map"):
                action_step(1, "入門：勝ち方と命令", active=basic_done < 4, done=basic_done >= 4)
                action_step(2, "戦線力：支援と補給", active=4 <= basic_done < 7, done=basic_done >= 7)
                action_step(3, "実戦判断：偵察と勝敗", active=7 <= basic_done < 9, done=basic_complete)

        owned = set(player["collection"]["owned_cards"])
        completed_cards = set(tutorial_state["completed_cards"])
        card_stages = tutorial_state["card_stages"]
        owned_tutorials = [tutorial for tutorial in CARD_TUTORIALS if tutorial.card_id in owned]
        unfinished = [
            tutorial for tutorial in owned_tutorials
            if tutorial.card_id not in completed_cards
        ]
        recommended = sorted(
            unfinished,
            key=lambda tutorial: (
                0 if int(card_stages.get(tutorial.card_id, 0)) > 0 else 1,
                -int(card_stages.get(tutorial.card_id, 0)),
                list(ROLE_INFO).index(get_card(tutorial.card_id).branch),
            ),
        )[:3]

        section_heading(
            "次におすすめのカード訓練",
            "基礎コースとは別に、今持っているカードの数字・置き場所・組み合わせを5章で学べます。",
        )
        if recommended:
            with ui.element("div").classes("tutorial-course-grid"):
                for tutorial in recommended:
                    card_tutorial_tile(tutorial, player)
        else:
            with ui.element("div").classes("beginner-callout"):
                ui.label("所持カードの訓練をすべて完了しました。").classes("font-bold")
                ui.label("新しいカードを入手すると、そのカードの訓練がここに追加されます。").classes("text-sm")

        with ui.expansion(
            f"所持カード別の全コースを見る（{len(owned_tutorials)}枚）",
            icon="view_module",
        ).classes("details-expansion"):
            ui.label("兵科を一つだけ開いて選べます。全部を一度に見る必要はありません。").classes("section-subtitle mt-2")
            with ui.column().classes("w-full gap-2 mt-3"):
                for branch in ROLE_INFO:
                    branch_tutorials = [
                        tutorial for tutorial in owned_tutorials
                        if get_card(tutorial.card_id).branch == branch
                    ]
                    if not branch_tutorials:
                        continue
                    branch_complete = sum(
                        tutorial.card_id in completed_cards for tutorial in branch_tutorials
                    )
                    with ui.expansion(
                        f"{branch}　{branch_complete} / {len(branch_tutorials)}完了",
                        icon=str(ROLE_INFO[branch]["icon"]),
                    ).classes("tutorial-branch-expansion"):
                        with ui.element("div").classes("tutorial-course-grid mt-3"):
                            for tutorial in branch_tutorials:
                                card_tutorial_tile(tutorial, player)

        unlocked_ids = set(tutorial_state["unlocked_official_decks"])
        unlocked_decks = [deck for deck in OFFICIAL_DECKS if deck.id in unlocked_ids]
        section_heading(
            "受け取った公式デッキ",
            "カード訓練を一つ終えるたび、そのカードを含む12枠のおすすめ構成が増えます。",
        )
        if not unlocked_decks:
            with ui.card().classes("panel panel--compact"):
                ui.label("まだ公式デッキはありません").classes("font-bold")
                ui.label("上のカード訓練を1つ完了すると、最初の公式デッキを受け取れます。").classes("section-subtitle")
        else:
            with ui.column().classes("w-full gap-2"):
                for deck in unlocked_decks:
                    missing_count = len(deck_missing_cards(deck, owned))
                    with ui.expansion(
                        f"{deck.name}　{'完成' if not missing_count else f'空白 {missing_count}枠'}",
                        icon="view_carousel",
                    ).classes("details-expansion"):
                        with ui.card().classes("panel mt-3"):
                            official_deck_preview(deck)

        locked_tutorials = [
            tutorial for tutorial in CARD_TUTORIALS if tutorial.card_id not in owned
        ]
        if locked_tutorials:
            with ui.expansion(
                f"まだ持っていないカードの訓練（{len(locked_tutorials)}枚）",
                icon="lock",
            ).classes("details-expansion"):
                ui.label("対戦完了でカードを入手すると、対応する訓練が自動で開きます。").classes("section-subtitle mt-2")
                with ui.element("div").classes("locked-tutorial-grid mt-3"):
                    for tutorial in locked_tutorials:
                        card = get_card(tutorial.card_id)
                        with ui.element("div").classes("locked-tutorial-row"):
                            ui.icon("lock_outline")
                            with ui.column().classes("gap-0"):
                                ui.label(card.name).classes("font-bold text-sm")
                                ui.label(f"{card.branch}・カード入手後に開放").classes("muted text-xs")


@ui.page("/tutorials/basic")
def basic_tutorial_page() -> None:
    total_lessons = len(BASIC_TUTORIAL_LESSONS)
    initial = ensure_player_state(app.storage.user)["tutorials"]
    initial_index = min(int(initial["basic_stage"]), total_lessons - 1)
    view: dict[str, object] = {
        "index": initial_index,
        "answer": "",
        "feedback": "",
        "correct": False,
        "selected_card": "",
        "selected_lane": "",
        "revealed": False,
        "completion": bool(initial["basic_completed"]),
    }

    def reset_interaction() -> None:
        view.update(
            answer="",
            feedback="",
            correct=False,
            selected_card="",
            selected_lane="",
            revealed=False,
        )

    def show_lesson(index: int) -> None:
        view["completion"] = False
        view["index"] = max(0, min(total_lessons - 1, index))
        reset_interaction()
        lesson_view.refresh()
        ui.run_javascript("window.scrollTo({top: 0, behavior: 'auto'})")

    def answer_choice(lesson: BasicLesson, choice: str) -> None:
        view["answer"] = choice
        if choice == lesson.correct_choice:
            view["correct"] = True
            view["feedback"] = lesson.success_message
        else:
            view["correct"] = False
            view["feedback"] = lesson.hint
        lesson_view.refresh()

    def select_training_card(card_id: str) -> None:
        if view["correct"]:
            return
        view["selected_card"] = card_id
        view["feedback"] = "次に、配置する戦線を選びます。"
        lesson_view.refresh()

    def select_training_lane(lane_id: str) -> None:
        if view["correct"]:
            return
        view["selected_lane"] = lane_id
        view["feedback"] = "最後に『命令を確定』を押します。"
        lesson_view.refresh()

    def confirm_training_order(lesson: BasicLesson) -> None:
        if view["selected_card"] == "infantry_1" and view["selected_lane"] == "center":
            view["correct"] = True
            view["feedback"] = lesson.success_message
        else:
            view["correct"] = False
            view["feedback"] = lesson.hint
        lesson_view.refresh()

    def reveal_training_order(lesson: BasicLesson) -> None:
        view["revealed"] = True
        view["correct"] = True
        view["feedback"] = lesson.success_message
        lesson_view.refresh()

    def advance_basic() -> None:
        index = int(view["index"])
        if not view["correct"]:
            return
        state = ensure_player_state(app.storage.user)
        if index == total_lessons - 1:
            state = complete_basic_tutorial(state, final_stage=total_lessons)
            store_player_state(app.storage.user, state)
            view["completion"] = True
        else:
            state = update_basic_tutorial_stage(state, index + 1)
            store_player_state(app.storage.user, state)
            view["index"] = index + 1
            reset_interaction()
        lesson_view.refresh()
        ui.run_javascript("window.scrollTo({top: 0, behavior: 'auto'})")

    def render_choice_task(lesson: BasicLesson) -> None:
        with ui.element("div").classes("tutorial-choice-grid"):
            for choice, label in lesson.choices:
                selected = view["answer"] == choice
                state_class = " tutorial-choice--selected" if selected else ""
                if selected and view["correct"]:
                    state_class += " tutorial-choice--correct"
                with ui.button(
                    on_click=lambda value=choice: answer_choice(lesson, value)
                ).props("no-caps unelevated").classes(f"tutorial-choice{state_class}"):
                    ui.label(label).classes("font-bold")

    def render_card_choice_task(lesson: BasicLesson) -> None:
        with ui.element("div").classes("tutorial-card-choice-grid"):
            for card_id, _ in lesson.choices:
                card = get_card(card_id)
                selected = view["answer"] == card_id
                state_class = " tutorial-card-choice--selected" if selected else ""
                if selected and view["correct"]:
                    state_class += " tutorial-card-choice--correct"
                option = ui.card().classes(f"tutorial-card-choice{state_class}")
                option.on("click", lambda _, value=card_id: answer_choice(lesson, value))
                with option:
                    with ui.row().classes("items-center gap-3 no-wrap"):
                        unit_symbol(card, "sm")
                        with ui.column().classes("gap-0 min-w-0"):
                            ui.label(card.name).classes("font-bold text-sm")
                            ui.label(card.branch).classes("muted text-xs")
                    ui.label(
                        f"制圧 {card.control}　支援 {card.support}　偵察 {card.recon}　補給 {card.supply:+d}"
                    ).classes("tutorial-card-numbers")

    def render_deploy_task(lesson: BasicLesson) -> None:
        selected_card = str(view["selected_card"])
        selected_lane = str(view["selected_lane"])
        with ui.element("div").classes("mini-order-steps"):
            action_step(1, "カード", active=not selected_card, done=bool(selected_card))
            action_step(2, "戦線", active=bool(selected_card) and not selected_lane, done=bool(selected_lane))
            action_step(3, "確定", active=bool(selected_card and selected_lane), done=bool(view["correct"]))
        ui.label("手札から1枚選ぶ").classes("font-bold mt-3")
        with ui.element("div").classes("tutorial-mini-hand"):
            for card_id in ("infantry_1", "recon_1"):
                card = get_card(card_id)
                selected_class = " tutorial-mini-card--selected" if selected_card == card_id else ""
                option = ui.card().classes(f"tutorial-mini-card{selected_class}")
                option.on("click", lambda _, value=card_id: select_training_card(value))
                with option:
                    unit_symbol(card, "sm")
                    ui.label(card.name).classes("font-bold text-sm")
                    card_stats(card)
        ui.label("置く戦線を選ぶ").classes("font-bold mt-3")
        with ui.element("div").classes("tutorial-lane-grid"):
            for lane_id, lane_name in (("left", "左戦線"), ("center", "中央戦線"), ("right", "右戦線")):
                selected_class = " tutorial-lane--selected" if selected_lane == lane_id else ""
                with ui.button(
                    lane_name,
                    icon="place",
                    on_click=lambda value=lane_id: select_training_lane(value),
                ).props("no-caps unelevated").classes(f"tutorial-lane{selected_class}"):
                    pass
        with ui.row().classes("items-center gap-3 mt-3"):
            confirm = primary_button(
                "命令を確定",
                icon="check",
                on_click=lambda: confirm_training_order(lesson),
            )
            if not selected_card or not selected_lane or view["correct"]:
                confirm.props("disable")
            if selected_card and selected_lane:
                card = get_card(selected_card)
                lane_name = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}[selected_lane]
                ui.label(f"予定：{card.name} → {lane_name}").classes("section-subtitle")

    def render_reveal_task(lesson: BasicLesson) -> None:
        with ui.element("div").classes("sealed-orders"):
            with ui.element("div").classes("sealed-order"):
                ui.icon("lock")
                ui.label("あなたの命令").classes("font-bold")
                ui.label("確定済み").classes("muted text-xs")
            with ui.element("div").classes("sealed-order"):
                ui.icon("lock")
                ui.label("相手の命令").classes("font-bold")
                ui.label("確定済み").classes("muted text-xs")
        if not view["revealed"]:
            primary_button(
                "両方の配置先を公開",
                icon="visibility",
                on_click=lambda: reveal_training_order(lesson),
            ).classes("mt-3")
            return
        with ui.element("div").classes("tutorial-lane-grid mt-3"):
            for lane_name, content, owner in (
                ("左戦線", "配備なし", ""),
                ("中央戦線", "第1歩兵中隊", "あなた"),
                ("右戦線", "未確認部隊", "相手"),
            ):
                with ui.element("div").classes("tutorial-lane tutorial-lane--revealed"):
                    ui.label(lane_name).classes("font-bold")
                    ui.label(content).classes("text-sm")
                    if owner:
                        chip(owner, "green" if owner == "あなた" else "red")

    def render_basic_task(lesson: BasicLesson) -> None:
        if lesson.kind == "card_choice":
            render_card_choice_task(lesson)
        elif lesson.kind == "deploy":
            render_deploy_task(lesson)
        elif lesson.kind == "reveal":
            render_reveal_task(lesson)
        else:
            render_choice_task(lesson)

    with page_shell(
        "/tutorials", "BASIC COURSE", "はじめての作戦",
        "一度に覚えるのは一つだけです。正しく操作すると、次の章へ進めます。",
    ):
        @ui.refreshable
        def lesson_view() -> None:
            if view["completion"]:
                with ui.element("section").classes("tutorial-complete"):
                    ui.icon("workspace_premium", size="54px").classes("green-text")
                    ui.label("基礎9章を完了しました").classes("text-3xl font-bold")
                    ui.label(
                        "カードを1枚選び、戦線を選び、命令を確定するところから、"
                        "支援・補給・偵察・勝敗判定までを一通り練習しました。"
                    ).classes("page-subtitle text-center")
                    with ui.row().classes("gap-3 justify-center mt-3"):
                        primary_button("カード1枚を練習する", "/tutorials", "style")
                        secondary_button("最初から復習", icon="replay", on_click=lambda: show_lesson(0))
                        secondary_button("初心者演習へ", icon="play_arrow", on_click=lambda: begin_training())
                return

            index = int(view["index"])
            lesson = BASIC_TUTORIAL_LESSONS[index]
            completed, progress = tutorial_progress(index, total_lessons)
            group_index = 0 if index < 4 else 1 if index < 7 else 2
            with ui.element("div").classes("tutorial-progress-header"):
                with ui.column().classes("gap-1 flex-1"):
                    ui.label(f"第 {index + 1} / {total_lessons} 章").classes("page-eyebrow")
                    ui.linear_progress(value=progress).props("rounded size=8px").classes("progress-track w-full")
                chip(("入門", "戦線力", "実戦判断")[group_index], "green")

            with ui.card().classes("tutorial-lesson-card"):
                ui.label("今回覚える一言").classes("page-eyebrow")
                ui.label(lesson.title).classes("text-2xl font-bold")
                ui.label(lesson.plain_goal).classes("tutorial-plain-goal")
                with ui.expansion("なぜそうなるの？", icon="help_outline").classes("details-expansion"):
                    ui.label(lesson.explanation).classes("section-subtitle mt-2")
                ui.separator().classes("bg-blue-grey-8 my-2")
                ui.label("やってみる").classes("page-eyebrow")
                ui.label(lesson.task).classes("font-bold text-lg")
                render_basic_task(lesson)

                if view["feedback"]:
                    status_class = " tutorial-feedback--correct" if view["correct"] else " tutorial-feedback--hint"
                    with ui.element("div").classes(f"tutorial-feedback{status_class}"):
                        ui.icon("check_circle" if view["correct"] else "lightbulb")
                        ui.label(str(view["feedback"])).classes("text-sm")

                with ui.row().classes("w-full items-center justify-between gap-3 mt-2"):
                    with ui.row().classes("gap-2"):
                        if index > 0:
                            secondary_button(
                                "前の章",
                                icon="arrow_back",
                                on_click=lambda: show_lesson(index - 1),
                            )
                        secondary_button("訓練所へ戻る", "/tutorials", "close")
                    if view["correct"]:
                        primary_button(
                            "基礎訓練を完了" if index == total_lessons - 1 else "次の章へ",
                            icon="arrow_forward",
                            on_click=advance_basic,
                        )

        lesson_view()


@ui.page("/tutorials/card/{card_id}")
def card_tutorial_page(card_id: str) -> None:
    try:
        tutorial = get_tutorial(card_id)
        card = get_card(card_id)
    except KeyError:
        with page_shell(
            "/tutorials", "CARD COURSE", "訓練が見つかりません",
            "指定されたカードは、このバージョンにはありません。",
        ):
            with ui.card().classes("panel"):
                ui.label("カードIDを確認してください。").classes("font-bold")
                secondary_button("訓練所へ戻る", "/tutorials", "arrow_back")
        return

    initial_player = ensure_player_state(app.storage.user)
    if card_id not in initial_player["collection"]["owned_cards"]:
        with page_shell(
            "/tutorials", "CARD COURSE", f"{card.name}の訓練",
            "このカードを入手すると、使い方と公式デッキ報酬が開放されます。",
        ):
            with ui.card().classes("panel tutorial-locked-course"):
                ui.icon("lock", size="48px").classes("muted")
                unit_symbol(card, "lg")
                ui.label("まだこのカードを持っていません").classes("text-xl font-bold")
                ui.label("対戦を完了すると、未所持カードが1枚ずつ解放されます。").classes("section-subtitle")
                secondary_button("所持カードの訓練を見る", "/tutorials", "arrow_back")
        return

    saved_tutorials = initial_player["tutorials"]
    total_stages = len(tutorial.stages)
    view: dict[str, object] = {
        "index": min(int(saved_tutorials["card_stages"].get(card_id, 0)), total_stages - 1),
        "answer": "",
        "feedback": "",
        "correct": False,
        "reviewing": False,
    }

    def reset_card_interaction() -> None:
        view.update(answer="", feedback="", correct=False)

    def show_card_stage(index: int) -> None:
        view["reviewing"] = True
        view["index"] = max(0, min(total_stages - 1, index))
        reset_card_interaction()
        course_view.refresh()
        ui.run_javascript("window.scrollTo({top: 0, behavior: 'auto'})")

    def answer_card_check(choice: str) -> None:
        stage = tutorial.stages[int(view["index"])]
        view["answer"] = choice
        if choice == stage.correct_choice:
            view["correct"] = True
            view["feedback"] = stage.success_message
        else:
            view["correct"] = False
            view["feedback"] = "惜しいです。上の『注意』と、同じ戦線に必要な条件をもう一度確認してください。"
        course_view.refresh()

    def advance_card_course() -> None:
        index = int(view["index"])
        stage = tutorial.stages[index]
        if stage.choices and not view["correct"]:
            return
        state = ensure_player_state(app.storage.user)
        if index == total_stages - 1:
            state = complete_card_tutorial(
                state,
                card_id,
                official_deck_id=tutorial.reward_deck_id,
                final_stage=total_stages,
            )
            store_player_state(app.storage.user, state)
            view["reviewing"] = False
        else:
            state = update_card_tutorial_stage(state, card_id, index + 1)
            store_player_state(app.storage.user, state)
            view["index"] = index + 1
            reset_card_interaction()
        course_view.refresh()
        ui.run_javascript("window.scrollTo({top: 0, behavior: 'auto'})")

    with page_shell(
        "/tutorials", "CARD COURSE", tutorial.title,
        tutorial.intro,
    ):
        @ui.refreshable
        def course_view() -> None:
            player = ensure_player_state(app.storage.user)
            complete = card_id in player["tutorials"]["completed_cards"]
            if complete and not view["reviewing"]:
                reward = get_official_deck(tutorial.reward_deck_id)
                with ui.element("section").classes("tutorial-reward-header"):
                    ui.icon("redeem", size="46px").classes("yellow-text")
                    with ui.column().classes("gap-1 flex-1"):
                        ui.label("カード訓練 完了").classes("page-eyebrow green-text")
                        ui.label(f"報酬：{reward.name}").classes("text-2xl font-bold")
                        ui.label(
                            f"{card.name}を必ず含む公式おすすめデッキです。未所持カードは名前を表示し、選択時は空白にします。"
                        ).classes("section-subtitle")
                with ui.card().classes("panel"):
                    official_deck_preview(reward, on_applied=course_view.refresh)
                with ui.row().classes("gap-3"):
                    secondary_button("このカードを復習", icon="replay", on_click=lambda: show_card_stage(0))
                    secondary_button("ほかのカードを学ぶ", "/tutorials", "style")
                    secondary_button("デッキを調整", "/deck", "view_carousel")
                return

            index = int(view["index"])
            stage = tutorial.stages[index]
            completed, progress = tutorial_progress(index, total_stages)
            with ui.element("div").classes("tutorial-progress-header"):
                with ui.column().classes("gap-1 flex-1"):
                    ui.label(f"{card.name}　{index + 1} / {total_stages}章").classes("page-eyebrow")
                    ui.linear_progress(value=progress).props("rounded size=8px").classes("progress-track w-full")
                chip("復習中" if complete else f"{completed}章完了", "green" if complete else "")

            with ui.element("div").classes("card-course-layout"):
                with ui.card().classes("tutorial-lesson-card"):
                    ui.label(stage.title).classes("text-2xl font-bold")
                    ui.label(stage.summary).classes("tutorial-plain-goal")
                    ui.label(stage.explanation).classes("section-subtitle tutorial-copy")
                    with ui.element("div").classes("tutorial-practice"):
                        ui.label("この章で確認すること").classes("blue-text text-xs font-bold")
                        ui.label(stage.practice).classes("text-sm")

                    if stage.choices:
                        ui.separator().classes("bg-blue-grey-8 my-2")
                        ui.label(stage.question).classes("font-bold text-lg")
                        if stage.exercise_lanes:
                            ui.label(
                                "カードを置くならどこか、3つの戦線を見比べて選びます。"
                            ).classes("muted text-xs")
                            with ui.element("div").classes("tutorial-exercise-stats"):
                                with ui.row().classes("items-center gap-3"):
                                    unit_symbol(card, "sm")
                                    with ui.column().classes("gap-0"):
                                        ui.label("今回配備するカード").classes("muted text-xs")
                                        ui.label(card.name).classes("font-bold")
                                card_stats(card)
                            with ui.element("div").classes("tutorial-field-grid tutorial-lane-grid"):
                                for lane in stage.exercise_lanes:
                                    selected = view["answer"] == lane.label
                                    state_class = " tutorial-lane--selected" if selected else ""
                                    if selected and view["correct"]:
                                        state_class += " tutorial-lane--correct"
                                    with ui.element("div").classes(f"tutorial-lane{state_class}"):
                                        with ui.row().classes("w-full items-center justify-between"):
                                            ui.label(lane.label).classes("font-bold")
                                            difference = lane.player_power - lane.enemy_power
                                            chip(
                                                "味方優勢" if difference > 0 else "敵優勢" if difference < 0 else "互角",
                                                "green" if difference > 0 else "red" if difference < 0 else "yellow",
                                            )
                                        ui.label(lane.situation).classes("section-subtitle")
                                        with ui.element("div").classes("control-meter"):
                                            ui.label(f"味方 {lane.player_power}").classes("blue-text")
                                            ui.label("現在の戦線力").classes("muted")
                                            ui.label(f"敵 {lane.enemy_power}").classes("danger-text text-right")
                                        ui.button(
                                            "ここへ配備", icon="place",
                                            on_click=lambda value=lane.label: answer_card_check(value),
                                        ).props("flat no-caps").classes("card-action")
                        else:
                            with ui.element("div").classes("tutorial-choice-grid"):
                                for choice in stage.choices:
                                    selected = view["answer"] == choice
                                    state_class = " tutorial-choice--selected" if selected else ""
                                    if selected and view["correct"]:
                                        state_class += " tutorial-choice--correct"
                                    with ui.button(
                                        choice,
                                        on_click=lambda value=choice: answer_card_check(value),
                                    ).props("no-caps unelevated").classes(f"tutorial-choice{state_class}"):
                                        pass

                    if view["feedback"]:
                        status_class = " tutorial-feedback--correct" if view["correct"] else " tutorial-feedback--hint"
                        with ui.element("div").classes(f"tutorial-feedback{status_class}"):
                            ui.icon("check_circle" if view["correct"] else "lightbulb")
                            ui.label(str(view["feedback"])).classes("text-sm")

                    with ui.row().classes("w-full items-center justify-between gap-3 mt-3"):
                        with ui.row().classes("gap-2"):
                            if index > 0:
                                secondary_button(
                                    "前の章", icon="arrow_back",
                                    on_click=lambda: show_card_stage(index - 1),
                                )
                            secondary_button("訓練所へ", "/tutorials", "close")
                        if not stage.choices or view["correct"]:
                            primary_button(
                                "訓練を完了してデッキを受け取る" if index == total_stages - 1 else "理解した・次の章へ",
                                icon="arrow_forward",
                                on_click=advance_card_course,
                            )

                with ui.card().classes("panel card-course-reference"):
                    with ui.row().classes("items-start gap-4 no-wrap"):
                        unit_symbol(card, "lg")
                        with ui.column().classes("gap-1 min-w-0"):
                            chip(card.branch)
                            ui.label(card.name).classes("text-xl font-bold")
                            ui.label(card.tagline).classes("section-subtitle")
                    ui.separator().classes("bg-blue-grey-8 my-2")
                    with ui.element("div").classes("card-course-stat-grid"):
                        for label, value in (
                            ("制圧", card.control),
                            ("支援", card.support),
                            ("偵察", card.recon),
                            ("補給", f"{card.supply:+d}"),
                        ):
                            with ui.element("div").classes("card-course-stat"):
                                ui.label(label).classes("muted text-xs")
                                ui.label(str(value)).classes("mono text-xl font-bold")
                    ui.label("数値はこの4つだけ見れば進めます。").classes("muted text-xs")

        course_view()


@ui.page("/learn")
def learn_page() -> None:
    with page_shell(
        "/learn", "QUICK GUIDE", "遊び方は3つだけ",
        "この3つを試してから、分からない言葉だけ後で確認すれば大丈夫です。",
    ):
        with ui.element("div").classes("focus-banner"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon("flag", size="28px")
                with ui.column().classes("gap-0"):
                    ui.label("目的").classes("page-eyebrow")
                    ui.label("左・中央・右で、相手より多く取る").classes("text-xl font-bold")

        with ui.element("div").classes("three-grid"):
            for number, title, description in (
                ("1", "カードを選ぶ", "最初は『歩兵』か『偵察』を選べば大丈夫です。"),
                ("2", "場所を選ぶ", "迷ったら中央へ置きます。"),
                ("3", "命令を決定", "配置先は同時に決まり、相手カードは偵察まで未確認です。"),
            ):
                with ui.card().classes("step-card"):
                    ui.label(number).classes("step-number")
                    ui.label(title).classes("font-bold text-lg")
                    ui.label(description).classes("section-subtitle mt-2")

        with ui.row().classes("gap-3"):
            primary_button("段階チュートリアルで試す", "/tutorials/basic", "school")
            secondary_button("訓練所の一覧", "/tutorials", "view_module")

        with ui.expansion("6つのカードの仕事を見る", icon="extension").classes("details-expansion"):
            with ui.element("div").classes("role-grid mt-3"):
                for role in ROLE_INFO:
                    role_card(role)

        with ui.expansion("用語や詳しい流れを見る", icon="menu_book").classes("details-expansion"):
            ui.label("8ステップの演習、解決順、用語集をまとめた詳しい説明があります。").classes("section-subtitle mt-2")
            secondary_button("詳しい説明を開く", "/advanced-learn", "arrow_forward").classes("mt-3")


@ui.page("/advanced-learn")
def advanced_learn_page() -> None:
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
            primary_button("段階チュートリアルを始める", "/tutorials/basic", "school")
            secondary_button("演習を始める", icon="play_arrow", on_click=lambda: begin_training())
            secondary_button("カード図鑑を見る", "/cards", "style")


@ui.page("/cards")
def cards_page() -> None:
    with page_shell(
        "/cards", "COLLECTION", "まず覚える6枚",
        "最初は、それぞれの『仕事』だけ見れば十分です。数値や専門的な説明は、カードを開いたときだけ表示します。",
    ):
        player = ensure_player_state(app.storage.user)
        owned_cards = set(player["collection"]["owned_cards"])
        with ui.element("div").classes("focus-banner"):
            with ui.row().classes("items-start gap-3 no-wrap"):
                ui.icon("lightbulb", size="26px")
                with ui.column().classes("gap-1"):
                    ui.label("この6枚だけで演習を始められます").classes("font-bold text-lg")
                    ui.label("歩兵が取り、偵察が見つけ、砲兵が助ける。工兵が整え、兵站が支え、機甲が突破します。").classes("text-sm")

        core_cards = [next(card for card in CARDS if card.branch == role and card.id in owned_cards) for role in ROLE_INFO]
        with ui.element("div").classes("beginner-card-grid"):
            for card in core_cards:
                beginner_card(card)

        with ui.card().classes("panel collection-next"):
            with ui.row().classes("w-full items-center justify-between gap-4"):
                with ui.column().classes("gap-1"):
                    ui.label("もっと見たいときだけ開く").classes("font-bold")
                    ui.label(
                        f"カード {len(owned_cards)} / {len(CARDS)}枚、記号 {len(player['collection']['unlocked_symbols'])} / {len(SYMBOL_CATALOG)}種類を収集中です。"
                    ).classes("section-subtitle")
                with ui.row().classes("gap-2"):
                    secondary_button("全カードを見る", "/advanced-cards", "style")
                    secondary_button(f"全記号を見る（{len(SYMBOL_CATALOG)}）", "/symbols", "account_tree")


@ui.page("/symbols")
def symbols_page() -> None:
    with page_shell(
        "/cards", "SYMBOL LIBRARY", "全記号ライブラリ",
        "ここはコレクションを深く見たい人向けです。遊ぶために全部を覚える必要はありません。",
    ):
        player = ensure_player_state(app.storage.user)
        unlocked_symbols = set(player["collection"]["unlocked_symbols"])
        with ui.element("div").classes("beginner-callout beginner-callout--yellow"):
            with ui.row().classes("items-center justify-between gap-4 w-full"):
                with ui.column().classes("gap-1"):
                    ui.label("初心者の方は読み飛ばして大丈夫です").classes("font-bold")
                    ui.label("全記号は一度に出さず、短い練習任務と一緒に段階解放します。").classes("text-sm")
                secondary_button("基本6枚へ戻る", "/cards", "arrow_back")

        family_by_name = {family.name: family for family in SYMBOL_FAMILIES}
        catalog_state = {"family": "歩兵組織"}

        def change_family(event) -> None:
            catalog_state["family"] = event.value
            family_view.refresh()

        def try_division() -> None:
            state = update_state_formation(ensure_player_state(app.storage.user), "division")
            store_player_state(app.storage.user, state)
            begin_training()

        def select_emblem(symbol_id: str) -> None:
            try:
                state = update_state_selected_symbol(
                    ensure_player_state(app.storage.user), symbol_id
                )
            except ValueError as error:
                ui.notify(str(error), type="warning")
                return
            store_player_state(app.storage.user, state)
            family_view.refresh()
            ui.notify("アカウントアイコンを変更しました。", type="positive")

        ui.select(
            list(family_by_name), value=catalog_state["family"], label="見る分類を1つ選ぶ",
            on_change=change_family,
        ).props("outlined options-dense").classes("filter-control w-full max-w-xl")

        @ui.refreshable
        def family_view() -> None:
            current_selected = str(
                ensure_player_state(app.storage.user)["profile"].get("selected_symbol", "")
            )
            family = family_by_name[catalog_state["family"]]
            symbols = symbols_for_family(family.id)
            with ui.card().classes("panel symbol-family-panel"):
                with ui.row().classes("w-full items-start gap-4 no-wrap"):
                    ui.label(family.token).classes("symbol-family-token")
                    with ui.column().classes("gap-1 flex-1"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(family.name).classes("section-title")
                            chip(f"{len(symbols)}種類")
                            chip(f"解放 {sum(symbol.id in unlocked_symbols for symbol in symbols)}", "green")
                        ui.label(family.plain_role).classes("section-subtitle")
                        with ui.row().classes("gap-2 mt-1"):
                            chip(family.play_kind.value, "green")
                            chip(family.domain.value)
                            chip(STAGE_LABELS[family.unlock_stage], "yellow")
                ui.separator().classes("bg-blue-grey-8 my-4")
                ui.label("収録している記号").classes("font-bold")
                ui.label("各記号には、カード・支援・施設・装備・編制のいずれかの用途を割り当てています。").classes("section-subtitle")
                with ui.element("div").classes("symbol-mini-grid mt-4"):
                    for symbol in symbols:
                        with ui.element("div").classes("symbol-mini-row"):
                            ui.label(symbol.token).classes("symbol-mini-token")
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(symbol.name).classes("font-bold text-sm")
                                ui.label(symbol.play_kind.value).classes("muted text-xs")
                            if symbol.id == current_selected:
                                chip("使用中", "yellow")
                            elif symbol.id in unlocked_symbols:
                                ui.button(
                                    "アイコンにする", icon="account_circle",
                                    on_click=lambda sid=symbol.id: select_emblem(sid),
                                ).props("flat dense no-caps").classes("symbol-try-button")
                            else:
                                chip("未解放", "")
                            if symbol.id == "echelon_05":
                                ui.button(
                                    "師団編制を使う", icon="play_arrow", on_click=try_division,
                                ).props("flat no-caps").classes("symbol-try-button")

        family_view()

        with ui.expansion("全体の解放順を見る", icon="timeline").classes("details-expansion"):
            for stage, label in STAGE_LABELS.items():
                count = sum(1 for symbol in SYMBOL_CATALOG if symbol.unlock_stage == stage)
                with ui.row().classes("w-full items-center justify-between py-2"):
                    ui.label(label).classes("font-bold text-sm")
                    chip(f"{count}記号")

        with ui.expansion("参照画像で全記号を確認", icon="image").classes("details-expansion"):
            ui.label(
                "送っていただいた早見表を原寸のまま収録しています。図鑑の201項目はこの画像の分類と対応します。"
            ).classes("section-subtitle mt-2")
            ui.image("/static/reference-symbols.png").props("fit=contain").classes(
                "w-full mt-3 rounded-borders bg-white"
            )


@ui.page("/advanced-cards")
def advanced_cards_page() -> None:
    with page_shell(
        "/cards", f"COLLECTION / 12 OF {len(CARDS)}", "カード図鑑",
        "未入手のカードも能力と入手方法を確認できます。レア度は強さの順位ではありません。",
    ):
        player = ensure_player_state(app.storage.user)
        owned_cards = set(player["collection"]["owned_cards"])
        unlocked_symbols = set(player["collection"]["unlocked_symbols"])
        with ui.element("div").classes("metric-grid"):
            metric_card("ゲームカード", f"{len(owned_cards)} / {len(CARDS)}", "対戦完了ごとに1枚解放", "blue-text")
            metric_card("兵科図鑑", "6 / 6", "初期6兵科を発見済み", "green-text")
            metric_card("編制規模", f"{len(player['collection']['unlocked_formations'])} / {len(FORMATION_SCALES)}", "大隊・旅団・師団を表示")
            metric_card("記号コレクション", f"{len(unlocked_symbols)} / {len(SYMBOL_CATALOG)}", "対戦ごとに最大12種類解放", "yellow-text")

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
                    unit_card(replace(card, owned=card.id in owned_cards))

        card_grid()


@ui.page("/deck")
def deck_page() -> None:
    with page_shell(
        "/deck", "FORCE BUILDER", "デッキ編成",
        "役割の違うカードを組み合わせて、自分の部隊を作ります。実際の軍隊編制ではなくゲーム用の構成です。",
    ):
        initial_player = ensure_player_state(app.storage.user)
        unlocked_deck_count = len(initial_player["tutorials"]["unlocked_official_decks"])
        with ui.element("div").classes("beginner-callout"):
            with ui.row().classes("w-full items-center justify-between gap-4"):
                with ui.column().classes("gap-1"):
                    ui.label(f"公式おすすめデッキ：{unlocked_deck_count}個 解放済み").classes("font-bold")
                    ui.label("カード訓練の報酬デッキは、未所持の枠を空白にしてここへセットできます。").classes("text-sm")
                secondary_button("公式デッキを見る", "/tutorials", "redeem")

        def update_deck(new_deck: list[str], message: str | None = None) -> None:
            state = ensure_player_state(app.storage.user)
            try:
                state = update_state_deck(state, new_deck)
            except ValueError as error:
                ui.notify(str(error), type="negative")
                return
            store_player_state(app.storage.user, state)
            deck_view.refresh()
            if message:
                ui.notify(message, type="positive")

        def add_card(card_id: str) -> None:
            deck = list(ensure_player_state(app.storage.user)["deck"])
            if len(deck) >= 12:
                ui.notify("デッキは12枚までです。先に1枚外してください。", type="warning")
                return
            if card_id in deck:
                ui.notify("この試作版では同じカードを1枚まで入れられます。", type="warning")
                return
            deck.append(card_id)
            update_deck(deck)

        def remove_card(card_id: str) -> None:
            deck = list(ensure_player_state(app.storage.user)["deck"])
            if card_id in deck:
                deck.remove(card_id)
                update_deck(deck)

        def use_current_deck() -> None:
            deck = ensure_player_state(app.storage.user)["deck"]
            if len(deck) < 6:
                ui.notify(f"対戦にはカードを{MAX_ROUNDS}枚以上入れてください。", type="warning")
                return
            ui.notify("このデッキを使用します。", type="positive")
            go("/lobby")

        @ui.refreshable
        def deck_view() -> None:
            player = ensure_player_state(app.storage.user)
            deck_ids = list(player["deck"])
            owned_cards = set(player["collection"]["owned_cards"])
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
                                    if card.id not in owned_cards or card.id in deck_ids or len(deck_ids) >= 12:
                                        add.props("disable")

                with ui.column().classes("w-full gap-4"):
                    with ui.card().classes("panel"):
                        with ui.row().classes("w-full items-start justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label("はじめての統合部隊").classes("section-title")
                                ui.label(f"{analysis['count']} / 12枚").classes("section-subtitle")
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
                            primary_button("このデッキで遊ぶ", icon="play_arrow", on_click=use_current_deck)
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
                                            ui.label(f"{card.branch}・{card.echelon}").classes("muted text-xs")
                                        ui.button(
                                            icon="remove", on_click=lambda cid=card_id: remove_card(cid)
                                        ).props("round flat aria-label=カードを外す")

        def select_formation(formation_id: str) -> None:
            state = update_state_formation(
                ensure_player_state(app.storage.user), get_formation(formation_id).id
            )
            store_player_state(app.storage.user, state)
            formation_view.refresh()
            ui.notify(f"編制規模を{get_formation(formation_id).name}にしました。", type="positive")

        @ui.refreshable
        def formation_view() -> None:
            current = get_formation(ensure_player_state(app.storage.user)["selected_formation"])
            with ui.expansion("編制規模（任意）", icon="account_tree").classes("details-expansion"):
                ui.label(
                    "兵科は『仕事』、師団や旅団は『大きさ』です。編制規模を変えてもカードの強さは変わりません。"
                ).classes("section-subtitle mt-2")
                with ui.row().classes("gap-2 mt-3"):
                    for formation in FORMATION_SCALES:
                        selected_class = " primary-button" if formation.id == current.id else " secondary-button"
                        label = formation.name if formation.id == "native" else f"{formation.marker} {formation.name}"
                        ui.button(
                            label, on_click=lambda fid=formation.id: select_formation(fid),
                        ).props("no-caps unelevated").classes(selected_class)
                ui.label(f"現在：{current.name}").classes("blue-text text-sm font-bold mt-3")

        deck_view()
        formation_view()


@ui.page("/lobby")
def lobby_page() -> None:
    with page_shell(
        "/lobby", "PLAY", "何をするか一つ選ぶ",
        "初めてなら演習がおすすめです。勝敗や時間を気にせず操作を試せます。",
    ):
        if not ensure_player_state(app.storage.user)["tutorials"]["basic_completed"]:
            with ui.element("div").classes("beginner-callout beginner-callout--yellow"):
                with ui.row().classes("w-full items-center justify-between gap-4"):
                    with ui.column().classes("gap-1"):
                        ui.label("操作の前に、基礎を一つずつ試せます").classes("font-bold")
                        ui.label("対戦はいつでも始められますが、9章の段階チュートリアルを先に行うと画面が分かりやすくなります。").classes("text-sm")
                    secondary_button("基礎チュートリアル", "/tutorials/basic", "school")

        def choose_mode(mode: str) -> None:
            if mode == "training":
                begin_training()
                return
            state = update_state_mode(ensure_player_state(app.storage.user), mode)
            store_player_state(app.storage.user, state)
            if mode in {"casual", "ranked"}:
                go("/online")
                return
            if mode == "friend":
                go("/friend")
                return

        with ui.element("section").classes("start-here start-here--compact"):
            with ui.column().classes("start-here__copy gap-2"):
                chip("おすすめ", "green")
                ui.label("初心者演習").classes("start-here__title")
                ui.label("相手は練習用です。時間制限なしで、カードを置くところから始めます。").classes("start-here__description")
                primary_button(
                    "演習を始める", icon="play_arrow", on_click=lambda: choose_mode("training"),
                ).classes("start-here__button")
            with ui.card().classes("panel panel--compact"):
                ui.label("使用デッキ").classes("muted text-xs")
                ui.label("はじめての統合部隊").classes("font-bold")
                ui.label("6つの基本的な仕事が入っています").classes("section-subtitle")
                secondary_button("デッキを確認", "/deck", "view_carousel").classes("mt-2")

        with ui.expansion("ほかの遊び方", icon="unfold_more").classes("details-expansion"):
            with ui.element("div").classes("three-grid mt-3"):
                for mode, title, description, icon in (
                    ("casual", "オンライン対戦", "待機中のプレイヤーと気軽に対戦します。", "public"),
                    ("ranked", "ランク対戦", "オンラインの勝敗を戦績へ記録します。", "leaderboard"),
                    ("friend", "フレンド対戦", "6文字の合言葉で友人と同じ部屋へ入ります。", "group"),
                ):
                    with ui.card().classes("lobby-mode"):
                        ui.icon(icon, size="28px").classes("blue-text")
                        ui.label(title).classes("font-bold text-lg mt-2")
                        ui.label(description).classes("section-subtitle")
                        ui.button(
                            "このモードで遊ぶ", icon="play_arrow",
                            on_click=lambda selected_mode=mode: choose_mode(selected_mode),
                        ).props("flat no-caps").classes("card-action")
            secondary_button("詳しい対戦準備画面を見る", "/advanced-lobby", "tune").classes("mt-3")


@ui.page("/advanced-lobby")
def advanced_lobby_page() -> None:
    with page_shell(
        "/lobby", "MATCH CONTROL", "対戦の準備",
        "遊ぶモードとデッキを選びます。最初は時間制限のない演習がおすすめです。",
    ):
        def select_mode(mode: str) -> None:
            if mode == "training":
                begin_training()
                return
            state = update_state_mode(ensure_player_state(app.storage.user), mode)
            store_player_state(app.storage.user, state)
            if mode in {"casual", "ranked"}:
                go("/online")
                return
            if mode == "friend":
                go("/friend")
                return

        section_heading("遊ぶモード", "カードの性能はどのモードでも同じです。")
        with ui.element("div").classes("three-grid"):
            for mode, title, badge, body, icon, recommended in (
                ("training", "演習", "ひとり用", "ゆっくり操作を覚えられます。時間制限もありません。", "school", True),
                ("casual", "オンライン対戦", "対人", "待機中の別プレイヤーとリアルタイムで遊びます。", "public", False),
                ("ranked", "ランク対戦", "競技", "オンラインの勝敗を戦績に記録します。", "leaderboard", False),
            ):
                with ui.card().classes("lobby-mode"):
                    with ui.row().classes("w-full items-start justify-between"):
                        ui.icon(icon, size="30px").classes("blue-text")
                        chip("おすすめ" if recommended else badge, "green" if recommended else "")
                    ui.label(title).classes("text-xl font-bold mt-2")
                    ui.label(body).classes("section-subtitle")
                    ui.button(
                        "このモードを選ぶ", on_click=lambda selected_mode=mode: select_mode(selected_mode),
                    ).props("flat no-caps").classes("card-action")

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
                    primary_button(
                        "このデッキで対戦", icon="swords",
                        on_click=lambda: select_mode(str(ensure_player_state(app.storage.user)["selected_mode"])),
                    )
                    secondary_button("ヒント設定", "/settings", "tips_and_updates")
            with ui.card().classes("panel"):
                section_heading("フレンド対戦", "合言葉または招待URLで友人と遊べます。")
                ui.label("部屋を作る側と参加する側で、同じ6文字の合言葉を使います。").classes("section-subtitle mt-3")
                primary_button("フレンド部屋を開く", icon="group", on_click=lambda: select_mode("friend")).classes("mt-3")


@ui.page("/online")
def online_queue_page() -> None:
    user_storage = app.storage.user
    abandon_match(user_storage)
    user_storage.pop("battle_selection", None)
    player = ensure_player_state(app.storage.user)
    mode = str(player["selected_mode"])
    if mode not in {"casual", "ranked"}:
        mode = "casual"
        player = update_state_mode(player, mode)
        store_player_state(app.storage.user, player)
    display_name = str(player["profile"]["display_name"])
    mode_label = "ランク対戦" if mode == "ranked" else "オンライン対戦"

    try:
        existing_online = poll_multiplayer(app.storage.user)
        if existing_online.get("status") == "left":
            close_multiplayer_session(app.storage.user)
        initial_view = join_queue(app.storage.user, mode, name=display_name)
    except MultiplayerError as error:
        initial_view = {"status": "error", "message": str(error)}

    def cancel_queue() -> None:
        try:
            cancel_waiting(app.storage.user)
        except MultiplayerError:
            pass
        go("/lobby")

    def cleanup_queue_on_delete() -> None:
        try:
            cancel_waiting(user_storage)
        except MultiplayerError:
            pass

    with page_shell(
        "/lobby", "MATCHMAKING", f"{mode_label}・相手を検索中",
        "同じモードで待っている別のブラウザと、自動で組み合わせます。",
    ):
        @ui.refreshable
        def waiting_panel() -> None:
            view = poll_multiplayer(app.storage.user)
            if view.get("status") in {"playing", "complete", "opponent_left"}:
                ui.label("対戦相手が見つかりました。盤面を開きます…").classes("green-text font-bold")
                go("/pvp")
                return
            if view.get("status") == "waiting_friend":
                ui.label("フレンド部屋の待機画面へ戻ります…").classes("blue-text font-bold")
                go("/friend")
                return
            if view.get("status") == "idle" and initial_view.get("status") == "error":
                with ui.card().classes("panel"):
                    ui.icon("error_outline", size="38px").classes("danger-text")
                    ui.label("マッチングを開始できませんでした").classes("text-xl font-bold")
                    ui.label(str(initial_view.get("message", "もう一度お試しください。"))).classes("section-subtitle")
                    secondary_button("ロビーへ戻る", "/lobby", "arrow_back").classes("mt-3")
                return
            with ui.card().classes("panel panel--strong"):
                with ui.column().classes("w-full items-center text-center gap-3 py-5"):
                    ui.spinner("dots", size="58px", color="primary")
                    ui.label("対戦相手を待っています").classes("text-2xl font-bold")
                    with ui.element("div").classes("battle-account"):
                        account_icon(player["profile"].get("selected_symbol"), display_name)
                        with ui.column().classes("gap-0 text-left"):
                            ui.label(display_name).classes("font-bold")
                            ui.label(f"モード：{mode_label}").classes("section-subtitle")
                    if view.get("queue_position"):
                        chip(f"待機順 {view['queue_position']}", "yellow")
                    ui.label("この画面を開いた別のプレイヤーが来ると自動で開始します。").classes("muted text-xs")
                    secondary_button("待機をやめる", icon="close", on_click=cancel_queue)

        waiting_panel()

        def poll_queue() -> None:
            view = poll_multiplayer(app.storage.user)
            if view.get("status") in {"playing", "complete", "opponent_left"}:
                go("/pvp")
            else:
                waiting_panel.refresh()

        register_client_poll(poll_queue, cleanup=cleanup_queue_on_delete)


@ui.page("/friend")
def friend_room_page() -> None:
    user_storage = app.storage.user
    abandon_match(user_storage)
    user_storage.pop("battle_selection", None)
    player = ensure_player_state(app.storage.user)
    if player["selected_mode"] != "friend":
        player = update_state_mode(player, "friend")
        player = store_player_state(app.storage.user, player)
    display_name = str(player["profile"]["display_name"])
    room_state: dict[str, object] = {"message": ""}

    existing_friend = poll_multiplayer(app.storage.user)
    if existing_friend.get("status") == "left":
        try:
            close_multiplayer_session(app.storage.user)
        except MultiplayerError:
            pass

    def create_room() -> None:
        try:
            create_friend_room(app.storage.user, name=display_name)
        except MultiplayerError as error:
            room_state["message"] = str(error)
            ui.notify(str(error), type="negative")
        room_panel.refresh()

    def join_room() -> None:
        code = str(code_input.value or "").strip().upper()
        if not code:
            ui.notify("6文字の合言葉を入力してください。", type="warning")
            return
        try:
            join_friend_room(app.storage.user, code, name=display_name)
        except MultiplayerError as error:
            room_state["message"] = "合言葉が違うか、その部屋はすでに開始しています。"
            ui.notify(room_state["message"], type="negative")
            room_panel.refresh()
            return
        go("/pvp")

    def cancel_room() -> None:
        try:
            cancel_waiting(app.storage.user)
        except MultiplayerError:
            pass
        go("/lobby")

    def cleanup_room_on_delete() -> None:
        try:
            cancel_waiting(user_storage)
        except MultiplayerError:
            pass

    with page_shell(
        "/lobby", "PRIVATE MATCH", "フレンド対戦",
        "部屋を作って合言葉を渡すか、友人から受け取った合言葉で参加します。",
    ):
        code_input = ui.input("友人から受け取った6文字", placeholder="例：A7K2PX").props(
            "outlined maxlength=6"
        ).classes("filter-control w-full max-w-md")

        @ui.refreshable
        def room_panel() -> None:
            view = poll_multiplayer(app.storage.user)
            status = view.get("status")
            if status in {"playing", "complete", "opponent_left"}:
                ui.label("友人が参加しました。対戦盤を開きます…").classes("green-text font-bold")
                go("/pvp")
                return
            if status == "waiting":
                ui.label("オンライン対戦の待機画面へ戻ります…").classes("blue-text font-bold")
                go("/online")
                return
            if status == "waiting_friend":
                with ui.card().classes("panel panel--strong"):
                    with ui.element("div").classes("battle-account"):
                        account_icon(player["profile"].get("selected_symbol"), display_name)
                        with ui.column().classes("gap-0"):
                            ui.label(display_name).classes("font-bold")
                            ui.label("部屋の作成者").classes("muted text-xs")
                    ui.label("この合言葉を友人へ送ってください").classes("font-bold")
                    ui.label(str(view["room_code"])).classes("mono text-4xl font-bold blue-text my-3")
                    ui.label("参加を待っています（1 / 2）").classes("section-subtitle")

                    def copy_code() -> None:
                        ui.run_javascript(f"navigator.clipboard.writeText('{view['room_code']}')")
                        ui.notify("合言葉をコピーしました。", type="positive")

                    with ui.row().classes("gap-2 mt-3"):
                        secondary_button("合言葉をコピー", icon="content_copy", on_click=copy_code)
                        secondary_button("部屋を閉じる", icon="close", on_click=cancel_room)
                return
            with ui.element("div").classes("content-grid"):
                with ui.card().classes("panel"):
                    section_heading("部屋を作る", "あなたが合言葉を友人へ伝えます。")
                    primary_button("新しい部屋を作る", icon="add", on_click=create_room).classes("mt-3")
                with ui.card().classes("panel"):
                    section_heading("部屋へ参加", "上の欄へ合言葉を入力します。")
                    primary_button("この合言葉で参加", icon="login", on_click=join_room).classes("mt-3")
                    if room_state["message"]:
                        ui.label(str(room_state["message"])).classes("danger-text text-sm mt-2")

        room_panel()

        def poll_friend() -> None:
            view = poll_multiplayer(app.storage.user)
            if view.get("status") in {"playing", "complete", "opponent_left"}:
                go("/pvp")
            else:
                room_panel.refresh()

        register_client_poll(poll_friend, cleanup=cleanup_room_on_delete)


@ui.page("/pvp")
def multiplayer_battle_page() -> None:
    user_storage = app.storage.user
    initial_view = poll_multiplayer(app.storage.user)
    if initial_view.get("status") == "waiting":
        go("/online")
        return
    if initial_view.get("status") == "waiting_friend":
        go("/friend")
        return
    if initial_view.get("status") == "left":
        try:
            close_multiplayer_session(app.storage.user)
        except MultiplayerError:
            pass
        go("/lobby")
        return
    if initial_view.get("status") == "idle":
        with page_shell(
            "/lobby", "ONLINE OPERATION", "参加中のオンライン対戦がありません",
            "ロビーからオンライン対戦を選ぶか、フレンドの合言葉で参加してください。",
        ):
            primary_button("対戦ロビーへ", "/lobby", "swords")
        return

    selection_key = "pvp_selection"
    preferences = get_preferences()
    last_poll = {"digest": ""}

    def get_pvp_selection(view: dict[str, object]) -> dict[str, object]:
        match_id = str(view.get("match_id", ""))
        raw = app.storage.user.get(selection_key)
        if not isinstance(raw, dict) or raw.get("match_id") != match_id:
            raw = {"match_id": match_id, "selected": None, "planned_lane": None}
            app.storage.user[selection_key] = raw
        return dict(raw)

    def set_pvp_selection(view: dict[str, object], **changes: object) -> None:
        selected = get_pvp_selection(view)
        selected.update(changes)
        app.storage.user[selection_key] = selected

    def select_pvp_card(card_id: str) -> None:
        view = poll_multiplayer(app.storage.user)
        if view.get("submitted"):
            ui.notify("このラウンドの命令は確定済みです。", type="warning")
            return
        player_id = str(view["player_id"])
        hand = view["game"]["players"][player_id]["hand"]
        if card_id not in hand:
            ui.notify("そのカードは現在の手札にありません。", type="warning")
            return
        set_pvp_selection(view, selected=card_id, planned_lane=None)
        pvp_board.refresh()

    def plan_pvp_lane(lane_id: str) -> None:
        view = poll_multiplayer(app.storage.user)
        selected = get_pvp_selection(view)
        if not selected.get("selected"):
            ui.notify("先に手札からカードを選んでください。", type="warning")
            return
        set_pvp_selection(view, planned_lane=lane_id)
        pvp_board.refresh()

    def execute_pvp_order() -> None:
        view = poll_multiplayer(app.storage.user)
        selected = get_pvp_selection(view)
        card_id = selected.get("selected")
        lane_id = selected.get("planned_lane")
        if not card_id or not lane_id:
            ui.notify("カードと配置先を選んでください。", type="warning")
            return
        try:
            response = submit_player_order(app.storage.user, str(card_id), str(lane_id))
        except (MultiplayerError, RuleViolation) as error:
            ui.notify(str(error), type="negative")
            pvp_board.refresh()
            return
        set_pvp_selection(response, selected=None, planned_lane=None)
        if response.get("status") == "complete":
            claimed = claim_multiplayer_result(app.storage.user)
            if claimed.get("rewards"):
                app.storage.user["last_pvp_rewards"] = claimed["rewards"]
            ui.notify("最終ラウンドを解決しました。", type="positive")
        elif response.get("submitted"):
            ui.notify("命令を確定しました。相手の命令を待っています。", type="positive")
        else:
            ui.notify("両者の命令を公開し、ラウンドを解決しました。", type="positive")
        pvp_board.refresh()

    def request_pvp_confirmation() -> None:
        view = poll_multiplayer(app.storage.user)
        selected = get_pvp_selection(view)
        card_id = selected.get("selected")
        lane_id = selected.get("planned_lane")
        if not card_id or not lane_id:
            ui.notify("カードと配置先を選んでください。", type="warning")
            return
        if preferences["confirm_orders"]:
            lane_name = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}[str(lane_id)]
            pvp_confirm_text.text = f"{get_card(str(card_id)).name}を{lane_name}へ配備します。"
            pvp_confirm_dialog.open()
        else:
            execute_pvp_order()

    def close_pvp_confirmation() -> None:
        pvp_confirm_dialog.close()
        execute_pvp_order()

    def close_pvp_to(path: str) -> None:
        try:
            current = poll_multiplayer(app.storage.user)
            if current.get("status") not in {"complete", "left"}:
                leave_multiplayer(app.storage.user)
            close_multiplayer_session(app.storage.user)
        except MultiplayerError:
            pass
        app.storage.user.pop(selection_key, None)
        go(path)

    def leave_pvp() -> None:
        close_pvp_to("/lobby")

    with ui.dialog() as pvp_confirm_dialog, ui.card().classes("dialog-card"):
        ui.label("オンラインへ命令を送りますか？").classes("text-xl font-bold")
        pvp_confirm_text = ui.label().classes("section-subtitle")
        ui.label("送信後は、相手が確定するまで変更できません。").classes("muted text-xs")
        with ui.row().classes("gap-2 mt-3"):
            primary_button("命令を送信", icon="send", on_click=close_pvp_confirmation)
            secondary_button("戻る", icon="close", on_click=pvp_confirm_dialog.close)

    mode_label = "ランク対戦" if initial_view.get("mode") == "ranked" else "フレンド対戦" if initial_view.get("mode") == "friend" else "オンライン対戦"
    with page_shell(
        "/lobby", "ONLINE OPERATION", mode_label,
        "あなたと相手が1枚ずつ選び、両方の命令が届いた時点で同時に解決します。",
    ):
        @ui.refreshable
        def pvp_board() -> None:
            view = poll_multiplayer(app.storage.user)
            status = str(view.get("status", "idle"))
            if status == "idle":
                with ui.card().classes("panel"):
                    ui.label("対戦情報が見つかりません。").classes("text-xl font-bold")
                    ui.label("サーバー再起動後は、待機中の対戦が終了する場合があります。").classes("section-subtitle")
                    primary_button("ロビーへ戻る", "/lobby", "arrow_back").classes("mt-3")
                return

            game = view["game"]
            player_id = str(view["player_id"])
            opponent_id = next(key for key in game["players"] if key != player_id)
            human = game["players"][player_id]
            opponent = game["players"][opponent_id]
            selected = get_pvp_selection(view)
            selected_id = selected.get("selected")
            planned_lane = selected.get("planned_lane")
            submitted = bool(view.get("submitted"))
            formation = get_formation(str(view.get("formation", "native")))

            with ui.element("div").classes("battle-status"):
                with ui.element("div").classes("battle-account"):
                    account_icon(view.get("player", {}).get("icon_symbol_id"), str(human["name"]))
                    with ui.column().classes("gap-0"):
                        ui.label(f"{human['name']} / あなた").classes("font-bold")
                        ui.label(f"任務点 {human['mission_points']}").classes("mono blue-text text-xs")
                with ui.column().classes("items-center gap-0"):
                    ui.label(f"ROUND {game['round_no']} / {game['max_rounds']}").classes("mono text-xl font-bold")
                    ui.label("送信済み・相手を待機" if submitted else "命令を選んでください").classes("muted text-xs")
                with ui.element("div").classes("battle-account"):
                    account_icon(
                        view.get("opponent", {}).get("icon_symbol_id"),
                        str(view["opponent"]["name"]),
                    )
                    with ui.column().classes("items-end gap-0"):
                        ui.label(f"{view['opponent']['name']} / 相手").classes("font-bold")
                        connection = "退出" if view["opponent"]["left"] else "接続中" if view["opponent"]["connected"] else "再接続待ち"
                        ui.label(f"任務点 {opponent['mission_points']}・{connection}").classes("green-text text-xs")

            if status == "opponent_left":
                with ui.element("div").classes("result-banner"):
                    ui.label("相手が退出しました").classes("text-2xl font-bold")
                    ui.label("退出した側の不戦敗として結果を確定します。").classes("section-subtitle mt-2")
                    primary_button("ロビーへ戻る", icon="arrow_back", on_click=leave_pvp).classes("mt-3")
                return

            if status == "complete" and game.get("result"):
                if not view.get("result_claimed"):
                    claimed = claim_multiplayer_result(app.storage.user)
                    if claimed.get("rewards"):
                        app.storage.user["last_pvp_rewards"] = claimed["rewards"]
                    view = poll_multiplayer(app.storage.user)
                result = game["result"]
                winner = result.get("winner_id")
                if winner == player_id:
                    title, badge, badge_class = "オンライン勝利", "勝利", "green-text"
                elif winner is None:
                    title, badge, badge_class = "互角の決着", "引き分け", "yellow-text"
                else:
                    title, badge, badge_class = "対戦終了", "敗北", "danger-text"
                with ui.element("div").classes("result-banner"):
                    ui.label(badge).classes(f"page-eyebrow {badge_class}")
                    ui.label(title).classes("text-2xl font-bold mt-1")
                    ui.label(
                        f"最終任務点：あなた {human['mission_points']} - {opponent['mission_points']} 相手"
                    ).classes("text-sm mt-2")
                    ui.label(str(result["summary"])).classes("section-subtitle")
                    rewards = app.storage.user.get("last_pvp_rewards", {})
                    if isinstance(rewards, dict) and (rewards.get("cards") or rewards.get("symbols")):
                        with ui.element("div").classes("beginner-callout mt-3"):
                            ui.label("コレクション報酬").classes("font-bold")
                            if rewards.get("cards"):
                                ui.label("新しいカード：" + "・".join(get_card(cid).name for cid in rewards["cards"])).classes("text-sm")
                            if rewards.get("symbols"):
                                ui.label(f"新しい記号：{len(rewards['symbols'])}種類").classes("text-sm")
                    with ui.row().classes("gap-2 mt-4"):
                        primary_button("ロビーへ戻る", icon="arrow_back", on_click=leave_pvp)
                        secondary_button(
                            "戦績を見る", icon="military_tech",
                            on_click=lambda: close_pvp_to("/profile"),
                        )
                return

            if submitted:
                with ui.element("div").classes("focus-banner"):
                    ui.spinner("dots", size="30px", color="primary")
                    with ui.column().classes("gap-0"):
                        ui.label("命令を送信済みです").classes("font-bold")
                        ui.label("相手の命令が届くと、自動で結果を表示します。").classes("section-subtitle")
            elif preferences["beginner_mode"] or preferences["recommended_actions"]:
                with ui.element("div").classes("battle-focus"):
                    with ui.column().classes("gap-1"):
                        ui.label("カード → 場所 → 送信").classes("page-eyebrow beginner-only")
                        ui.label(
                            "手札を1枚選んでください" if not selected_id
                            else "配置先を選んでください" if not planned_lane
                            else "命令を送信できます"
                        ).classes("text-xl font-bold")

            with ui.element("div").classes("battle-layout"):
                with ui.column().classes("w-full gap-4 battle-board-column"):
                    with ui.element("div").classes("lane-grid"):
                        lane_labels = {
                            "left": ("左戦線（左翼）", "森林"),
                            "center": ("中央戦線", "市街地"),
                            "right": ("右戦線（右翼）", "平地"),
                        }
                        for lane_id, (lane_name, terrain) in lane_labels.items():
                            lane = game["lanes"][lane_id]
                            last_power = lane.get("last_power", {})
                            own_power = int(last_power.get(player_id, {}).get("total", 0))
                            enemy_power = int(last_power.get(opponent_id, {}).get("total", 0))
                            own_units = [d for d in lane["deployments"] if d["player_id"] == player_id]
                            enemy_units = [d for d in lane["deployments"] if d["player_id"] == opponent_id]
                            hidden_enemy = any(bool(deployment.get("hidden")) for deployment in enemy_units)
                            planned_class = " battle-lane--planned" if planned_lane == lane_id else ""
                            with ui.element("div").classes(f"battle-lane{planned_class}"):
                                with ui.row().classes("lane-header items-center justify-between"):
                                    with ui.column().classes("gap-0"):
                                        ui.label(lane_name).classes("font-bold")
                                        ui.label(terrain).classes("muted text-xs")
                                    if not lane["round_winners"]:
                                        chip("未解決", "yellow")
                                    elif hidden_enemy:
                                        last_winner = lane["round_winners"][-1]
                                        if last_winner == player_id:
                                            chip("前回：あなたが確保", "green")
                                        elif last_winner == opponent_id:
                                            chip("前回：相手が確保", "red")
                                        else:
                                            chip("前回：互角", "yellow")
                                    elif own_power > enemy_power:
                                        chip(f"あなたが優勢 +{own_power - enemy_power}", "green")
                                    elif own_power < enemy_power:
                                        chip(f"相手が優勢 +{enemy_power - own_power}", "red")
                                    else:
                                        chip("互角", "yellow")
                                ui.label("相手部隊").classes("muted text-xs mt-3")
                                if not enemy_units:
                                    ui.label("まだ配備なし").classes("unknown-unit")
                                for deployment in enemy_units[-3:]:
                                    with ui.element("div").classes("unknown-unit"):
                                        hidden = bool(deployment.get("hidden"))
                                        ui.icon("help_outline" if hidden else "visibility", size="21px")
                                        card_data = deployment.get("card") or {}
                                        ui.label("未確認部隊" if hidden else str(card_data.get("name", "部隊")))
                                with ui.element("div").classes("control-meter mt-3"):
                                    ui.label(f"味方 {own_power}").classes("blue-text")
                                    ui.label("前ラウンド戦線力").classes("muted")
                                    ui.label(f"敵 {'?' if hidden_enemy else enemy_power}").classes("danger-text text-right")
                                ui.label("あなたの部隊").classes("muted text-xs mt-3")
                                with ui.element("div").classes("front-line"):
                                    ui.label(
                                        "・".join(str((d.get("card") or {}).get("name", "部隊")) for d in own_units[-3:]) or "まだ配備なし"
                                    ).classes("font-bold text-sm")
                                place = ui.button(
                                    "ここに配置", icon="place", on_click=lambda lid=lane_id: plan_pvp_lane(lid)
                                ).props("flat no-caps").classes("card-action mt-3")
                                if not selected_id or submitted:
                                    place.props("disable")

                    with ui.card().classes("panel battle-hand-panel"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label(f"手札（残り {len(human['hand'])}枚）").classes("section-title")
                                ui.label("カード下部の制圧・支援・偵察・補給を見て選べます。相手には確定内容は見えません。").classes("section-subtitle")
                            if formation.id != "native":
                                chip(f"{formation.marker} {formation.name}", "yellow")
                        with ui.element("div").classes("hand-strip mt-3"):
                            for card_id in human["hand"]:
                                card = get_card(card_id)
                                selected_class = " hand-card--selected" if selected_id == card_id else ""
                                hand_card = ui.card().classes(f"hand-card{selected_class}")
                                if not submitted:
                                    hand_card.on("click", lambda cid=card_id: select_pvp_card(cid))
                                with hand_card:
                                    ui.label(card.branch).classes("unit-card__branch")
                                    ui.label(card.name).classes("font-bold text-sm min-h-10")
                                    with ui.element("div").classes("unit-card__symbol-area").style("min-height:72px"):
                                        unit_symbol(card, "sm", formation.id)
                                    ui.label(card.tagline).classes("text-xs font-bold")
                                    card_stats(card)
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            if selected_id and planned_lane:
                                planned_label = {
                                    "left": "左", "center": "中央", "right": "右"
                                }[str(planned_lane)]
                                ui.label(
                                    f"予定：{get_card(str(selected_id)).name}を"
                                    f"{planned_label}戦線へ"
                                ).classes("font-bold")
                            else:
                                ui.label("カードと配置先を選んでください").classes("muted text-sm")
                            send_button = primary_button("命令を送信", icon="send", on_click=request_pvp_confirmation)
                            if not selected_id or not planned_lane or submitted:
                                send_button.props("disable")

                with ui.column().classes("battle-side w-full gap-4"):
                    with ui.card().classes("panel"):
                        section_heading("対人戦のポイント")
                        ui.label("先に送っても内容は相手へ見えません。両者が送った時だけ公開・解決します。").classes("section-subtitle mt-2")
                    with ui.expansion(
                        "公開済みログ", icon="receipt_long", value=bool(preferences["auto_logs"])
                    ).classes("details-expansion"):
                        with ui.column().classes("w-full gap-2 mt-2"):
                            for event in reversed(game["events"][-10:]):
                                ui.label(f"R{event['round_no']}：{event['message']}").classes("log-entry")
                    secondary_button("対戦から退出", icon="logout", on_click=leave_pvp)

        pvp_board()

        def poll_pvp() -> None:
            view = poll_multiplayer(app.storage.user)
            game = view.get("game", {}) if isinstance(view, dict) else {}
            digest = repr((
                view.get("status") if isinstance(view, dict) else "idle",
                game.get("round_no") if isinstance(game, dict) else None,
                view.get("submitted") if isinstance(view, dict) else None,
                len(game.get("events", [])) if isinstance(game, dict) else 0,
                (view.get("opponent") or {}).get("connected") if isinstance(view, dict) else None,
            ))
            if digest != last_poll["digest"]:
                last_poll["digest"] = digest
                pvp_board.refresh()

        register_client_poll(
            poll_pvp, cleanup=lambda: disconnect_multiplayer(user_storage)
        )


@ui.page("/battle")
def battle_page() -> None:
    online_view = poll_multiplayer(app.storage.user)
    online_status = str(online_view.get("status", "idle"))
    if online_status in {"playing", "complete", "opponent_left"}:
        go("/pvp")
        return
    if online_status == "waiting":
        go("/online")
        return
    if online_status == "waiting_friend":
        go("/friend")
        return
    if online_status == "left":
        try:
            close_multiplayer_session(app.storage.user)
        except MultiplayerError:
            pass
    player = ensure_player_state(app.storage.user)
    if load_match(app.storage.user) is None and player["selected_mode"] != "training":
        player = update_state_mode(player, "training")
        player = store_player_state(app.storage.user, player)
    preferences = player["preferences"]
    try:
        state = start_match(app.storage.user)
    except RuleViolation:
        with page_shell(
            "/lobby", "LIVE OPERATION", "対戦を開始できません",
            f"対戦には所持しているカードを{MAX_ROUNDS}枚以上入れたデッキが必要です。",
        ):
            with ui.card().classes("panel"):
                ui.icon("warning", size="38px").classes("yellow-text")
                ui.label("デッキのカードが足りません").classes("text-2xl font-bold")
                ui.label("デッキ編成で6〜12枚を選ぶと、対戦を始められます。").classes("section-subtitle")
                primary_button("デッキを編成する", "/deck", "view_carousel").classes("mt-3")
        return

    context = get_match_context(app.storage.user) or {
        "mode": player["selected_mode"],
        "formation": player["selected_formation"],
    }
    formation = get_formation(str(context["formation"]))
    mode_labels = {
        "training": "初心者演習",
        "casual": "カジュアル対戦",
        "ranked": "ランク対戦",
        "friend": "フレンド対戦",
    }
    selection_key = "battle_selection"

    def get_selection() -> dict[str, object]:
        active = load_match(app.storage.user)
        game_id = active.game_id if active else ""
        raw = app.storage.user.get(selection_key)
        if not isinstance(raw, dict) or raw.get("game_id") != game_id:
            raw = {"game_id": game_id, "selected": None, "planned_lane": None, "resolving": False}
            app.storage.user[selection_key] = raw
        return dict(raw)

    def set_selection(**changes: object) -> dict[str, object]:
        selected = get_selection()
        selected.update(changes)
        app.storage.user[selection_key] = selected
        return selected

    def select_card(card_id: str) -> None:
        active = load_match(app.storage.user)
        if active is None or card_id not in active.players[HUMAN_PLAYER_ID].hand:
            ui.notify("そのカードは現在の手札にありません。", type="warning")
            return
        set_selection(selected=card_id, planned_lane=None)
        battle_board.refresh()

    def plan_lane(lane_id: str) -> None:
        selected = get_selection()
        if not selected.get("selected"):
            ui.notify("先に手札からカードを選んでください。", type="warning")
            return
        set_selection(planned_lane=lane_id)
        battle_board.refresh()

    def execute_order() -> None:
        selected = get_selection()
        card_id = selected.get("selected")
        lane_id = selected.get("planned_lane")
        if not card_id or not lane_id:
            ui.notify("カードと配置先の戦線を選んでください。", type="warning")
            return
        set_selection(resolving=True)
        try:
            _, resolution = play_player_round(
                app.storage.user, str(card_id), str(lane_id)
            )
        except RuleViolation as error:
            set_selection(resolving=False)
            ui.notify(str(error), type="negative")
            battle_board.refresh()
            return
        set_selection(selected=None, planned_lane=None, resolving=False)
        if preferences["slow_resolution"]:
            resolved_state = load_match(app.storage.user)
            round_events = [
                event.message for event in (resolved_state.events if resolved_state else [])
                if event.round_no == resolution.round_no
                and (event.visible_to is None or HUMAN_PLAYER_ID in event.visible_to)
                and event.kind not in {"order_submitted"}
            ][-6:]
            for index, message in enumerate(round_events):
                ui.notify(
                    f"{index + 1}. {message}", type="positive", timeout=2200,
                    position="bottom-right",
                )
        else:
            ui.notify("ラウンドを解決しました。", type="positive")
        battle_board.refresh()

    def request_confirmation() -> None:
        selected = get_selection()
        card_id = selected.get("selected")
        lane_id = selected.get("planned_lane")
        if not card_id or not lane_id:
            ui.notify("カードと配置先の戦線を選んでください。", type="warning")
            return
        if preferences["confirm_orders"]:
            lane_name = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}[str(lane_id)]
            confirm_text.text = f"{get_card(str(card_id)).name}を{lane_name}へ配備します。"
            confirm_dialog.open()
        else:
            execute_order()

    def close_and_execute() -> None:
        confirm_dialog.close()
        execute_order()

    def reset_battle() -> None:
        fresh = restart_match(app.storage.user)
        app.storage.user[selection_key] = {
            "game_id": fresh.game_id,
            "selected": None,
            "planned_lane": None,
            "resolving": False,
        }
        battle_board.refresh()
        ui.notify("同じ設定で新しい対戦を始めました。", type="positive")

    def leave_battle() -> None:
        abandon_match(app.storage.user)
        app.storage.user.pop(selection_key, None)
        go("/lobby")

    with ui.dialog() as confirm_dialog, ui.card().classes("dialog-card"):
        ui.label("この命令でよいですか？").classes("text-xl font-bold")
        confirm_text = ui.label().classes("section-subtitle")
        ui.label("確定すると両者の配置先が同時に決まり、相手カードは未確認で置かれます。").classes("muted text-xs")
        with ui.row().classes("gap-2 mt-3"):
            primary_button("確定して解決", icon="check", on_click=close_and_execute)
            secondary_button("選び直す", icon="close", on_click=confirm_dialog.close)

    with page_shell(
        "/lobby", "LIVE OPERATION", f"{mode_labels.get(str(context['mode']), '対戦')}・対戦中",
        "カードを1枚選び、配置する戦線を選んでから命令を確定します。",
    ):
        @ui.refreshable
        def battle_board() -> None:
            active = load_match(app.storage.user)
            if active is None:
                active = start_match(app.storage.user)
            selected = get_selection()
            selected_id = selected.get("selected")
            planned_lane = selected.get("planned_lane")
            resolving = bool(selected.get("resolving"))
            human = active.players[HUMAN_PLAYER_ID]
            opponent = active.players[AI_PLAYER_ID]

            with ui.element("div").classes("battle-status"):
                with ui.element("div").classes("battle-account"):
                    account_icon(
                        player["profile"].get("selected_symbol"),
                        str(player["profile"]["display_name"]),
                    )
                    with ui.column().classes("gap-0"):
                        ui.label(f"{player['profile']['display_name']} / あなた").classes("font-bold")
                        ui.label(f"任務点 {human.mission_points}").classes("mono blue-text text-xs")
                with ui.column().classes("items-center gap-0"):
                    ui.label(f"ROUND {active.round_no} / {active.max_rounds}").classes("mono text-xl font-bold")
                    ui.label("解決済み" if active.phase is Phase.COMPLETE else "命令を選んでください").classes("muted text-xs")
                with ui.column().classes("items-end gap-0"):
                    ui.label(f"{opponent.name} / 相手").classes("font-bold")
                    ui.label(f"任務点 {opponent.mission_points}・AIが待機中").classes("green-text text-xs")

            if active.phase is Phase.COMPLETE and active.result is not None:
                completed_context = get_match_context(app.storage.user) or {}
                rewards = completed_context.get("rewards", {})
                reward_cards = [
                    get_card(card_id).name for card_id in rewards.get("cards", [])
                ] if isinstance(rewards, dict) else []
                reward_symbols = rewards.get("symbols", []) if isinstance(rewards, dict) else []
                winner = active.result.winner_id
                if winner == HUMAN_PLAYER_ID:
                    result_title, result_badge, badge_class = "作戦成功", "勝利", "green-text"
                elif winner is None:
                    result_title, result_badge, badge_class = "互角の結果", "引き分け", "yellow-text"
                else:
                    result_title, result_badge, badge_class = "作戦終了", "敗北", "danger-text"
                with ui.element("div").classes("result-banner"):
                    ui.label(result_badge).classes(f"page-eyebrow {badge_class}")
                    ui.label(result_title).classes("text-2xl font-bold mt-1")
                    ui.label(
                        f"最終任務点：あなた {human.mission_points} - {opponent.mission_points} 相手"
                    ).classes("text-sm mt-2")
                    ui.label(active.result.summary).classes("section-subtitle mt-1")
                    if reward_cards or reward_symbols:
                        with ui.element("div").classes("beginner-callout mt-3"):
                            ui.label("コレクション報酬").classes("font-bold")
                            if reward_cards:
                                ui.label(f"新しいカード：{'・'.join(reward_cards)}").classes("text-sm")
                            if reward_symbols:
                                ui.label(f"新しい記号：{len(reward_symbols)}種類").classes("text-sm")
                    with ui.row().classes("gap-2 mt-4"):
                        primary_button("同じ条件でもう一度", icon="replay", on_click=reset_battle)
                        secondary_button("戦績を見る", "/profile", "military_tech")
                        secondary_button("デッキを調整", "/deck", "view_carousel")
                        secondary_button("ホームへ", "/", "home")
                return

            if not selected_id:
                focus_title = "① 下の手札からカードを1枚選ぶ"
                focus_note = "迷ったら偵察か歩兵を選ぶと、状況を理解しやすくなります。"
                focus_step = 1
            elif not planned_lane:
                focus_title = "② 選んだカードを置く場所を決める"
                focus_note = "数字が低い戦線を補うか、優勢な戦線を確実に取ります。"
                focus_step = 2
            else:
                focus_title = "③ 内容を確認して命令を決定する"
                focus_note = "相手も1枚を同時に出し、3戦線の力を比べます。"
                focus_step = 3

            if preferences["beginner_mode"] or preferences["recommended_actions"]:
                with ui.element("div").classes("battle-focus"):
                    with ui.column().classes("gap-1 flex-1"):
                        ui.label("いま見る場所").classes("page-eyebrow beginner-only")
                        ui.label(focus_title).classes("text-xl font-bold")
                        if preferences["recommended_actions"]:
                            ui.label(focus_note).classes("section-subtitle recommendation-only")
                    with ui.element("div").classes("action-steps"):
                        action_step(1, "カード", active=focus_step == 1, done=focus_step > 1)
                        action_step(2, "場所", active=focus_step == 2, done=focus_step > 2)
                        action_step(3, "決定", active=focus_step == 3)

            with ui.expansion(
                "詳しい解決順を見る", icon="timeline", value=bool(preferences["slow_resolution"])
            ).classes("details-expansion"):
                with ui.element("div").classes("phase-strip mt-2"):
                    for index, (name, _) in enumerate(PHASES):
                        ui.label(f"{index + 1} {name}").classes("phase-item")

            with ui.element("div").classes("battle-layout"):
                with ui.column().classes("w-full gap-4 battle-board-column"):
                    with ui.element("div").classes("lane-grid"):
                        lane_labels = {
                            "left": ("左戦線（左翼）", "森林"),
                            "center": ("中央戦線", "市街地"),
                            "right": ("右戦線（右翼）", "平地"),
                        }
                        for lane_id, (lane_name, terrain) in lane_labels.items():
                            lane = active.lanes[lane_id]
                            own_power = calculate_lane_power(active, lane_id, HUMAN_PLAYER_ID)
                            enemy_power = calculate_lane_power(
                                active, lane_id, AI_PLAYER_ID, visible_to=HUMAN_PLAYER_ID
                            )
                            own_deployments = [d for d in lane.deployments if d.player_id == HUMAN_PLAYER_ID]
                            enemy_deployments = [d for d in lane.deployments if d.player_id == AI_PLAYER_ID]
                            hidden_enemy_count = sum(
                                not deployment.visible_to(HUMAN_PLAYER_ID)
                                for deployment in enemy_deployments
                            )
                            planned_class = " battle-lane--planned" if planned_lane == lane_id else ""
                            with ui.element("div").classes(f"battle-lane{planned_class}"):
                                with ui.row().classes("lane-header items-center justify-between"):
                                    with ui.column().classes("gap-0"):
                                        ui.label(lane_name).classes("font-bold")
                                        ui.label(terrain).classes("muted text-xs")
                                    difference = own_power.total - enemy_power.total
                                    if hidden_enemy_count:
                                        chip(f"未確認 {hidden_enemy_count}部隊", "yellow")
                                    elif difference > 0:
                                        chip(f"あなたが優勢 +{difference}", "green")
                                    elif difference < 0:
                                        chip(f"相手が優勢 +{abs(difference)}", "red")
                                    else:
                                        chip("互角", "yellow")
                                ui.label("相手部隊").classes("muted text-xs mt-3")
                                if not enemy_deployments:
                                    ui.label("まだ配備なし").classes("unknown-unit")
                                for deployment in enemy_deployments[-3:]:
                                    visible = deployment.visible_to(HUMAN_PLAYER_ID)
                                    with ui.element("div").classes("unknown-unit"):
                                        ui.icon("visibility" if visible else "help_outline", size="21px")
                                        ui.label(get_card(deployment.card_id).name if visible else "未確認部隊")
                                with ui.element("div").classes("control-meter mt-3"):
                                    ui.label(f"味方 {own_power.total}").classes("blue-text")
                                    ui.label("戦線力").classes("muted")
                                    enemy_total = f"{enemy_power.total}+?" if hidden_enemy_count else str(enemy_power.total)
                                    ui.label(f"敵 {enemy_total}").classes("danger-text text-right")
                                ui.label("あなたの部隊").classes("muted text-xs mt-3")
                                with ui.element("div").classes("front-line"):
                                    ui.label(
                                        "・".join(get_card(d.card_id).name for d in own_deployments[-3:]) or "まだ配備なし"
                                    ).classes("font-bold text-sm")
                                    ui.label(
                                        f"制圧 {own_power.control} / 支援 {own_power.active_support} / 補給差 {own_power.supply_generated - own_power.supply_demand:+d}"
                                    ).classes("muted text-xs")
                                place_button = ui.button(
                                    "ここに配置", icon="place", on_click=lambda lid=lane_id: plan_lane(lid)
                                ).props("flat no-caps").classes("card-action mt-3")
                                if not selected_id or resolving:
                                    place_button.props("disable")

                    with ui.card().classes("panel battle-hand-panel"):
                        with ui.row().classes("w-full items-center justify-between"):
                            with ui.column().classes("gap-0"):
                                ui.label(f"手札（残り {len(human.hand)}枚）").classes("section-title")
                                ui.label("カード下部の4ステータスを見て、1ラウンドに1枚使います。").classes("section-subtitle")
                            with ui.row().classes("gap-2"):
                                chip(mode_labels.get(str(context["mode"]), "対戦"), "green")
                                if formation.id != "native":
                                    chip(f"{formation.marker} {formation.name}", "yellow")
                        with ui.element("div").classes("hand-strip mt-3"):
                            for card_id in human.hand:
                                card = get_card(card_id)
                                selected_class = " hand-card--selected" if selected_id == card_id else ""
                                hand_card = ui.card().classes(f"hand-card{selected_class}")
                                if not resolving:
                                    hand_card.on("click", lambda cid=card_id: select_card(cid))
                                with hand_card:
                                    with ui.row().classes("w-full items-start justify-between no-wrap"):
                                        ui.label(card.branch).classes("unit-card__branch")
                                    ui.label(card.name).classes("font-bold text-sm min-h-10")
                                    with ui.element("div").classes("unit-card__symbol-area").style("min-height:72px"):
                                        unit_symbol(card, "sm", formation.id)
                                    ui.label(card.tagline).classes("text-xs font-bold")
                                    card_stats(card)
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.column().classes("gap-0 flex-1"):
                                if selected_id and planned_lane:
                                    card = get_card(str(selected_id))
                                    lane_name = {"left": "左戦線", "center": "中央戦線", "right": "右戦線"}[str(planned_lane)]
                                    ui.label(f"予定：{card.name}を{lane_name}へ配置").classes("font-bold")
                                    ui.label("確定後、相手の命令と戦線結果を同時に解決します。").classes("muted text-xs")
                                else:
                                    ui.label("カードと配置先を選んでください").classes("muted text-sm")
                            confirm_button = primary_button("命令を確定", icon="check", on_click=request_confirmation)
                            if not selected_id or not planned_lane or resolving:
                                confirm_button.props("disable")
                            secondary_button(
                                "選択を解除", icon="undo",
                                on_click=lambda: (set_selection(selected=None, planned_lane=None), battle_board.refresh()),
                            )

                with ui.column().classes("battle-side w-full gap-4"):
                    with ui.card().classes("panel"):
                        section_heading("この戦線力の見方")
                        ui.label("制圧が前線の土台、支援は制圧部隊がいると加算、補給不足は減点です。").classes("section-subtitle mt-2")
                        if formation.id != "native":
                            ui.label(f"編制表示：{formation.marker} {formation.name}（強さへの追加補正なし）").classes("yellow-text text-xs font-bold mt-2")
                    with ui.expansion(
                        "これまでに起きたこと", icon="receipt_long", value=bool(preferences["auto_logs"])
                    ).classes("details-expansion"):
                        visible_events = [
                            event for event in active.events
                            if event.visible_to is None or HUMAN_PLAYER_ID in event.visible_to
                        ]
                        with ui.column().classes("w-full gap-2 mt-2"):
                            for event in reversed(visible_events[-10:]):
                                ui.label(f"R{event.round_no}：{event.message}").classes("log-entry")
                    secondary_button("同じ条件で最初から", icon="restart_alt", on_click=reset_battle)
                    secondary_button("対戦を終了して戻る", icon="logout", on_click=leave_battle)

        battle_board()


def start_fresh_simulation(player: dict[str, object] | None = None) -> SimulationState:
    """Create and persist a fresh advanced match for the current browser."""

    current = player or ensure_player_state(app.storage.user)
    current = update_state_mode(current, "simulation")
    current = store_player_state(app.storage.user, current)
    deck = list(current["progression"]["advanced_deck"])
    state = new_simulation(
        deck,
        player_name=str(current["profile"]["display_name"]),
    )
    app.storage.user[SIMULATION_MATCH_STORAGE_KEY] = state.to_dict()
    app.storage.user.pop(SIMULATION_RECORDED_STORAGE_KEY, None)
    app.storage.user.pop(SIMULATION_REWARDS_STORAGE_KEY, None)
    return state


def load_or_start_simulation(player: dict[str, object]) -> SimulationState:
    raw = app.storage.user.get(SIMULATION_MATCH_STORAGE_KEY)
    if isinstance(raw, dict):
        try:
            return SimulationState.from_dict(raw)
        except (KeyError, TypeError, ValueError, SimulationRuleError):
            pass
    return start_fresh_simulation(player)


def save_simulation(state: SimulationState) -> None:
    app.storage.user[SIMULATION_MATCH_STORAGE_KEY] = state.to_dict()


def record_simulation_completion(state: SimulationState) -> None:
    """Record one advanced result and grant the same outcome-based symbols."""

    if state.result is None:
        return
    if app.storage.user.get(SIMULATION_RECORDED_STORAGE_KEY) == state.game_id:
        return
    result = (
        "win" if state.result.winner_id == "player"
        else "draw" if state.result.winner_id is None
        else "loss"
    )
    player = ensure_player_state(app.storage.user)
    rewards = collection_rewards_for_outcome(player, result)
    updated = record_result(
        player,
        result,
        mode="simulation",
        opponent="統合作戦AI",
        mission_points_for=state.players["player"].mission_points,
        mission_points_against=state.players["opponent"].mission_points,
        turns=state.result.rounds_played,
        summary=state.result.summary,
        unlocked_symbols=rewards["symbols"],
    )
    store_player_state(app.storage.user, updated)
    app.storage.user[SIMULATION_RECORDED_STORAGE_KEY] = state.game_id
    app.storage.user[SIMULATION_REWARDS_STORAGE_KEY] = rewards


@ui.page("/simulation")
def simulation_page() -> None:
    with page_shell(
        "/simulation", "ADVANCED SIMULATION", "本格統合作戦シミュレーション",
        "基本18枚を集めた後の上級ルールです。全201記号をカードとして使い、12ターンで3作戦域を争います。",
    ):
        player = ensure_player_state(app.storage.user)
        owned_count = len(player["collection"]["owned_cards"])
        if not player["progression"]["simulation_unlocked"]:
            with ui.element("section").classes("simulation-hero"):
                ui.icon("lock", size="44px").classes("yellow-text")
                with ui.column().classes("gap-2 flex-1"):
                    chip(f"基本カード {owned_count} / {len(CARDS)}枚", "yellow")
                    ui.label("まず18枚を集めると開放されます").classes("text-2xl font-bold")
                    ui.label(
                        "通常対戦で基本カードを少しずつ集めてください。開放後も、これまでの18枚ルールは"
                        "『カジュアル』としていつでも遊べます。"
                    ).classes("section-subtitle")
                    ui.linear_progress(value=owned_count / len(CARDS)).props(
                        "rounded size=10px"
                    ).classes("progress-track w-full")
                    with ui.row().classes("gap-2"):
                        primary_button("通常対戦で集める", "/lobby", "play_arrow")
                        secondary_button("所持カードを確認", "/advanced-cards", "style")
            with ui.card().classes("panel"):
                section_heading("開放後に増える要素", "いきなり覚える必要はありません。画面内で意味を説明します。")
                with ui.element("div").classes("three-grid mt-3"):
                    for title, text, icon in (
                        ("全201カード", "参照画像のすべての記号が、検索できるカードになります。", "library_books"),
                        ("12ターン", "通常の9ラウンドより長く、複数の作戦を組み立てます。", "schedule"),
                        ("統合作戦", "制圧・支援・偵察・補給に、指揮・機動・領域連携が加わります。", "hub"),
                    ):
                        with ui.element("div").classes("simulation-status"):
                            ui.icon(icon).classes("blue-text")
                            ui.label(title).classes("font-bold")
                            ui.label(text).classes("section-subtitle")
            return

        player = update_state_mode(player, "simulation")
        player = store_player_state(app.storage.user, player)
        state = load_or_start_simulation(player)
        selection: dict[str, str | None] = {"card": None, "theater": None}

        def select_simulation_card(card_id: str) -> None:
            active = load_or_start_simulation(ensure_player_state(app.storage.user))
            if active.phase is SimulationPhase.COMPLETE:
                return
            if card_id not in active.players["player"].hand:
                ui.notify("そのカードはすでに使用しました。", type="warning")
                return
            selection["card"] = card_id
            simulation_board.refresh()

        def select_theater(theater_id: str) -> None:
            selection["theater"] = theater_id
            simulation_board.refresh()

        def execute_simulation_order() -> None:
            card_id = selection.get("card")
            theater_id = selection.get("theater")
            if not card_id or not theater_id:
                ui.notify("カードと配備先の作戦域を選んでください。", type="warning")
                return
            active = load_or_start_simulation(ensure_player_state(app.storage.user))
            try:
                play_simulation_round(active, "player", card_id, theater_id)
            except SimulationRuleError as error:
                ui.notify(str(error), type="negative")
                return
            save_simulation(active)
            selection.update(card=None, theater=None)
            if active.phase is SimulationPhase.COMPLETE:
                record_simulation_completion(active)
                ui.notify("12ターンの結果を確定しました。", type="positive")
            else:
                ui.notify(f"第{active.round_no - 1}ターンを解決しました。", type="positive")
            simulation_board.refresh()

        def reset_simulation() -> None:
            start_fresh_simulation(ensure_player_state(app.storage.user))
            selection.update(card=None, theater=None)
            simulation_board.refresh()
            ui.notify("新しい12ターン作戦を開始しました。", type="positive")

        @ui.refreshable
        def simulation_board() -> None:
            active = load_or_start_simulation(ensure_player_state(app.storage.user))
            if active.phase is SimulationPhase.COMPLETE:
                record_simulation_completion(active)
            human = active.players["player"]
            opponent = active.players["opponent"]

            with ui.element("section").classes("simulation-hero"):
                with ui.column().classes("gap-1 flex-1"):
                    chip("上級ルール", "yellow")
                    ui.label("3つの作戦域へ、毎ターン1枚を配備").classes("text-2xl font-bold")
                    ui.label(
                        "まずカード、次に作戦域を選びます。相手も同時に1枚を置き、ターンごとに任務点を争います。"
                    ).classes("section-subtitle")
                with ui.row().classes("gap-2"):
                    secondary_button("24枚デッキを編集", "/simulation-deck", "tune")
                    secondary_button("最初から", icon="restart_alt", on_click=reset_simulation)

            with ui.element("div").classes("simulation-status-grid"):
                with ui.element("div").classes("simulation-status"):
                    ui.label("ターン").classes("muted text-xs")
                    ui.label(
                        f"{active.max_rounds} / {active.max_rounds}" if active.phase is SimulationPhase.COMPLETE
                        else f"{active.round_no} / {active.max_rounds}"
                    ).classes("mono text-2xl font-bold")
                with ui.element("div").classes("simulation-status"):
                    ui.label("あなたの任務点").classes("muted text-xs")
                    ui.label(str(human.mission_points)).classes("mono text-2xl font-bold blue-text")
                with ui.element("div").classes("simulation-status"):
                    ui.label("AIの任務点").classes("muted text-xs")
                    ui.label(str(opponent.mission_points)).classes("mono text-2xl font-bold danger-text")

            if active.phase is SimulationPhase.COMPLETE and active.result is not None:
                winner = active.result.winner_id
                title = "作戦成功" if winner == "player" else "引き分け" if winner is None else "作戦終了"
                color = "green-text" if winner == "player" else "yellow-text" if winner is None else "danger-text"
                rewards = app.storage.user.get(SIMULATION_REWARDS_STORAGE_KEY, {})
                with ui.element("div").classes("result-banner"):
                    ui.label(title).classes(f"text-3xl font-bold {color}")
                    ui.label(active.result.summary).classes("section-subtitle mt-2")
                    ui.label(
                        f"最終確保：あなた {active.result.theaters_controlled['player']}域 / "
                        f"AI {active.result.theaters_controlled['opponent']}域"
                    ).classes("font-bold mt-2")
                    if isinstance(rewards, dict) and rewards.get("symbols"):
                        ui.label(
                            f"コレクション報酬：アカウントアイコン用の記号 {len(rewards['symbols'])}種類"
                        ).classes("text-sm yellow-text")
                    with ui.row().classes("gap-2 mt-4"):
                        primary_button("新しい作戦", icon="replay", on_click=reset_simulation)
                        secondary_button("戦績を見る", "/profile", "military_tech")
                        secondary_button("通常の18枚ルール", "/lobby", "style")
                return

            ui.label("作戦域を選ぶ").classes("section-title")
            ui.label(
                "表示中の敵戦力は偵察済みのカードだけです。『未確認』があれば実際はさらに高い可能性があります。"
            ).classes("section-subtitle")
            with ui.element("div").classes("simulation-theater-grid"):
                for theater_id in THEATER_IDS:
                    theater = active.theaters[theater_id]
                    own_power = calculate_simulation_power(active, theater_id, "player")
                    visible_enemy = calculate_simulation_power(
                        active, theater_id, "opponent", visible_to="player"
                    )
                    own_units = [item for item in theater.deployments if item.player_id == "player"]
                    enemy_units = [item for item in theater.deployments if item.player_id == "opponent"]
                    hidden_count = sum(not item.visible_to("player") for item in enemy_units)
                    selected_class = (
                        " simulation-theater--selected"
                        if selection.get("theater") == theater_id else ""
                    )
                    with ui.element("div").classes(f"simulation-theater{selected_class}"):
                        with ui.row().classes("w-full items-center justify-between"):
                            ui.label(theater.label).classes("font-bold")
                            chip(f"未確認 {hidden_count}" if hidden_count else "偵察済み", "yellow" if hidden_count else "green")
                        with ui.element("div").classes("control-meter"):
                            ui.label(f"味方 {own_power.total}").classes("blue-text")
                            ui.label("現在戦力").classes("muted")
                            ui.label(
                                f"敵 {visible_enemy.total}+?" if hidden_count else f"敵 {visible_enemy.total}"
                            ).classes("danger-text text-right")
                        ui.label("味方の配備").classes("muted text-xs")
                        ui.label(
                            "・".join(get_advanced_card(item.card_id).name for item in own_units[-3:])
                            or "まだ配備なし"
                        ).classes("text-sm font-bold")
                        ui.label(
                            f"制圧 {own_power.control} / 有効支援 {own_power.active_support} / "
                            f"補給不足 {own_power.supply_deficit} / 領域連携 +{own_power.domain_bonus}"
                        ).classes("muted text-xs")
                        ui.button(
                            "この作戦域を選ぶ", icon="place",
                            on_click=lambda tid=theater_id: select_theater(tid),
                        ).props("flat no-caps").classes("card-action")

            with ui.card().classes("panel simulation-hand"):
                with ui.row().classes("w-full items-center justify-between gap-3"):
                    with ui.column().classes("gap-0"):
                        ui.label(f"手札（残り {len(human.hand)}枚）").classes("section-title")
                        ui.label("上段の制圧・支援・偵察・補給は全カード共通です。指揮・機動は下段に表示します。").classes("section-subtitle")
                    chip(
                        get_advanced_card(str(selection["card"])).name if selection.get("card") else "カード未選択",
                        "green" if selection.get("card") else "",
                    )
                with ui.element("div").classes("simulation-card-grid"):
                    for card_id in human.hand:
                        card = get_advanced_card(card_id)
                        selected_class = (
                            " simulation-card--selected" if selection.get("card") == card_id else ""
                        )
                        card_element = ui.card().classes(f"simulation-card{selected_class}")
                        card_element.on("click", lambda cid=card_id: select_simulation_card(cid))
                        with card_element:
                            with ui.row().classes("w-full items-start justify-between gap-2 no-wrap"):
                                with ui.column().classes("gap-0 min-w-0"):
                                    ui.label(card.domain.value).classes("page-eyebrow")
                                    ui.label(card.name).classes("font-bold text-sm")
                                chip(card.rarity, "yellow" if card.rarity != "標準" else "")
                            advanced_symbol(card)
                            ui.label(card.plain_role).classes("muted text-xs")
                            advanced_stats(card)

                with ui.element("div").classes("simulation-controls"):
                    if selection.get("card") and selection.get("theater"):
                        ui.label(
                            f"予定：{get_advanced_card(str(selection['card'])).name}を"
                            f"{THEATER_LABELS[str(selection['theater'])]}へ配備"
                        ).classes("font-bold")
                    else:
                        ui.label("カードと作戦域を1つずつ選んでください").classes("muted text-sm")
                    confirm = primary_button(
                        "命令を確定して1ターン進める", icon="check",
                        on_click=execute_simulation_order,
                    )
                    if not selection.get("card") or not selection.get("theater"):
                        confirm.props("disable")

            with ui.expansion("上級ルールの数字を確認", icon="menu_book").classes("details-expansion"):
                with ui.element("div").classes("three-grid mt-3"):
                    for title, body in (
                        ("指揮", "同じ作戦域の指揮合計3ごとに+1。最大+6です。"),
                        ("機動", "同じ作戦域の機動合計5ごとに+1。最大+4です。"),
                        ("領域連携", "陸・海・空宇宙など異なる領域が2種類以上そろうと、追加1領域ごとに+2です。"),
                    ):
                        with ui.element("div").classes("simulation-status"):
                            ui.label(title).classes("font-bold blue-text")
                            ui.label(body).classes("section-subtitle")

        simulation_board()


@ui.page("/simulation-deck")
def simulation_deck_page() -> None:
    with page_shell(
        "/simulation", "ADVANCED DECK", "本格シミュレーション用デッキ",
        "全201カードから12〜24枚を選びます。最初は自動作成された24枚のままで問題ありません。",
    ):
        player = ensure_player_state(app.storage.user)
        if not player["progression"]["simulation_unlocked"]:
            with ui.card().classes("panel"):
                ui.label("このデッキ編集は基本18枚を集めると開放されます。").classes("text-xl font-bold")
                secondary_button("開放条件を見る", "/simulation", "lock").classes("mt-3")
            return

        filter_state: dict[str, object] = {"visible": 24}

        def refresh_filters() -> None:
            filter_state["visible"] = 24
            advanced_catalog.refresh()

        def toggle_advanced_card(card_id: str) -> None:
            current = ensure_player_state(app.storage.user)
            selected = list(current["progression"]["advanced_deck"])
            if card_id in selected:
                if len(selected) <= 12:
                    ui.notify("対戦に必要な最低12枚は残してください。", type="warning")
                    return
                selected.remove(card_id)
            else:
                if len(selected) >= 24:
                    ui.notify("最大24枚です。先に1枚外してください。", type="warning")
                    return
                selected.append(card_id)
            try:
                current = update_state_advanced_deck(current, selected)
            except ValueError as error:
                ui.notify(str(error), type="negative")
                return
            store_player_state(app.storage.user, current)
            selected_deck.refresh()
            advanced_catalog.refresh()

        def reset_advanced_deck() -> None:
            current = update_state_advanced_deck(
                ensure_player_state(app.storage.user), ADVANCED_STARTER_DECK
            )
            store_player_state(app.storage.user, current)
            selected_deck.refresh()
            advanced_catalog.refresh()
            ui.notify("領域を均等にした公式24枚へ戻しました。", type="positive")

        def start_selected_simulation() -> None:
            start_fresh_simulation(ensure_player_state(app.storage.user))
            go("/simulation")

        with ui.element("section").classes("simulation-hero"):
            with ui.column().classes("gap-1 flex-1"):
                chip("全201カード使用可能", "green")
                ui.label("全部を一度に読む必要はありません").classes("text-2xl font-bold")
                ui.label(
                    "検索と領域フィルターで少しずつ見られます。24枚のうち実戦で使うのは12枚です。"
                ).classes("section-subtitle")
            with ui.row().classes("gap-2"):
                primary_button("このデッキで新規作戦", icon="play_arrow", on_click=start_selected_simulation)
                secondary_button("公式24枚へ戻す", icon="restart_alt", on_click=reset_advanced_deck)

        @ui.refreshable
        def selected_deck() -> None:
            current = ensure_player_state(app.storage.user)
            deck = list(current["progression"]["advanced_deck"])
            section_heading(
                f"選択中 {len(deck)} / 24枚",
                "カードを押すと外せます。12枚未満にはできません。",
            )
            with ui.element("div").classes("simulation-deck-grid"):
                for card_id in deck:
                    card = get_advanced_card(card_id)
                    with ui.button(
                        on_click=lambda cid=card_id: toggle_advanced_card(cid)
                    ).props("flat no-caps").classes("simulation-card simulation-card--selected"):
                        advanced_symbol(card)
                        ui.label(card.name).classes("font-bold text-xs")
                        ui.label(f"{card.domain.value}・{card.play_kind.value}").classes("muted text-xs")

        selected_deck()

        domain_values = ["すべて", *dict.fromkeys(card.domain.value for card in ADVANCED_CARDS)]
        kind_values = ["すべて", *dict.fromkeys(card.play_kind.value for card in ADVANCED_CARDS)]
        with ui.element("div").classes("simulation-filter-bar"):
            query_input = ui.input(
                "カード名・役割を検索", placeholder="例：偵察、航空、補給",
                on_change=lambda _: refresh_filters(),
            ).props("outlined clearable").classes("filter-control")
            domain_select = ui.select(
                domain_values, value="すべて", label="領域",
                on_change=lambda _: refresh_filters(),
            ).props("outlined options-dense").classes("filter-control")
            kind_select = ui.select(
                kind_values, value="すべて", label="種類",
                on_change=lambda _: refresh_filters(),
            ).props("outlined options-dense").classes("filter-control")

        @ui.refreshable
        def advanced_catalog() -> None:
            query = str(query_input.value or "")
            domain = None if domain_select.value == "すべて" else str(domain_select.value)
            kind = None if kind_select.value == "すべて" else str(kind_select.value)
            matches = search_advanced_cards(query, domain=domain, play_kind=kind)
            visible = min(len(matches), int(filter_state["visible"]))
            deck = set(ensure_player_state(app.storage.user)["progression"]["advanced_deck"])
            section_heading(
                f"カード一覧 {len(matches)}件",
                f"最初の{visible}件を表示中。選択中のカードには青い枠が付きます。",
            )
            if not matches:
                ui.label("条件に合うカードがありません。検索語を短くしてみてください。").classes("section-subtitle")
                return
            with ui.element("div").classes("simulation-card-grid"):
                for card in matches[:visible]:
                    selected_class = " simulation-card--selected" if card.id in deck else ""
                    element = ui.card().classes(f"simulation-card{selected_class}")
                    element.on("click", lambda cid=card.id: toggle_advanced_card(cid))
                    with element:
                        with ui.row().classes("w-full items-start justify-between gap-2 no-wrap"):
                            with ui.column().classes("gap-0 min-w-0"):
                                ui.label(card.domain.value).classes("page-eyebrow")
                                ui.label(card.name).classes("font-bold text-sm")
                            chip("選択中", "green") if card.id in deck else chip(card.rarity)
                        advanced_symbol(card)
                        ui.label(f"{card.play_kind.value}・{card.plain_role}").classes("muted text-xs")
                        advanced_stats(card)
            if visible < len(matches):
                secondary_button(
                    "さらに24件を見る", icon="expand_more",
                    on_click=lambda: (
                        filter_state.update(visible=int(filter_state["visible"]) + 24),
                        advanced_catalog.refresh(),
                    ),
                ).classes("mt-3")

        advanced_catalog()


@ui.page("/account")
def account_page() -> None:
    username = signed_in_username()
    with page_shell(
        "/account", "ACCOUNT", "アカウントと保存",
        "ログインすると、カード・記号・デッキ・戦績・チュートリアル進捗をデータベースから復元できます。",
    ):
        if username:
            player = ensure_player_state(app.storage.user)
            selected_symbol = SYMBOL_INDEX.get(
                str(player["profile"].get("selected_symbol", ""))
            )
            avatar = selected_symbol.token if selected_symbol else str(
                player["profile"]["display_name"]
            )[:2].upper()

            with ui.element("section").classes("account-hero"):
                ui.label(avatar).classes("account-avatar")
                with ui.column().classes("gap-1 flex-1"):
                    chip("ログイン済み", "green")
                    ui.label(str(player["profile"]["display_name"])).classes("text-2xl font-bold")
                    ui.label(f"@{username}・{account_backend_label()}").classes("section-subtitle")
                    if selected_symbol:
                        ui.label(f"アカウントアイコン：{selected_symbol.name}").classes("blue-text text-sm")
                secondary_button("ログアウト", icon="logout", on_click=lambda: (log_out_account(), go("/")))

            sync_error = app.storage.user.get(ACCOUNT_SYNC_ERROR_STORAGE_KEY)
            if sync_error:
                with ui.element("div").classes("beginner-callout beginner-callout--yellow"):
                    ui.label("データベースへの保存を再試行します").classes("font-bold")
                    ui.label(str(sync_error)).classes("text-sm")

            def save_account_name() -> None:
                value = str(display_name_input.value or "")
                try:
                    account = get_default_account_store().update_display_name(username, value)
                    state = update_state_profile(
                        ensure_player_state(app.storage.user),
                        display_name=account.display_name,
                    )
                    store_player_state(app.storage.user, state)
                except (AccountStoreError, ValueError) as error:
                    ui.notify(str(error), type="negative")
                    return
                ui.notify("表示名を保存しました。", type="positive")
                go("/account")

            def choose_account_icon(symbol_id: str) -> None:
                try:
                    state = update_state_selected_symbol(
                        ensure_player_state(app.storage.user), symbol_id
                    )
                    store_player_state(app.storage.user, state)
                except ValueError as error:
                    ui.notify(str(error), type="warning")
                    return
                ui.notify("アカウントアイコンを変更しました。", type="positive")
                go("/account")

            with ui.element("div").classes("content-grid"):
                with ui.card().classes("panel"):
                    section_heading("表示名", "対戦相手やフレンド部屋に表示されます。")
                    display_name_input = ui.input(
                        "表示名", value=str(player["profile"]["display_name"])
                    ).props("outlined maxlength=20").classes("filter-control w-full mt-3")
                    primary_button("表示名を保存", icon="save", on_click=save_account_name).classes("mt-3")

                with ui.card().classes("panel"):
                    section_heading(
                        "アカウントアイコン",
                        "コレクションで獲得した記号だけを選べます。ヘッダーと対戦部屋へ共通反映します。",
                    )
                    unlocked = set(player["collection"]["unlocked_symbols"])
                    with ui.element("div").classes("account-icon-grid mt-3"):
                        for symbol in SYMBOL_CATALOG:
                            if symbol.id not in unlocked:
                                continue
                            is_selected = (
                                selected_symbol is not None
                                and symbol.id == selected_symbol.id
                            )
                            active_class = " account-icon-option--active" if is_selected else ""
                            with ui.button(
                                on_click=lambda sid=symbol.id: choose_account_icon(sid)
                            ).props(
                                f'flat no-caps aria-label="{symbol.name}をアイコンに設定"'
                            ).classes(
                                f"account-icon-option{active_class}"
                            ):
                                ui.label(symbol.token).classes("account-icon-option__token")
                                ui.label(symbol.name).classes("account-icon-option__name")
            return

        login_state = {"busy": False}

        def login() -> None:
            if login_state["busy"]:
                return
            login_state["busy"] = True
            try:
                account = get_default_account_store().authenticate(
                    str(login_username.value or ""), str(login_password.value or "")
                )
                establish_account_session(account.username)
            except AuthenticationError:
                ui.notify("ユーザー名またはパスワードが違います。", type="negative")
                return
            except AccountStoreError:
                ui.notify(
                    "保存先に接続できません。しばらく待ってからもう一度お試しください。",
                    type="negative",
                )
                return
            finally:
                login_state["busy"] = False
            ui.notify("ログインしました。保存データを復元しました。", type="positive")
            go("/")

        def register() -> None:
            if login_state["busy"]:
                return
            if str(register_password.value or "") != str(register_confirm.value or ""):
                ui.notify("確認用パスワードが一致しません。", type="warning")
                return
            login_state["busy"] = True
            registered_username: str | None = None
            try:
                guest_state = update_state_profile(
                    ensure_player_state(app.storage.user),
                    display_name=str(register_display_name.value or ""),
                )
                account = get_default_account_store().register(
                    str(register_username.value or ""),
                    str(register_password.value or ""),
                    str(register_display_name.value or ""),
                    guest_state,
                )
                registered_username = account.username
                token = get_default_account_store().create_session(account.username)
                app.storage.user[ACCOUNT_USERNAME_STORAGE_KEY] = account.username
                app.storage.user[ACCOUNT_SESSION_STORAGE_KEY] = token
                store_player_state(app.storage.user, guest_state)
            except DuplicateUsernameError:
                ui.notify("そのユーザー名はすでに使われています。", type="warning")
                return
            except (AccountValidationError, ValueError) as error:
                ui.notify(str(error), type="negative")
                return
            except AccountStoreError:
                if registered_username:
                    ui.notify(
                        "アカウントは作成済みです。ログイン欄からログインしてください。",
                        type="warning",
                    )
                else:
                    ui.notify(
                        "アカウントを保存できませんでした。保存先の設定を確認してから、もう一度お試しください。",
                        type="negative",
                    )
                return
            finally:
                login_state["busy"] = False
            ui.notify("アカウントを作成し、現在の進行状況を保存しました。", type="positive")
            go("/account")

        backend = account_backend_label()
        with ui.element("div").classes("beginner-callout"):
            with ui.row().classes("items-center gap-3 no-wrap"):
                ui.icon("cloud_done", size="26px")
                with ui.column().classes("gap-0"):
                    ui.label(f"現在の保存先：{backend}").classes("font-bold")
                    ui.label("同じユーザー名でログインすれば、別の端末でも進行状況を読み込めます。").classes("text-sm")

        with ui.element("div").classes("account-auth-grid"):
            with ui.card().classes("panel account-auth-card"):
                section_heading("ログイン", "すでに作成したアカウントを使います。")
                login_username = ui.input("ユーザー名").props(
                    "outlined autocomplete=username maxlength=24"
                ).classes("filter-control w-full mt-3")
                login_password = ui.input(
                    "パスワード", password=True, password_toggle_button=True
                ).props("outlined autocomplete=current-password maxlength=256").classes("filter-control w-full")
                primary_button("ログインして復元", icon="login", on_click=login)

            with ui.card().classes("panel account-auth-card"):
                section_heading("新規登録", "今のゲスト進行状況をそのまま保存します。")
                register_username = ui.input("ユーザー名（2〜24文字・日本語OK）").props(
                    "outlined autocomplete=username maxlength=24"
                ).classes("filter-control w-full mt-3")
                ui.label(
                    "日本語・英数字と . _ - が使えます（空白は使えません）。"
                ).classes("text-xs text-slate-400 -mt-2 mb-1")
                register_display_name = ui.input(
                    "表示名", value=str(ensure_player_state(app.storage.user)["profile"]["display_name"])
                ).props("outlined maxlength=20").classes("filter-control w-full")
                register_password = ui.input(
                    "パスワード（8文字以上）", password=True, password_toggle_button=True
                ).props("outlined autocomplete=new-password maxlength=256").classes("filter-control w-full")
                register_confirm = ui.input(
                    "パスワードをもう一度", password=True, password_toggle_button=True
                ).props("outlined autocomplete=new-password maxlength=256").classes("filter-control w-full")
                primary_button("アカウントを作成", icon="person_add", on_click=register)


@ui.page("/profile")
def profile_page() -> None:
    with page_shell(
        "/profile", "PLAYER RECORD", "プロフィール / プレイ記録",
        "勝率だけが上達の目安ではありません。索敵や補給など、自分の得意な役割も確認できます。",
    ):
        player = ensure_player_state(app.storage.user)
        stats = player["stats"]
        history = player["battle_history"]
        battles = int(stats["battles_played"])
        wins = int(stats["wins"])
        win_rate = round(wins / battles * 100) if battles else 0
        rank_label = ("CADET I", "CADET II", "CADET III", "OFFICER I", "OFFICER II")[
            min(4, wins // 3)
        ]
        played_cards = [card_id for entry in history for card_id in entry.get("deck", [])]
        fallback_card = player["deck"][0] if player["deck"] else STARTER_DECK[0]
        favorite_id = max(set(played_cards), key=played_cards.count) if played_cards else fallback_card

        def save_profile() -> None:
            try:
                updated = update_state_profile(
                    ensure_player_state(app.storage.user),
                    display_name=str(name_input.value or ""),
                    tagline=str(tagline_input.value or ""),
                )
            except ValueError as error:
                ui.notify(str(error), type="negative")
                return
            store_player_state(app.storage.user, updated)
            profile_dialog.close()
            ui.notify("プロフィールを保存しました。", type="positive")
            go("/profile")

        with ui.dialog() as profile_dialog, ui.card().classes("dialog-card"):
            ui.label("プロフィールを編集").classes("text-xl font-bold")
            name_input = ui.input(
                "表示名", value=str(player["profile"]["display_name"])
            ).props("outlined maxlength=20").classes("w-full")
            tagline_input = ui.input(
                "ひとこと", value=str(player["profile"]["tagline"])
            ).props("outlined maxlength=60").classes("w-full")
            with ui.row().classes("gap-2 mt-3"):
                primary_button("保存", icon="save", on_click=save_profile)
                secondary_button("キャンセル", icon="close", on_click=profile_dialog.close)

        with ui.element("div").classes("profile-hero"):
            selected_symbol = SYMBOL_INDEX.get(str(player["profile"].get("selected_symbol", "")))
            avatar_text = selected_symbol.token if selected_symbol else str(player["profile"]["display_name"])[:2].upper()
            ui.label(avatar_text).classes("avatar-command")
            with ui.column().classes("gap-1"):
                with ui.row().classes("items-center gap-2"):
                    ui.label(str(player["profile"]["display_name"])).classes("text-2xl font-bold")
                    chip(rank_label, "green")
                support_label = "初心者モード使用中" if player["preferences"]["beginner_mode"] else "標準表示"
                ui.label(f"{battles}戦プレイ・{support_label}").classes("section-subtitle")
                ui.label(f"ひとこと：{player['profile']['tagline'] or '未設定'}").classes("text-sm")
                if selected_symbol:
                    ui.label(f"アカウントアイコン：{selected_symbol.name}").classes("muted text-xs")
                ui.label("オンライン対戦では表示名とアカウントアイコンを相手に共有します。").classes("muted text-xs")
            secondary_button("プロフィールを編集", icon="edit", on_click=profile_dialog.open)

        with ui.element("div").classes("metric-grid"):
            metric_card("対戦", f"{battles} 戦", f"{wins}勝・{stats['losses']}敗・{stats['draws']}分")
            metric_card("勝率", f"{win_rate}%", "勝敗は演習を含めて記録", "green-text")
            metric_card("獲得任務点", str(stats["mission_points_earned"]), "3つの戦線で獲得")
            metric_card("収集", f"{len(player['collection']['owned_cards'])} 枚", f"記号 {len(player['collection']['unlocked_symbols'])} 種", "yellow-text")

        with ui.element("div").classes("content-grid"):
            with ui.card().classes("panel"):
                section_heading("最近の対戦", "勝敗、使用した編制、最終結果を保存しています。")
                if not history:
                    ui.label("まだ対戦記録がありません。演習を最後まで遊ぶとここに残ります。").classes("section-subtitle mt-3")
                result_labels = {"win": ("勝利", "green"), "loss": ("敗北", "red"), "draw": ("引き分け", "yellow")}
                for entry in history[:5]:
                    result, color = result_labels.get(entry["result"], ("結果", ""))
                    detail = entry.get("summary") or f"任務点 {entry['mission_points_for']} - {entry['mission_points_against']}"
                    deck = f"{len(entry.get('deck', []))}枚 / {get_formation(entry.get('formation')).name}編制"
                    time = str(entry.get("played_at", ""))[:16].replace("T", " ")
                    with ui.element("div").classes("history-row"):
                        with ui.row().classes("w-full items-center justify-between gap-3"):
                            with ui.row().classes("items-center gap-3"):
                                chip(result, color)
                                with ui.column().classes("gap-0"):
                                    ui.label(detail).classes("font-bold text-sm")
                                    ui.label(f"使用デッキ：{deck}").classes("muted text-xs")
                            with ui.row().classes("items-center gap-2"):
                                ui.label(time).classes("muted text-xs")
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("お気に入りカード")
                    favorite = get_card(favorite_id)
                    favorite_uses = played_cards.count(favorite_id)
                    with ui.row().classes("items-center gap-4 mt-3"):
                        unit_symbol(favorite)
                        with ui.column().classes("gap-0"):
                            ui.label(favorite.name).classes("font-bold")
                            ui.label(f"完了した対戦で使用 {favorite_uses}回").classes("section-subtitle")
                            chip(f"熟練度 {min(10, favorite_uses)} / 10", "yellow")
                    ui.linear_progress(value=min(1, favorite_uses / 10)).props("rounded size=8px").classes("progress-track mt-4")
                with ui.card().classes("panel"):
                    section_heading("獲得した実績")
                    achievements: list[tuple[str, str]] = []
                    if battles >= 1:
                        achievements.append(("flag", "初陣"))
                    if wins >= 1:
                        achievements.append(("shield", "初勝利"))
                    if any(entry.get("formation") == "division" for entry in history):
                        achievements.append(("account_tree", "師団運用"))
                    if len(player["collection"]["unlocked_symbols"]) == len(SYMBOL_CATALOG):
                        achievements.append(("verified", "全記号収集"))
                    if not achievements:
                        ui.label("対戦を完了すると、ここに実績が増えます。").classes("section-subtitle mt-3")
                    with ui.row().classes("gap-3 mt-3"):
                        for icon, label in achievements:
                            with ui.column().classes("items-center gap-1"):
                                with ui.element("div").classes("role-icon").style("--role-color:#60afff"):
                                    ui.icon(icon)
                                ui.label(label).classes("muted text-xs")


def setting_switch(key: str, title: str, description: str) -> None:
    preferences = get_preferences()

    def changed(event) -> None:
        set_preference(key, bool(event.value))
        ui.notify(f"{title}を{'オン' if event.value else 'オフ'}にしました。", type="positive")

    with ui.row().classes("setting-row items-center no-wrap gap-4"):
        with ui.column().classes("gap-0 flex-1"):
            ui.label(title).classes("font-bold text-sm")
            ui.label(description).classes("section-subtitle")
        ui.switch(value=bool(preferences[key]), on_change=changed)


@ui.page("/settings")
def settings_page() -> None:
    with page_shell(
        "/settings", "PREFERENCES", "設定",
        "説明の量や表示方法を、自分が遊びやすい状態に調整できます。",
    ):
        settings_player = ensure_player_state(app.storage.user)
        preferences = dict(settings_player["preferences"])

        def set_choice(key: str, value: str, label: str) -> None:
            set_preference(key, value)
            ui.notify(f"{label}を変更しました。", type="positive")

        font_labels = {"standard": "標準", "large": "大きめ", "maximum": "最大"}
        font_values = {label: key for key, label in font_labels.items()}
        with ui.element("div").classes("content-grid"):
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("初心者サポート", "最初はすべてオンがおすすめです。")
                    if settings_player["progression"]["simulation_unlocked"]:
                        with ui.element("div").classes("beginner-callout beginner-callout--yellow"):
                            ui.label("基本18枚を集めたため、初心者モードを修了しました").classes("font-bold")
                            ui.label(
                                "おすすめ行動や用語説明は個別に残せます。18枚ルールもカジュアルモードで遊べます。"
                            ).classes("text-sm")
                    else:
                        setting_switch("beginner_mode", "初心者モード", "カードの役割とおすすめ行動を常に表示します。")
                    setting_switch("explain_military_terms", "軍事用語の説明", "専門用語の横に、普段の言葉で意味を表示します。")
                    setting_switch("recommended_actions", "おすすめ行動", "選べる行動に迷ったとき、候補を1つ表示します。")
                    setting_switch("slow_resolution", "結果を項目別に表示", "命令公開・索敵・補給・戦線判定を番号付きで表示します。")
                    secondary_button("チュートリアルをもう一度見る", "/tutorials", "school").classes("mt-3")
                with ui.card().classes("panel"):
                    section_heading("対戦")
                    setting_switch("confirm_orders", "命令確定前に確認する", "誤操作を防ぐため、確定内容を文章で表示します。")
                    setting_switch("auto_logs", "戦闘ログを自動表示", "各ラウンドで起きたことを自動で開きます。")
            with ui.column().classes("w-full gap-4"):
                with ui.card().classes("panel"):
                    section_heading("表示とアクセシビリティ")
                    ui.select(
                        list(font_values), value=font_labels[str(preferences["font_size"])], label="文字サイズ",
                        on_change=lambda e: set_choice("font_size", font_values[str(e.value)], "文字サイズ"),
                    ).props("outlined").classes("filter-control w-full mt-3")
                    setting_switch("high_contrast", "高コントラスト", "境界線と文字の差をさらに大きくします。")
                    setting_switch("reduce_motion", "アニメーションを減らす", "カード公開などの動きを短くします。")
                    setting_switch("large_symbols", "カード記号を大きくする", "カードの中央にある兵科記号を拡大します。")


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
