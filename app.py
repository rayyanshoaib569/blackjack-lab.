from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import streamlit as st

import blackjack_engine as bj


APP_TITLE = "Blackjack Lab"
STORE_KEY = "blackjack-lab.session.v1"
EMPTY_SENTINEL = "__BLACKJACK_LAB_EMPTY__"
DEFAULT_STARTING_BALANCE = 2500


def default_rules() -> dict[str, Any]:
    return {
        "name": "Classic six-deck · S17",
        "decks": 6,
        "blackjack_payout": "3:2",
        "dealer_soft_17": "Stand soft 17",
        "double_rule": "Any first two cards",
        "double_after_split": True,
        "splitting": True,
        "split_match": "Exact rank",
        "max_split_hands": 4,
        "split_aces_one_card": True,
        "resplit_aces": False,
        "surrender": True,
        "insurance": True,
        "dealer_mode": bj.HOLE_PEEK,
        "reshuffle_mode": "Penetration auto",
        "penetration": 0.75,
    }


PRESETS: dict[str, dict[str, Any]] = {
    "Classic six-deck · S17": {
        **default_rules(),
        "name": "Classic six-deck · S17",
    },
    "Atlantic City · 8 decks": {
        **default_rules(),
        "name": "Atlantic City · 8 decks",
        "decks": 8,
        "surrender": True,
        "dealer_mode": bj.HOLE_PEEK,
        "penetration": 0.75,
    },
    "Vegas · H17": {
        **default_rules(),
        "name": "Vegas · H17",
        "dealer_soft_17": "Hit soft 17",
        "surrender": False,
    },
    "Single-deck · 3:2": {
        **default_rules(),
        "name": "Single-deck · 3:2",
        "decks": 1,
        "double_rule": "Hard 9–11 only",
        "double_after_split": False,
        "penetration": 0.70,
    },
    "European · no hole card": {
        **default_rules(),
        "name": "European · no hole card",
        "dealer_soft_17": "Hit soft 17",
        "dealer_mode": bj.NO_HOLE,
        "surrender": False,
    },
}

RULE_FORM_KEYS = [
    "decks",
    "blackjack_payout",
    "dealer_soft_17",
    "double_rule",
    "double_after_split",
    "splitting",
    "split_match",
    "max_split_hands",
    "split_aces_one_card",
    "resplit_aces",
    "surrender",
    "insurance",
    "dealer_mode",
    "reshuffle_mode",
    "penetration",
]


def rule_widget_key(rule_key: str) -> str:
    return "rule_penetration_pct" if rule_key == "penetration" else f"rule_{rule_key}"


def make_game_data() -> dict[str, Any]:
    rules = default_rules()
    return {
        "version": 1,
        "starting_balance": DEFAULT_STARTING_BALANCE,
        "balance": DEFAULT_STARTING_BALANCE,
        "rules": deepcopy(rules),
        "draft_rules": deepcopy(rules),
        "shoe": bj.new_shoe(rules),
        "round": None,
        "history": [],
    }


@st.cache_resource
def local_storage_bridge():
    return st.components.v2.component(
        name="blackjack_lab_local_storage",
        html='<span id="storage-bridge" aria-hidden="true"></span>',
        css="#storage-bridge { display: none; }",
        js=f"""
        export default function({{ data, setStateValue }}) {{
          const storeKey = {json.dumps(STORE_KEY)};
          try {{
            if (!data || data.ready !== true) {{
              const saved = window.localStorage.getItem(storeKey);
              setStateValue("loaded", saved === null ? {json.dumps(EMPTY_SENTINEL)} : saved);
              setStateValue("storage_error", null);
              return;
            }}
            if (data.clear === true) {{
              window.localStorage.removeItem(storeKey);
              setStateValue("storage_error", null);
              return;
            }}
            const encoded = JSON.stringify(data.payload);
            if (window.localStorage.getItem(storeKey) !== encoded) {{
              window.localStorage.setItem(storeKey, encoded);
            }}
            setStateValue("storage_error", null);
          }} catch (error) {{
            setStateValue("storage_error", String(error && error.message ? error.message : error));
          }}
        }}
        """,
    )


def mount_storage_bridge(*, ready: bool, payload: dict[str, Any] | None = None, clear: bool = False) -> None:
    bridge = local_storage_bridge()
    bridge(
        data={"ready": ready, "payload": payload, "clear": clear},
        default={"loaded": None, "storage_error": None},
        on_loaded_change=lambda: None,
        on_storage_error_change=lambda: None,
        key="blackjack_browser_storage",
        width="content",
        height=1,
    )


def component_value(name: str, default=None):
    result = st.session_state.get("blackjack_browser_storage")
    if result is None:
        return default
    try:
        return getattr(result, name, default)
    except Exception:
        return default


def hydrate_game() -> bool:
    if st.session_state.get("_game_hydrated"):
        return True
    loaded = component_value("loaded")
    if loaded is None:
        return False
    if loaded == EMPTY_SENTINEL:
        data = make_game_data()
    else:
        try:
            data = json.loads(loaded)
            if not isinstance(data, dict) or data.get("version") != 1 or "shoe" not in data:
                raise ValueError("Unsupported saved session format")
        except (json.JSONDecodeError, TypeError, ValueError):
            data = make_game_data()
            st.session_state["_storage_warning"] = "The saved browser session could not be read, so a fresh shoe was started."
    # Upgrade sessions saved by earlier versions without discarding their shoe or history.
    history = data.setdefault("history", [])
    if "starting_balance" not in data or "balance" not in data:
        data.setdefault("starting_balance", DEFAULT_STARTING_BALANCE)
        recorded_net = sum(float(hand.get("total_net", 0.0)) for hand in history)
        data.setdefault("balance", float(data["starting_balance"]) + recorded_net)
    st.session_state.setdefault("starting_balance_input", int(data["starting_balance"]))
    st.session_state["game_data"] = data
    st.session_state["_game_hydrated"] = True
    return True


def get_game() -> dict[str, Any]:
    if "game_data" not in st.session_state:
        st.session_state.game_data = make_game_data()
    return st.session_state.game_data


def style_app() -> None:
    st.markdown(
        """
        <style>
        @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Playfair+Display:wght@600;700&display=swap');
        :root { --felt: #14513f; --felt-deep: #0b342a; --gold: #d8b56d; --gold-light: #f0dba7; --ink: #14211f; --muted: #71807b; }
        .stApp { background: radial-gradient(ellipse at 48% -12%, #203e36 0, #111a19 43%, #0c1112 100%); color: #eef2ee; }
        .block-container { max-width: 1280px; padding-top: 1.4rem; padding-bottom: 3rem; }
        [data-testid="stSidebar"] { background: #101817; border-right: 1px solid rgba(216,181,109,.12); }
        [data-testid="stSidebar"] * { color: #d9e0dc; }
        h1, h2, h3 { letter-spacing: -.025em; }
        h1, h2 { font-family: 'Playfair Display', Georgia, serif !important; }
        h1 { color: #f2e3bf; }
        h3 { color: #e8d8ae; }
        p, label, .stMarkdown, [data-testid="stMetricLabel"] { font-family: 'DM Sans', sans-serif; }
        .hero { display:flex; align-items:center; justify-content:space-between; gap:1rem; padding:.25rem 0 1.05rem; border-bottom:1px solid rgba(216,181,109,.2); margin-bottom:1.15rem; }
        .brand { color:#d8b56d; font:600 .78rem 'DM Mono', monospace; letter-spacing:.18em; text-transform:uppercase; }
        .hero-note { color:#a2b2ab; font-size:.9rem; }
        .eyebrow { color:#d8b56d; text-transform:uppercase; letter-spacing:.14em; font:500 .72rem 'DM Mono', monospace; }
        .felt-table { background: radial-gradient(ellipse at 50% 35%, #1b6a50, #104835 62%, #0a362a); border:1px solid rgba(234,204,137,.48); box-shadow: inset 0 0 0 9px rgba(7,31,25,.17), inset 0 0 50px rgba(4,24,19,.36), 0 18px 44px rgba(0,0,0,.28); border-radius: 48% / 15%; padding:1.7rem 2.2rem 2rem; min-height: 300px; margin:.5rem 0 1rem; position:relative; overflow:hidden; }
        .felt-table:after { content:'BLACKJACK  ·  21'; display:block; text-align:center; color:rgba(231,204,143,.25); font:500 .66rem 'DM Mono',monospace; letter-spacing:.28em; margin-top:1.4rem; }
        .table-label { color:#d7e8dc; text-transform:uppercase; letter-spacing:.14em; font:500 .65rem 'DM Mono',monospace; margin:.15rem 0 .55rem; }
        .cards { display:flex; gap:.5rem; min-height:92px; flex-wrap:wrap; align-items:center; }
        .playing-card { display:flex; flex-direction:column; align-items:flex-start; justify-content:space-between; width:58px; height:82px; padding:.38rem .42rem; box-sizing:border-box; border-radius:8px; background:linear-gradient(145deg,#fffefa,#ece9dc); color:#202a27; box-shadow:0 5px 12px rgba(0,0,0,.24); font:600 1.08rem 'DM Sans',sans-serif; animation:deal-in .26s ease-out both; }
        .playing-card .suit { font-size:1.05rem; line-height:1; }
        .playing-card.red { color:#bd3e39; }
        .playing-card.back { align-items:center; justify-content:center; background:repeating-linear-gradient(45deg,#233c50,#233c50 5px,#314f62 5px,#314f62 10px); border:2px solid #f2e3bf; color:#f2e3bf; font:500 .72rem 'DM Mono',monospace; }
        @keyframes deal-in { from { opacity:0; transform:translateY(-12px) rotate(-3deg) scale(.96); } to { opacity:1; transform:translateY(0) rotate(0) scale(1); } }
        .hand-status { margin-left:.25rem; color:#bbd6c3; font:.72rem 'DM Mono',monospace; }
        .active-hand { outline:1px solid rgba(240,219,167,.65); outline-offset:8px; border-radius:10px; }
        .decision-card { background:linear-gradient(135deg,rgba(31,46,42,.92),rgba(18,27,26,.92)); border:1px solid rgba(216,181,109,.2); border-radius:14px; padding:1rem 1.05rem; min-height:104px; }
        .decision-card.recommended { border-color:rgba(216,181,109,.82); box-shadow:0 0 0 1px rgba(216,181,109,.13),0 8px 24px rgba(0,0,0,.15); }
        .decision-action { color:#d7e4dc; text-transform:uppercase; letter-spacing:.11em; font:500 .7rem 'DM Mono',monospace; }
        .decision-ev { font:600 1.45rem 'DM Mono',monospace; color:#f1e2bb; margin:.55rem 0 .1rem; }
        .decision-se { color:#9ead a6; color:#9eada6; font-size:.72rem; }
        .recommendation { padding:.85rem 1rem; background:rgba(216,181,109,.11); border-left:3px solid var(--gold); border-radius:0 9px 9px 0; color:#f3e6c7; }
        .bar-row { display:grid; grid-template-columns:75px 1fr 42px; gap:.55rem; align-items:center; margin:.36rem 0; color:#c6d1ca; font-size:.78rem; }
        .bar-track { height:7px; background:#28312e; border-radius:9px; overflow:hidden; }
        .bar-fill { height:100%; background:linear-gradient(90deg,#c39e52,#ebd394); border-radius:9px; }
        .subtle { color:#9eada6; font-size:.82rem; }
        .mono { font-family:'DM Mono',monospace; }
        .result-pill { display:inline-flex; padding:.25rem .52rem; border-radius:999px; background:rgba(216,181,109,.14); color:#eddbaf; font:.68rem 'DM Mono',monospace; text-transform:uppercase; letter-spacing:.06em; }
        .history-meta { color:#a5b2ac; font-size:.8rem; }
        .rank-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(52px,1fr)); gap:.4rem; margin:.5rem 0; }
        .rank-cell { display:flex; justify-content:space-between; gap:.25rem; padding:.45rem .5rem; border-radius:8px; border:1px solid rgba(216,181,109,.13); background:rgba(27,38,35,.62); color:#e7dfcb; font:.78rem 'DM Mono',monospace; }
        .table-seats { display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.35fr); gap:1.35rem; align-items:stretch; }
        .table-seat { min-width:0; padding:1rem; border:1px solid rgba(231,215,171,.22); border-radius:16px; background:rgba(7,34,27,.3); }
        .table-seat.player-seat { background:rgba(7,34,27,.47); }
        .seat-heading { display:flex; justify-content:space-between; align-items:flex-start; gap:.5rem; min-height:2.25rem; }
        .seat-total { color:#f1e2bb; font:600 1.05rem 'DM Mono',monospace; }
        .player-hand { margin:.6rem 0 .9rem; padding:.45rem .55rem .65rem; border:1px solid transparent; border-radius:12px; }
        .player-hand.is-active { border-color:rgba(240,219,167,.75); background:rgba(240,219,167,.07); box-shadow:0 0 20px rgba(240,219,167,.08); }
        .st-key-table_controls { padding:1rem 1.1rem; border:1px solid rgba(216,181,109,.3); border-radius:16px; background:linear-gradient(135deg,rgba(30,45,39,.96),rgba(17,27,25,.96)); margin:.75rem 0 1rem; }
        .st-key-table_controls .stButton button { min-height:2.8rem; font-weight:700; }
        .st-key-table_controls .stButton button[kind="primary"] { box-shadow:0 4px 14px rgba(216,181,109,.16); }
        .st-key-table_controls .stButton button:disabled { opacity:.38; }
        .stButton button { border:1px solid rgba(216,181,109,.4); border-radius:10px; transition:transform .14s ease,background .14s ease,border-color .14s ease; }
        .stButton button:hover { transform:translateY(-1px); border-color:#d8b56d; background:rgba(216,181,109,.1); }
        .stButton button[kind="primary"] { background:linear-gradient(135deg,#d8b56d,#b48b3f); color:#18211d; border:0; font-weight:700; }
        [data-testid="stMetric"] { background:rgba(27,38,35,.75); border:1px solid rgba(216,181,109,.13); padding:.7rem .8rem; border-radius:12px; }
        [data-testid="stMetricValue"] { color:#f0dfb5; font-family:'DM Mono',monospace; }
        div[data-baseweb="tab-list"] { gap:.4rem; border-bottom:1px solid rgba(216,181,109,.14); }
        button[data-baseweb="tab"] { color:#acb9b2; }
        button[data-baseweb="tab"][aria-selected="true"] { color:#f0dfb5; }
        [data-testid="stExpander"] { border:1px solid rgba(216,181,109,.16); border-radius:12px; background:rgba(18,27,26,.55); }
        @media(max-width:700px) { .felt-table { border-radius:28px; padding:1.2rem 1rem; min-height:260px; } .table-seats { grid-template-columns:1fr; gap:.65rem; } .table-seat { padding:.8rem; } .playing-card { width:50px;height:72px; } .hero { align-items:flex-start; flex-direction:column; } .decision-card { min-height:92px; padding:.75rem; } .decision-ev { font-size:1.14rem; } }
        </style>
        """,
        unsafe_allow_html=True,
    )


def card_html(card: str, index: int) -> str:
    suits = ["♠", "♥", "♦", "♣"]
    suit = suits[(bj.RANK_INDEX[card] + index) % len(suits)]
    color_class = "red" if suit in {"♥", "♦"} else ""
    return f'<div class="playing-card {color_class}"><span>{card}</span><span class="suit">{suit}</span></div>'


def cards_html(cards: list[str], hidden: bool = False, hidden_count: int = 0) -> str:
    visible = "".join(card_html(card, index) for index, card in enumerate(cards))
    if hidden:
        visible += '<div class="playing-card back"><span>21</span><span>?</span></div>'
    for _ in range(hidden_count):
        visible += '<div class="playing-card back"><span>DEAL</span><span>?</span></div>'
    return f'<div class="cards">{visible}</div>'


def show_shoe_composition(game: dict[str, Any], round_state: dict[str, Any] | None) -> None:
    shoe = game["shoe"]
    with st.expander("Shoe composition by rank"):
        if round_state and round_state.get("phase") != "complete":
            composition = bj.unseen_counts(shoe, round_state)
            st.caption("Analytical unseen pool. It includes the face-down dealer card when one is in play; the card remains unknown. A negative peek is also applied as a condition in the probability model.")
        else:
            composition = list(shoe["cards"])
            st.caption("Physical cards left to draw. The completed hand's cards, including the revealed dealer cards, have been removed.")
        total_unseen = sum(composition)
        grid = "".join(
            f'<div class="rank-cell"><b>{rank}</b><span>{count}</span></div>'
            for rank, count in zip(bj.RANKS, composition)
        )
        st.markdown(f'<div class="rank-grid">{grid}</div>', unsafe_allow_html=True)
        st.caption(f"{total_unseen} cards in this composition snapshot.")


def show_table(game: dict[str, Any]) -> None:
    round_state = game.get("round")
    shoe = game["shoe"]
    remaining = sum(shoe["cards"])
    shoe_fraction = remaining / max(1, shoe["initial_total"])
    active_round = bool(round_state and round_state.get("phase") != "complete")
    wager_now = sum(float(hand.get("wager", 0.0)) for hand in round_state.get("hands", [])) if active_round else 0.0
    insurance_now = float(round_state.get("initial_wager", 0.0)) * 0.5 if active_round and round_state.get("insurance_taken") else 0.0
    st.markdown(
        f'<div class="eyebrow">Solo table · Shoe {shoe["id"]} · {game["rules"]["name"]}</div>',
        unsafe_allow_html=True,
    )
    balance_cols = st.columns(4)
    balance_cols[0].metric("Balance", f'{float(game.get("balance", DEFAULT_STARTING_BALANCE)):,.0f} credits')
    balance_cols[1].metric("Available", f'{bj.available_balance(game):,.0f} credits')
    wager_label = f"{wager_now:,.0f}" + (f" + {insurance_now:,.0f} insurance" if insurance_now else "")
    balance_cols[2].metric("Wager", f"{wager_label} credits" if active_round else "Set below")
    balance_cols[3].metric("Cards left", f"{remaining} / {shoe['initial_total']}")

    if not round_state:
        st.markdown(
            '<div class="felt-table"><div class="table-seats"><section class="table-seat dealer-seat"><div class="seat-heading"><div><div class="table-label">Dealer</div><div class="subtle">Waiting for the deal</div></div><span class="seat-total">—</span></div><div class="cards"><div class="playing-card back"><span>21</span><span>?</span></div></div></section><section class="table-seat player-seat"><div class="seat-heading"><div><div class="table-label">Your seat</div><div class="subtle">Set a wager, then deal</div></div><span class="seat-total">—</span></div><div class="cards"><div class="playing-card back"><span>DEAL</span><span>?</span></div><div class="playing-card back"><span>DEAL</span><span>?</span></div></div></section></div></div>',
            unsafe_allow_html=True,
        )
    else:
        dealer_cards = round_state.get("dealer_cards", [round_state["dealer_up"]])
        show_hidden = round_state["phase"] != "complete" and round_state.get("dealer_hole") is not None and not round_state.get("hole_revealed")
        european_placeholder = round_state["rules"]["dealer_mode"] == bj.NO_HOLE and round_state["phase"] != "complete"
        if round_state.get("phase") == "complete":
            dealer_total, dealer_soft = bj.hand_value(dealer_cards)
            result = round_state.get("dealer_result", "")
            dealer_value = result.title() if result in {"bust", "blackjack"} else str(dealer_total) + (" soft" if dealer_soft else "")
            dealer_note = "Final hand"
        else:
            dealer_value = f"Up card {round_state['dealer_up']}"
            dealer_note = "Second card dealt after player hands" if european_placeholder else "Hole card hidden"
        dealer_html = cards_html(dealer_cards, hidden=show_hidden, hidden_count=1 if european_placeholder else 0)
        player_html = []
        for index, hand in enumerate(round_state["hands"]):
            current = round_state.get("phase") == "player" and index == round_state.get("current_hand")
            total, soft = bj.hand_value(hand["cards"])
            total_label = f"{total}" + (" · soft" if soft else "")
            status = "Your decision" if current else hand.get("status", "active").replace("_", " ")
            player_html.append(
                f'<div class="player-hand {"is-active" if current else ""}"><div class="table-label">Hand {index + 1} · {total_label} · wager {float(hand["wager"]):,.0f} credits <span class="hand-status">{status}</span></div>{cards_html(hand["cards"])}</div>'
            )
        st.markdown(
            f'<div class="felt-table"><div class="table-seats"><section class="table-seat dealer-seat"><div class="seat-heading"><div><div class="table-label">Dealer</div><div class="subtle">{dealer_note}</div></div><span class="seat-total">{dealer_value}</span></div>{dealer_html}</section><section class="table-seat player-seat"><div class="seat-heading"><div><div class="table-label">Your seat</div><div class="subtle">{len(round_state["hands"])} hand(s) · {round_state["phase"].replace("_", " ").title()}</div></div></div>{"".join(player_html)}</section></div></div>',
            unsafe_allow_html=True,
        )
    shoe_cols = st.columns(3)
    shoe_cols[0].metric("Shoe used", f"{(1-shoe_fraction)*100:.0f}%")
    shoe_cols[1].metric("Hands in shoe", shoe["rounds"])
    shoe_cols[2].metric("Dealer rule", game["rules"]["dealer_soft_17"].replace(" soft", ""))
    show_shoe_composition(game, round_state)


def _decision_cache_key(game: dict[str, Any], hand_index: int) -> str:
    round_state = game["round"]
    hand = round_state["hands"][hand_index]
    payload = {
        "cards": hand["cards"],
        "from_split": hand["from_split"],
        "split_aces": hand["split_aces"],
        "up": round_state["dealer_up"],
        "shoe": game["shoe"]["cards"],
        "hole": round_state.get("dealer_hole"),
        "peek": round_state.get("peek_no_blackjack"),
        "rules": round_state["rules"],
        "hand_count": len(round_state["hands"]),
        "index": hand_index,
        "available": bj.available_balance(game),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":"))


def get_analysis(game: dict[str, Any], hand_index: int) -> dict[str, Any]:
    cache = st.session_state.setdefault("_decision_cache", {})
    key = _decision_cache_key(game, hand_index)
    if key not in cache:
        cache[key] = bj.decision_analysis(
            game["round"], game["shoe"], hand_index, bj.available_balance(game)
        )
        while len(cache) > 8:
            cache.pop(next(iter(cache)))
    return cache[key]


def format_ev(value: float) -> str:
    return f"{value:+.3f}"


def show_dealer_outcomes(outcomes: dict[str, float]) -> None:
    labels = [("Bust", outcomes.get("bust", 0)), ("17", outcomes.get("17", 0)), ("18", outcomes.get("18", 0)), ("19", outcomes.get("19", 0)), ("20", outcomes.get("20", 0)), ("21", outcomes.get("21", 0)), ("Blackjack", outcomes.get("blackjack", 0))]
    html = []
    for label, probability in labels:
        html.append(
            f'<div class="bar-row"><span>{label}</span><div class="bar-track"><div class="bar-fill" style="width:{probability*100:.1f}%"></div></div><span class="mono">{probability*100:.1f}%</span></div>'
        )
    st.markdown("".join(html), unsafe_allow_html=True)


def show_hand_math(game: dict[str, Any], analysis: dict[str, Any], hand_index: int) -> None:
    round_state = game["round"]
    hand = round_state["hands"][hand_index]
    total, soft = bj.hand_value(hand["cards"])
    st.markdown(f'<div class="eyebrow">Decision {hand_index + 1} · {"soft " if soft else ""}{total} vs dealer {round_state["dealer_up"]}</div>', unsafe_allow_html=True)
    st.markdown("#### Live math")
    top = st.columns([1, 1.7])
    if analysis["bust_probability"] is not None:
        top[0].metric("Bust if you hit", f"{analysis['bust_probability']*100:.1f}%", help="Exact for the next card using the unseen finite shoe composition. It does not assume a fresh deck.")
    else:
        top[0].metric("Bust if you hit", "—")
    with top[1]:
        st.markdown(f'<div class="subtle">Dealer outcomes if you stand · Monte Carlo · {1800:,} samples</div>', unsafe_allow_html=True)
        show_dealer_outcomes(analysis["dealer_outcomes"])
    st.caption(f"EV = expected net return per 1 unit of this hand's wager. Sampled from {analysis['simulation_count']:,} finite-shoe rollouts; ± values are estimated standard errors.")

    actions = analysis["actions"]
    for row_start in range(0, len(actions), 3):
        row_actions = actions[row_start : row_start + 3]
        cols = st.columns(len(row_actions))
        for index, action in enumerate(row_actions):
            estimate = analysis["evs"][action]
            recommended = action == analysis["recommended"]
            cols[index].markdown(
                f'<div class="decision-card {"recommended" if recommended else ""}"><div class="decision-action">{action}{" · recommended" if recommended else ""}</div><div class="decision-ev">{format_ev(estimate["ev"])}</div><div class="decision-se">± {estimate["se"]:.3f} SE · per unit</div></div>',
                unsafe_allow_html=True,
            )

    recommended = analysis["recommended"]
    st.markdown(
        f'<div class="recommendation"><b>Current EV leader: {recommended.title()}</b> · {format_ev(analysis["evs"][recommended]["ev"])} units per unit wager in this estimate.</div>',
        unsafe_allow_html=True,
    )
    with st.expander("Why this recommendation?", expanded=False):
        st.markdown(
            f"The shoe has **{analysis['unseen_total']} unseen cards** in the calculation, including the dealer's hidden card when that rule applies. There are **{analysis['physical_remaining']} physical cards left to draw**. The hidden card is not revealed to this analysis; when a peek ruled out blackjack, the simulated hidden-card pool is conditioned on that fact."
        )
        if analysis["bust_probability"] is not None:
            st.markdown(f"- Immediate bust chance on a hit: **{analysis['bust_probability']*100:.2f}%** (exact next-card probability).")
        st.markdown("- Dealer outcome bars estimate the distribution if you stand now. They sample the finite shoe under the active hit/stand-soft-17 and hole-card rules; the player's future hit cards are not reserved for that separate display.")
        st.markdown("- EVs are net returns from the main hand only. They include the active payout, dealer behavior, double/split limits, and shoe composition.")
        st.markdown("- After the action being compared, each rollout continues with a disclosed rule-aware basic-strategy policy. The available practice balance limits later doubles and splits; if a continuation double or split cannot be funded, that rollout hits instead (one-card split aces stand). The highest estimated EV is the recommendation; it is not an exact globally optimal strategy solution.")
        st.markdown("- EV gaps smaller than roughly **2× the combined standard error** may be statistically unclear at this sample count.")
        ev_rows = []
        for action in actions:
            item = analysis["evs"][action]
            ev_rows.append(f"| {action.title()} | {item['ev']:+.4f} | ± {item['se']:.4f} | {item['samples']:,} |")
        st.markdown("| Action | EV / unit | SE | Samples |\n|---|---:|---:|---:|\n" + "\n".join(ev_rows))


def _draw_round_form(game: dict[str, Any]) -> None:
    round_state = game.get("round")
    if round_state and round_state["phase"] != "complete":
        return
    previous = round_state and round_state.get("phase") == "complete"
    if previous:
        st.markdown("### Place your next wager")
    history_started = bool(game.get("history")) or int(game["shoe"].get("rounds", 0)) > 0
    with st.container(key="table_controls"):
        st.markdown('<div class="eyebrow">Place wager · Deal</div>', unsafe_allow_html=True)
        balance = float(game.get("balance", DEFAULT_STARTING_BALANCE))
        st.session_state.setdefault("starting_balance_input", int(game.get("starting_balance", DEFAULT_STARTING_BALANCE)))
        if not history_started and balance == float(game.get("starting_balance", DEFAULT_STARTING_BALANCE)):
            starting_balance = st.select_slider(
                "Starting balance",
                options=list(range(1000, 10001, 500)),
                format_func=lambda amount: f"{amount:,} credits",
                key="starting_balance_input",
                help="Choose your practice bankroll before your first hand. These credits have no cash value.",
            )
            game["starting_balance"] = int(starting_balance)
            game["balance"] = float(starting_balance)
        else:
            st.select_slider(
                "Starting balance",
                options=list(range(1000, 10001, 500)),
                format_func=lambda amount: f"{amount:,} credits",
                key="starting_balance_input",
                disabled=True,
                help="The starting balance is fixed after the first hand so the saved session remains consistent.",
            )
        balance = float(game.get("balance", DEFAULT_STARTING_BALANCE))
        st.session_state.setdefault("wager_input", min(10.0, max(1.0, balance)))
        wager_key_value = float(st.session_state.get("wager_input", min(10.0, max(1.0, balance))))
        if wager_key_value > max(1.0, balance):
            st.session_state["wager_input"] = max(1.0, balance)
        st.number_input(
            "Wager (credits)",
            min_value=1.0,
            max_value=max(1.0, balance),
            step=1.0,
            key="wager_input",
            help="The main wager is reserved while the hand is in progress. Doubles, splits, and insurance need enough additional available credits.",
        )
        st.caption("Practice credits only; no real-money betting. Your current wager is limited by your balance.")
        if balance < 1:
            st.warning("Your practice balance is empty. Reload practice chips to start a fresh shoe; your hand history will stay saved.")
            if st.button("Reload practice chips · new shoe", type="primary", use_container_width=True, key="reload_practice_chips"):
                game["balance"] = float(game.get("starting_balance", DEFAULT_STARTING_BALANCE))
                game["shoe"] = bj.new_shoe(game["rules"])
                game["round"] = None
                st.rerun()
            return
        if st.button("Deal hand", type="primary", use_container_width=True, key="deal_hand"):
            wager = float(st.session_state["wager_input"])
            game["starting_balance"] = int(game.get("starting_balance", DEFAULT_STARTING_BALANCE))
            try:
                bj.deal_round(game, wager)
                bj.commit_round_to_history(game)
                st.rerun()
            except ValueError as error:
                st.error(str(error))


def _action_buttons(game: dict[str, Any], actions: list[str], key_prefix: str) -> str | None:
    selected = None
    labels = {"stand": "Stand", "hit": "Hit", "double": "Double", "split": "Split", "surrender": "Surrender"}
    with st.container(key="table_controls"):
        st.markdown('<div class="eyebrow">Your move · Legal actions</div>', unsafe_allow_html=True)
        for row_start in range(0, len(actions), 3):
            row_actions = actions[row_start : row_start + 3]
            button_cols = st.columns(len(row_actions))
            for index, action in enumerate(row_actions):
                if button_cols[index].button(
                    labels[action],
                    key=f"{key_prefix}_{action}",
                    type="primary",
                    use_container_width=True,
                ):
                    selected = action
    return selected


def _show_insurance_math(info: dict[str, Any]) -> None:
    probability = info["dealer_blackjack_probability"]
    ev = info["insurance_ev_per_main_wager"]
    st.markdown("### Insurance math")
    st.write(
        f"Dealer blackjack chance: **{probability*100:.2f}%** from {info['unseen_total']} unseen cards. "
        f"Take insurance EV: **{ev:+.3f}** · Decline insurance EV: **+0.000** units per unit of the main wager."
    )
    st.markdown(f'<div class="recommendation"><b>Recommended:</b> {info["recommended"].title()}</div>', unsafe_allow_html=True)
    if not info.get("take_available", True):
        st.info("There are not enough available credits to take insurance, so declining is the recommended legal choice.")
    with st.expander("Why this insurance recommendation?", expanded=False):
        st.markdown(
            "The hidden dealer card remains included among the unseen cards. Insurance wins +1 unit when the dealer has blackjack and loses 0.5 units otherwise, so its break-even probability is 33.33%."
        )
        st.markdown(
            f"EV = ({probability:.4f} × +1.0) + ({1-probability:.4f} × −0.5) = **{ev:+.4f} units**. "
            f"The current calculation recommends **{info['recommended']}**."
        )


def render_play(game: dict[str, Any]) -> None:
    current = game.get("round")
    show_table(game)
    if not current or current["phase"] == "complete":
        if current and current["phase"] == "complete":
            net = float(current.get("total_net", 0.0))
            tone = "positive" if net > 0 else "negative" if net < 0 else "neutral"
            st.markdown(f'<div class="recommendation">Hand complete · <b>{current.get("total_net", 0):+.2f} credits net</b> · Balance {float(game.get("balance", 0)):,.0f} credits · Dealer {current.get("dealer_result", "").title()} · <span class="result-pill">{tone}</span></div>', unsafe_allow_html=True)
        _draw_round_form(game)
        return

    if current["phase"] == "insurance":
        available = bj.available_balance(game)
        insurance_cost = float(current["initial_wager"]) * 0.5
        info = bj.insurance_analysis(
            current, game["shoe"], can_take=available >= insurance_cost
        )
        st.markdown("### Insurance decision")
        with st.container(key="table_controls"):
            st.markdown('<div class="eyebrow">Optional side bet · Dealer shows an Ace</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            take = c1.button(
                "Take insurance",
                type="primary",
                key=f"insurance_{current['id']}_True",
                use_container_width=True,
                disabled=available < insurance_cost,
            )
            decline = c2.button(
                "Decline insurance",
                type="primary",
                key=f"insurance_{current['id']}_False",
                use_container_width=True,
            )
            if available < insurance_cost:
                st.caption(f"Insurance needs {insurance_cost:,.0f} additional credits; {available:,.0f} are available.")
        show_math = st.toggle("Show hand math", value=False, key=f"show_insurance_math_{current['id']}")
        if show_math:
            _show_insurance_math(info)
        if take or decline:
            try:
                bj.choose_insurance(game, take, info)
                bj.commit_round_to_history(game)
                st.rerun()
            except ValueError as error:
                st.error(str(error))
        return

    if current["phase"] == "player":
        index = current["current_hand"]
        legal = bj.legal_actions(current, index, bj.available_balance(game))
        selected = _action_buttons(game, legal, f"act_{current['id']}_{index}")
        show_math = st.toggle("Show hand math", value=False, key=f"show_hand_math_{current['id']}_{index}")
        if show_math:
            show_hand_math(game, get_analysis(game, index), index)
        if selected:
            analysis = get_analysis(game, index)
            bj.apply_player_action(game, selected, analysis)
            bj.commit_round_to_history(game)
            st.rerun()
        return

    if current["phase"] == "dealer":
        with st.container(key="table_controls"):
            st.markdown('<div class="eyebrow">Dealer turn</div>', unsafe_allow_html=True)
            st.caption("Your hands are set. Reveal the dealer card and finish the hand under the active table rules.")
            if st.button("Play dealer turn", type="primary", key=f"dealer_{current['id']}", use_container_width=True):
                bj.play_dealer(game)
                bj.commit_round_to_history(game)
                st.rerun()
def _preset_changed() -> None:
    selected = st.session_state.get("preset_choice", "Custom rules")
    if selected not in PRESETS:
        return
    new_rules = deepcopy(PRESETS[selected])
    st.session_state["game_data"]["draft_rules"] = new_rules
    for key in RULE_FORM_KEYS:
        value = round(new_rules[key] * 100) if key == "penetration" else new_rules[key]
        st.session_state[rule_widget_key(key)] = value


def render_rules(game: dict[str, Any]) -> None:
    st.markdown("## Rules & shoe setup")
    st.markdown("Choose a preset, adjust the table, then start a **new shoe** to apply the rules. The active shoe always keeps its saved rules snapshot.")
    draft = game.setdefault("draft_rules", deepcopy(game["rules"]))
    if "preset_choice" not in st.session_state:
        initial = draft.get("name", "Custom rules")
        st.session_state["preset_choice"] = initial if initial in PRESETS else "Custom rules"
    for key in RULE_FORM_KEYS:
        value = round(draft[key] * 100) if key == "penetration" else draft[key]
        st.session_state.setdefault(rule_widget_key(key), value)

    st.selectbox(
        "Start from a preset",
        [*PRESETS.keys(), "Custom rules"],
        key="preset_choice",
        on_change=_preset_changed,
        help="Loading a preset fills the controls below. You can change any setting before starting the next shoe.",
    )
    if st.button("Load selected preset", key="load_selected_preset"):
        _preset_changed()
        st.rerun()

    st.markdown("### Cards, payout & dealer")
    left, right = st.columns(2)
    with left:
        st.select_slider("Number of decks", options=[1, 2, 4, 6, 8], key="rule_decks", help="A new shoe uses this many standard 52-card decks.")
        st.selectbox("Blackjack payout", ["3:2", "6:5", "1:1"], key="rule_blackjack_payout", help="Net profit for a natural blackjack, per unit wagered. A push against dealer blackjack remains a push.")
        st.selectbox("Dealer on soft 17", ["Stand soft 17", "Hit soft 17"], key="rule_dealer_soft_17", help="Changes how the dealer plays A+6 and other soft 17 hands.")
    with right:
        st.selectbox("Dealer card procedure", [bj.HOLE_PEEK, bj.HOLE_NO_PEEK, bj.NO_HOLE], key="rule_dealer_mode", help="Peek mode checks for blackjack under an Ace or ten before player decisions. No-peek modes reveal dealer blackjack after player play; extra wagers lose under the ENHC preset behavior.")
        st.checkbox("Insurance offered against dealer Ace", key="rule_insurance", help="Insurance costs half the initial wager and pays 2:1. Its EV is shown separately from the main hand.")
        st.checkbox("Late surrender available", key="rule_surrender", help="Allows surrender on an unsplit initial two-card hand. A negative peek is required where the dealer peeks; without a peek, a later dealer blackjack makes surrender lose the full wager.")

    st.markdown("### Doubling & splitting")
    left, right = st.columns(2)
    with left:
        st.selectbox("Double on", ["Any first two cards", "Hard 9–11 only", "10–11 only"], key="rule_double_rule", help="Restrictions apply to the initial decision and split hands when doubling after split is enabled.")
        st.checkbox("Double after split", key="rule_double_after_split", help="Allows doubling on the first two cards of a split hand, subject to the selected double restriction.")
        splitting = st.checkbox("Allow splitting pairs", key="rule_splitting", help="Enables pair splitting under the match rule and maximum hand count on the right.")
    with right:
        st.selectbox("What counts as a pair", ["Exact rank", "Any ten-value pair"], key="rule_split_match", disabled=not splitting, help="Exact rank treats 10, J, Q, and K as separate ranks. The alternate treats any two ten-value cards as a pair.")
        st.selectbox("Maximum split hands", [2, 3, 4], key="rule_max_split_hands", disabled=not splitting, help="Two hands allows one split and no resplit; three or four hands allow resplitting pairs until the selected cap.")
        st.checkbox("Split aces receive one card only", key="rule_split_aces_one_card", disabled=not splitting, help="If selected, each split-ace hand stands after one card unless a permitted ace resplit is available.")
        st.checkbox("Allow resplitting aces", key="rule_resplit_aces", disabled=not splitting or not st.session_state["rule_split_aces_one_card"], help="Aces may be split again when a split-ace hand receives another ace, up to the maximum split-hand count.")

    st.markdown("### Reshuffle")
    left, right = st.columns(2)
    with left:
        st.selectbox("Reshuffle condition", ["Penetration auto", "Manual only"], key="rule_reshuffle_mode", help="Automatic mode reshuffles before the next hand once the penetration setting is reached. Manual-only mode waits for you to press Reshuffle.")
    with right:
        st.slider("Penetration before shuffle", min_value=50, max_value=90, step=5, key="rule_penetration_pct", disabled=st.session_state["rule_reshuffle_mode"] != "Penetration auto", format="%d%%", help="Fraction of the shoe used before automatic reshuffle, checked between hands.")

    new_draft = {
        key: (st.session_state[rule_widget_key(key)] / 100 if key == "penetration" else st.session_state[rule_widget_key(key)])
        for key in RULE_FORM_KEYS
    }
    selected_preset = st.session_state.get("preset_choice", "Custom rules")
    preset_rules = PRESETS.get(selected_preset)
    matches_preset = bool(preset_rules) and all(new_draft[key] == preset_rules[key] for key in RULE_FORM_KEYS)
    new_draft["name"] = selected_preset if matches_preset else "Custom rules"
    game["draft_rules"] = new_draft
    st.session_state["game_data"] = game
    active = game["rules"]
    pending = any(new_draft.get(key) != active.get(key) for key in RULE_FORM_KEYS)
    if pending:
        st.warning(f"Draft rules differ from the active shoe ({active['name']}). The current shoe continues with its saved rules until a new shoe starts.")
    else:
        st.success(f"These rules match the active shoe: {active['name']}.")

    active_round = game.get("round") and game["round"].get("phase") != "complete"
    button_col, shuffle_col = st.columns(2)
    if button_col.button("Start new shoe with these rules", type="primary", disabled=bool(active_round), key="apply_rules"):
        game["rules"] = deepcopy(new_draft)
        game["shoe"] = bj.new_shoe(game["rules"])
        game["round"] = None
        st.session_state["game_data"] = game
        st.session_state.pop("_decision_cache", None)
        st.success("New shoe started. Its rules are now locked in.")
        st.rerun()
    if active_round:
        st.caption("Finish the current hand before starting a new shoe.")
    if shuffle_col.button("Reshuffle current rules", disabled=bool(active_round), key="manual_reshuffle"):
        game["shoe"] = bj.new_shoe(game["rules"])
        game["round"] = None
        st.session_state["game_data"] = game
        st.session_state.pop("_decision_cache", None)
        st.rerun()

    st.markdown("### Active shoe snapshot")
    active = game["rules"]
    facts = [
        f"**{active['decks']} decks** · blackjack **{active['blackjack_payout']}**",
        f"Dealer **{active['dealer_soft_17']}** · **{active['dealer_mode']}**",
        f"Double **{active['double_rule']}** · DAS **{'yes' if active['double_after_split'] else 'no'}**",
        f"Split **{'on' if active['splitting'] else 'off'}** · max hands **{active['max_split_hands']}** · split aces one card **{'yes' if active['split_aces_one_card'] else 'no'}** · resplit aces **{'yes' if active['resplit_aces'] else 'no'}**",
        f"Surrender **{'yes' if active['surrender'] else 'no'}** · insurance **{'yes' if active['insurance'] else 'no'}**",
        f"Reshuffle **{active['reshuffle_mode']}**" + (f" at {active['penetration']:.0%} penetration" if active["reshuffle_mode"] == "Penetration auto" else ""),
    ]
    st.markdown("\n\n".join(f"- {line}" for line in facts))


def render_history(game: dict[str, Any]) -> None:
    history = game.get("history", [])
    summary = bj.session_summary(history)
    st.markdown("## Session history")
    st.caption("Every completed hand stores its rule snapshot, shoe state, actions, result, and decision-time probabilities and EV estimates.")
    metrics = st.columns(6)
    metrics[0].metric("Rounds", summary["rounds"])
    metrics[1].metric("Player hands", summary["player_hands"])
    metrics[2].metric("Wins", summary["wins"])
    metrics[3].metric("Losses", summary["losses"])
    metrics[4].metric("Pushes", summary["pushes"])
    metrics[5].metric("Net credits", f"{summary['net']:+.2f}")
    if summary["rounds"]:
        st.metric("Player decisions matching EV recommendation", f"{summary['decision_accuracy']*100:.1f}%")

    export = {
        "app": APP_TITLE,
        "version": 1,
        "exported_at": bj._timestamp(),
        "starting_balance": game.get("starting_balance", DEFAULT_STARTING_BALANCE),
        "balance": game.get("balance", DEFAULT_STARTING_BALANCE),
        "active_rules": game["rules"],
        "draft_rules": game.get("draft_rules", game["rules"]),
        "current_shoe": {
            "shoe_id": game["shoe"]["id"],
            "remaining_counts": game["shoe"]["cards"],
            "initial_total": game["shoe"]["initial_total"],
        },
        "current_round": game.get("round"),
        "history": history,
    }
    st.download_button(
        "Download session backup (JSON)",
        data=json.dumps(export, ensure_ascii=False, indent=2),
        file_name="blackjack-lab-session.json",
        mime="application/json",
        key="download_session",
    )
    st.caption(
        f"Starting balance: {float(game.get('starting_balance', DEFAULT_STARTING_BALANCE)):,.0f} credits · "
        f"Current balance: {float(game.get('balance', DEFAULT_STARTING_BALANCE)):,.0f} credits."
    )
    if not history:
        st.info("Your first completed hand will appear here with its rule and shoe snapshots.")
        return
    for number, hand in enumerate(reversed(history), 1):
        actual_number = len(history) - number + 1
        net = float(hand.get("total_net", 0.0))
        result = "WIN" if net > 0 else "LOSS" if net < 0 else "PUSH"
        with st.expander(f"Hand {actual_number} · {result} {net:+.2f} credits · Shoe {hand.get('shoe_id', '?')} · {hand.get('completed_at', '')[:16].replace('T', ' ')}"):
            st.markdown(f"**Rules:** {hand['rules']['name']} · {hand['rules']['decks']} deck(s) · {hand['rules']['blackjack_payout']} blackjack · {hand['rules']['dealer_soft_17']} · {hand['rules']['dealer_mode']}")
            st.markdown(f"**Dealer:** {' · '.join(hand.get('dealer_cards', []))} ({hand.get('dealer_result', '')})  \n**Starting wager:** {hand['initial_wager']:g} credits  ·  **Total net:** {net:+.2f} credits  ·  **Shoe:** {hand.get('shoe_id', '?')}")
            if "balance_after" in hand:
                st.markdown(f"**Practice balance:** {float(hand.get('balance_before', 0)):,.0f} → {float(hand['balance_after']):,.0f} credits")
            shoe_state = hand.get("shoe_state", {})
            st.markdown(f"**Shoe state:** {shoe_state.get('cards_remaining_before', '?')} physical cards before the deal → {shoe_state.get('cards_remaining_after', '?')} after dealer play.")
            for hand_index, player_hand in enumerate(hand.get("hands", []), 1):
                cards = " · ".join(player_hand.get("cards", []))
                st.markdown(f"**Player hand {hand_index}:** {cards} · actions: {', '.join(player_hand.get('actions', [])) or 'natural / automatic'} · {player_hand.get('outcome', '')} · net {float(player_hand.get('net', 0)):+.2f} credits")
            if hand.get("insurance_taken"):
                st.markdown(f"**Insurance:** taken · net {float(hand.get('insurance_net', 0)):+.2f} credits")
            decisions = hand.get("decisions", [])
            if decisions:
                st.markdown("**Decision snapshots**")
                for decision in decisions:
                    if decision["type"] == "insurance":
                        probability = decision["probabilities"]["dealer_blackjack"]
                        st.markdown(f"- Insurance: chose **{decision['chosen']}**; recommended **{decision['recommended']}**. Dealer blackjack chance **{probability*100:.2f}%**; insurance EV **{decision['evs']['take insurance']:+.3f} units**.")
                        continue
                    values = decision["evs"]
                    ev_text = ", ".join(f"{action}: {entry['ev']:+.3f} ± {entry['se']:.3f}" for action, entry in values.items())
                    bust = decision["probabilities"].get("bust_on_hit")
                    bust_text = f" · bust if hit {bust*100:.1f}%" if bust is not None else ""
                    st.markdown(f"- Hand {decision['hand_number']} {', '.join(decision['cards'])} vs {decision['dealer_up']}: chose **{decision['chosen']}**, EV leader **{decision['recommended']}**{bust_text}.  \n  {ev_text}  \n  Shoe snapshot: {decision['unseen_total']} unseen cards; {decision['physical_remaining']} physical cards remaining. Method: {decision['method']}.")
                    st.caption(f"Recommendation gap at the time: {decision['recommendation_gap']:.3f} units per current hand wager.")
            st.markdown("**Complete rule snapshot**")
            st.json(hand["rules"], expanded=False)


def render_method() -> None:
    st.markdown("## How the math works")
    st.markdown(
        """
        ### One finite shoe, carried between hands

        Cards are counted by rank, with four of each rank per deck and sixteen ten-value cards per deck. Dealt cards are removed from the physical shoe. During an American hole-card hand, the hidden card stays out of sight but is added back into the *unseen* pool used by the probability model. A negative peek under an Ace or ten conditions simulated hole cards on that fact. European no-hole play draws the dealer's second card after the player hands.

        ### What an EV means here

        **Player action EV** is estimated net profit from the main hand, in units of the current hand wager. A split EV includes both hands created by the split, per one unit of the hand being considered. Insurance has a separate EV per unit of the original main wager. Each completed decision stores the then-current unknown-card composition and analysis, so later shoes or rule changes do not rewrite earlier recommendations.

        **Immediate bust chance** and **insurance probability** are calculated exactly from the current unseen card counts. Dealer outcome percentages and player action EVs are **finite-shoe Monte Carlo estimates** with standard errors shown. For each candidate action, simulations draw without replacement; after that candidate action, the rollout uses a rule-aware basic-strategy continuation to finish the player hand(s), then plays the dealer under the selected rules. The available practice bankroll limits later doubles and splits; an unfunded continuation double or split falls back to a hit, while one-card split aces stand. The recommendation is the action with the highest estimated EV under that continuation. It is not an exact globally optimal solver, and close EVs may be indistinguishable at the displayed sample count.

        ### Rule assumptions

        Surrender is late surrender. Insurance pays 2:1. American no-peek and European no-hole blackjack are revealed after player action; in either mode, split and double wagers lose to dealer blackjack, and a surrender also loses its full wager if dealer blackjack is later found. Split aces get one card when selected; resplitting aces is controlled separately. Suits do not affect blackjack outcomes and are decorative on the table.
        """
    )


def render_sidebar(game: dict[str, Any]) -> bool:
    with st.sidebar:
        st.markdown("# 🂡 Blackjack Lab")
        st.caption("Probability · expected value · practice")
        st.markdown("---")
        st.markdown(f"**Active rules**  \n{game['rules']['name']}")
        st.markdown(f"**Shoe**  `{game['shoe']['id']}`  ·  {sum(game['shoe']['cards'])} cards left")
        st.markdown(f"**Saved hands**  {len(game.get('history', []))}")
        st.markdown("---")
        with st.expander("Local saving", expanded=False):
            st.markdown("The persistent session is saved in this browser's local storage. While the app is open, Streamlit sends the current game state to its Python session for calculations; the app does not write a shared history file or account record. Saved sessions are scoped to this browser and app origin.")
        if st.session_state.get("_storage_warning"):
            st.warning(st.session_state.pop("_storage_warning"))
        storage_error = component_value("storage_error")
        if storage_error:
            st.warning(f"Browser local storage could not be updated: {storage_error}. Download a session backup from History.")
        if st.button("Erase saved data", key="request_erase", use_container_width=True):
            st.session_state["_confirm_erase"] = True
        confirm = st.session_state.get("_confirm_erase", False)
        if confirm:
            st.warning("Erase this browser's saved shoe and all hand history?")
            col1, col2 = st.columns(2)
            if col1.button("Erase now", type="primary", key="confirm_erase"):
                st.session_state.game_data = make_game_data()
                st.session_state["_erase_pending"] = True
                st.session_state["_confirm_erase"] = False
                st.session_state.pop("_decision_cache", None)
                st.session_state.pop("preset_choice", None)
                st.session_state.pop("wager_input", None)
                st.session_state.pop("starting_balance_input", None)
                for form_key in RULE_FORM_KEYS:
                    st.session_state.pop(rule_widget_key(form_key), None)
                return True
            if col2.button("Keep data", key="cancel_erase"):
                st.session_state["_confirm_erase"] = False
                st.rerun()
        st.markdown("---")
        st.caption("Practice credits only · no real-money play")
    return False


def main() -> None:
    st.set_page_config(page_title=APP_TITLE, page_icon="♠", layout="wide", initial_sidebar_state="expanded")
    style_app()

    if not hydrate_game():
        st.markdown('<div class="brand">BLACKJACK LAB · LOCAL PRACTICE</div>', unsafe_allow_html=True)
        st.title("Setting up your table")
        st.caption("Reading this browser's saved shoe and hand history…")
        mount_storage_bridge(ready=False)
        st.stop()

    game = get_game()
    if render_sidebar(game):
        game = get_game()
    st.markdown(
        '<div class="hero"><div><div class="brand">BLACKJACK LAB · PROBABILITY IN PLAY</div><h1 style="margin:.18rem 0 .18rem">The table is your classroom.</h1><div class="hero-note">Play a real shoe. See the math behind each choice. Keep every hand on this device.</div></div><div class="eyebrow">21 · EV · Finite shoe</div></div>',
        unsafe_allow_html=True,
    )
    table_tab, rules_tab, history_tab, method_tab = st.tabs(["♣  Table", "⚙  Rules & shoe", "▤  Hand history", "∑  How it works"])
    with table_tab:
        render_play(game)
    with rules_tab:
        render_rules(game)
    with history_tab:
        render_history(game)
    with method_tab:
        render_method()

    clear_now = bool(st.session_state.pop("_erase_pending", False))
    mount_storage_bridge(ready=True, payload=game, clear=clear_now)


if __name__ == "__main__":
    main()
