"""Blackjack rules, shoe management, play flow, and Monte Carlo EV analysis.

The game engine is deterministic outside of the explicitly shuffled shoe and
the repeatable Monte Carlo estimate used for decision coaching.
"""

from __future__ import annotations

import hashlib
import json
import random
import uuid
from copy import deepcopy
from typing import Any


RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
RANK_INDEX = {rank: index for index, rank in enumerate(RANKS)}
VALUE = {rank: (11 if rank == "A" else 10 if rank in {"10", "J", "Q", "K"} else int(rank)) for rank in RANKS}

HOLE_PEEK = "American hole card + peek"
HOLE_NO_PEEK = "American hole card, no peek"
NO_HOLE = "European no-hole-card (ENHC)"


def make_shoe(decks: int) -> list[int]:
    return [4 * decks for _ in RANKS]


def card_value(card: str) -> int:
    return VALUE[card]


def hand_value(cards: list[str]) -> tuple[int, bool]:
    total = sum(1 if card == "A" else card_value(card) for card in cards)
    aces = sum(card == "A" for card in cards)
    soft = False
    if aces and total + 10 <= 21:
        total += 10
        soft = True
    return total, soft


def is_blackjack(cards: list[str]) -> bool:
    return len(cards) == 2 and hand_value(cards)[0] == 21


def new_shoe(rules: dict[str, Any]) -> dict[str, Any]:
    count = make_shoe(int(rules["decks"]))
    return {
        "id": uuid.uuid4().hex[:8].upper(),
        "cards": count,
        "initial_total": sum(count),
        "rounds": 0,
        "created_at": _timestamp(),
    }


def reserved_balance(game: dict[str, Any]) -> float:
    """Credits committed to the unfinished hand and its side bet."""
    round_state = game.get("round")
    if not round_state or round_state.get("phase") == "complete":
        return 0.0
    committed = sum(float(hand.get("wager", 0.0)) for hand in round_state.get("hands", []))
    if round_state.get("insurance_taken"):
        committed += float(round_state.get("initial_wager", 0.0)) * 0.5
    return committed


def available_balance(game: dict[str, Any]) -> float:
    """Credits not already committed to the current unfinished hand."""
    return max(0.0, float(game.get("balance", game.get("starting_balance", 2500.0))) - reserved_balance(game))


def _timestamp() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def draw_card(counts: list[int], rng: random.Random) -> str:
    total = sum(counts)
    if total <= 0:
        raise ValueError("The shoe is empty. Start a new shoe before dealing.")
    ticket = rng.randrange(total)
    for index, amount in enumerate(counts):
        if ticket < amount:
            counts[index] -= 1
            return RANKS[index]
        ticket -= amount
    raise RuntimeError("Unable to draw from shoe")


def draw_restricted(counts: list[int], rng: random.Random, allowed: set[str]) -> str:
    allowed_indices = [RANK_INDEX[rank] for rank in allowed if counts[RANK_INDEX[rank]] > 0]
    total = sum(counts[index] for index in allowed_indices)
    if total <= 0:
        raise ValueError("No valid hidden card remains for the selected peek condition.")
    ticket = rng.randrange(total)
    for index in allowed_indices:
        if ticket < counts[index]:
            counts[index] -= 1
            return RANKS[index]
        ticket -= counts[index]
    raise RuntimeError("Unable to draw restricted card")


def dealer_has_blackjack(upcard: str, hole: str) -> bool:
    return (upcard == "A" and card_value(hole) == 10) or (card_value(upcard) == 10 and hole == "A")


def unseen_counts(shoe: dict[str, Any], round_state: dict[str, Any]) -> list[int]:
    counts = list(shoe["cards"])
    hole = round_state.get("dealer_hole")
    if hole is not None and not round_state.get("hole_revealed", False):
        counts[RANK_INDEX[hole]] += 1
    return counts


def split_pair(cards: list[str], rules: dict[str, Any]) -> bool:
    if len(cards) != 2:
        return False
    if rules.get("split_match") == "Any ten-value pair" and card_value(cards[0]) == card_value(cards[1]) == 10:
        return True
    return cards[0] == cards[1]


def split_allowed(cards: list[str], hand: dict[str, Any], rules: dict[str, Any], hand_count: int) -> bool:
    if not rules["splitting"] or not split_pair(cards, rules) or hand_count >= int(rules["max_split_hands"]):
        return False
    if hand.get("split_aces") and not rules["resplit_aces"]:
        return False
    return True


def double_allowed(cards: list[str], hand: dict[str, Any], rules: dict[str, Any]) -> bool:
    if len(cards) != 2:
        return False
    if hand.get("from_split") and not rules["double_after_split"]:
        return False
    total, soft = hand_value(cards)
    restriction = rules["double_rule"]
    if restriction == "Any first two cards":
        return True
    if soft:
        return False
    if restriction == "Hard 9–11 only":
        return total in {9, 10, 11}
    if restriction == "10–11 only":
        return total in {10, 11}
    return False


def legal_actions(
    round_state: dict[str, Any], hand_index: int, available: float | None = None
) -> list[str]:
    hand = round_state["hands"][hand_index]
    rules = round_state["rules"]
    cards = hand["cards"]
    total, _ = hand_value(cards)
    if hand["status"] != "active" or total >= 21:
        return []
    if hand.get("split_aces") and rules["split_aces_one_card"]:
        actions = ["stand"]
        if split_allowed(cards, hand, rules, len(round_state["hands"])) and (
            available is None or available >= float(hand["wager"])
        ):
            actions.append("split")
        return actions
    actions = ["stand", "hit"]
    if double_allowed(cards, hand, rules) and (
        available is None or available >= float(hand["wager"])
    ):
        actions.append("double")
    if split_allowed(cards, hand, rules, len(round_state["hands"])) and (
        available is None or available >= float(hand["wager"])
    ):
        actions.append("split")
    if rules["surrender"] and not hand.get("from_split") and len(cards) == 2:
        actions.append("surrender")
    return actions


def bust_probability(
    cards: list[str],
    counts: list[int],
    dealer_up: str | None = None,
    peek_no_blackjack: bool = False,
) -> float:
    total_cards = sum(counts)
    if not total_cards:
        return 0.0
    if peek_no_blackjack and dealer_up is not None:
        allowed_holes = _hole_allowed_ranks(dealer_up)
        allowed_total = sum(counts[RANK_INDEX[rank]] for rank in allowed_holes)
        if allowed_total > 0 and total_cards > 1:
            # One unseen card is reserved as the dealer's hidden card, selected
            # only from ranks consistent with the negative peek. Integrate over
            # that hidden card to get the exact next-player-card marginal.
            bust_mass = 0.0
            for index, rank in enumerate(RANKS):
                count = counts[index]
                if not count or hand_value(cards + [rank])[0] <= 21:
                    continue
                hidden_probability_mass = count / allowed_total if rank in allowed_holes else 0.0
                bust_mass += count - hidden_probability_mass
            return max(0.0, bust_mass / (total_cards - 1))
    bust_cards = sum(
        amount
        for index, amount in enumerate(counts)
        if amount and hand_value(cards + [RANKS[index]])[0] > 21
    )
    return bust_cards / total_cards


def _hole_allowed_ranks(upcard: str) -> set[str]:
    if upcard == "A":
        return {rank for rank in RANKS if card_value(rank) != 10}
    if card_value(upcard) == 10:
        return {rank for rank in RANKS if rank != "A"}
    return set(RANKS)


def _has_peek_constraint(round_state: dict[str, Any]) -> bool:
    return bool(
        round_state.get("peek_no_blackjack")
        and round_state["rules"]["dealer_mode"] == HOLE_PEEK
    )


def _draw_dealer_hole(counts: list[int], rng: random.Random, upcard: str, constrained: bool) -> str:
    return draw_restricted(counts, rng, _hole_allowed_ranks(upcard)) if constrained else draw_card(counts, rng)


def simulate_dealer(
    upcard: str,
    hole: str | None,
    counts: list[int],
    rules: dict[str, Any],
    rng: random.Random,
) -> tuple[list[str], str]:
    dealer_cards = [upcard]
    if hole is None:
        hole = draw_card(counts, rng)
    dealer_cards.append(hole)
    if is_blackjack(dealer_cards):
        return dealer_cards, "blackjack"
    total, soft = hand_value(dealer_cards)
    while total < 17 or (total == 17 and soft and rules["dealer_soft_17"] == "Hit soft 17"):
        dealer_cards.append(draw_card(counts, rng))
        total, soft = hand_value(dealer_cards)
    if total > 21:
        return dealer_cards, "bust"
    return dealer_cards, str(total)


def _can_double(cards: list[str], from_split: bool, rules: dict[str, Any]) -> bool:
    return double_allowed(cards, {"from_split": from_split}, rules)


def _baseline_action(
    cards: list[str],
    dealer_up: str,
    rules: dict[str, Any],
    from_split: bool,
    split_aces: bool,
    current_hand_count: int,
    allow_surrender: bool = True,
) -> str:
    """Rule-aware basic-strategy continuation for Monte Carlo rollouts.

    This is a disclosed continuation policy; the first action being compared is
    selected by the simulated EVs, not by this policy.
    """
    total, soft = hand_value(cards)
    up = card_value(dealer_up)
    can_split = split_allowed(
        cards,
        {"from_split": from_split, "split_aces": split_aces},
        rules,
        current_hand_count,
    )
    can_double = _can_double(cards, from_split, rules)

    if can_split:
        rank = cards[0]
        pair_value = card_value(rank)
        should_split = (
            pair_value == 11
            or pair_value == 8
            or (pair_value == 9 and up in {2, 3, 4, 5, 6, 8, 9})
            or (pair_value == 7 and up <= 7)
            or (pair_value == 6 and up <= 6)
            or (pair_value == 4 and up in {5, 6})
            or (pair_value in {2, 3} and up <= 7)
        )
        if should_split:
            return "split"

    if split_aces and rules["split_aces_one_card"]:
        return "stand"

    if allow_surrender and rules["surrender"] and not from_split and len(cards) == 2:
        if (total == 16 and up in {9, 10, 11}) or (total == 15 and up == 10):
            return "surrender"

    if soft:
        if total >= 19:
            return "stand"
        if total == 18:
            if up in {9, 10, 11}:
                return "hit"
            if up in {3, 4, 5, 6} and can_double:
                return "double"
            return "stand"
        if total in {17, 16} and up in {3, 4, 5, 6} and can_double:
            return "double"
        if total in {15, 14} and up in {4, 5, 6} and can_double:
            return "double"
        if total in {13, 14} and up in {5, 6} and can_double:
            return "double"
        return "hit"

    if total >= 17:
        return "stand"
    if total >= 13 and up <= 6:
        return "stand"
    if total == 12 and up in {4, 5, 6}:
        return "stand"
    if total == 11 and can_double:
        return "double"
    if total == 10 and up <= 9 and can_double:
        return "double"
    if total == 9 and up in {3, 4, 5, 6} and can_double:
        return "double"
    return "hit"


def _play_rollout_hands(
    starting_hands: list[dict[str, Any]],
    counts: list[int],
    dealer_up: str,
    rules: dict[str, Any],
    rng: random.Random,
    total_hand_count: int,
    extra_budget: float | None = None,
    max_draws: int = 20,
) -> list[dict[str, Any]]:
    queue = [deepcopy(hand) for hand in starting_hands]
    index = 0
    draw_steps = 0
    while index < len(queue):
        hand = queue[index]
        if hand.get("needs_card"):
            hand["cards"].append(draw_card(counts, rng))
            hand["needs_card"] = False
            draw_steps += 1
        cards = hand["cards"]
        total, _ = hand_value(cards)
        if total >= 21:
            hand["done"] = True
            index += 1
            continue

        # Aces normally receive one card. A permitted re-split of aces is the
        # only decision offered before the hand is forced to stand.
        if hand.get("split_aces") and rules["split_aces_one_card"]:
            if split_allowed(cards, hand, rules, total_hand_count):
                action = "split"
            else:
                hand["done"] = True
                index += 1
                continue
        else:
            action = _baseline_action(
                cards,
                dealer_up,
                rules,
                bool(hand.get("from_split")),
                bool(hand.get("split_aces")),
                total_hand_count,
            )

        if action == "split" and extra_budget is not None and extra_budget < float(hand.get("bet", 1.0)):
            action = "stand" if hand.get("split_aces") and rules["split_aces_one_card"] else "hit"
        if action == "double" and extra_budget is not None and extra_budget < float(hand.get("bet", 1.0)):
            action = "hit"

        if action == "split" and split_allowed(cards, hand, rules, total_hand_count) and (
            extra_budget is None or extra_budget >= float(hand.get("bet", 1.0))
        ):
            if extra_budget is not None:
                extra_budget -= float(hand.get("bet", 1.0))
            is_aces = cards[0] == "A" or (rules.get("split_match") == "Any ten-value pair" and card_value(cards[0]) == 11)
            child_a = {
                "cards": [cards[0]],
                "from_split": True,
                "split_aces": is_aces,
                "needs_card": True,
                "bet": float(hand.get("bet", 1.0)),
            }
            child_b = {
                "cards": [cards[1]],
                "from_split": True,
                "split_aces": is_aces,
                "needs_card": True,
                "bet": float(hand.get("bet", 1.0)),
            }
            queue[index : index + 1] = [child_a, child_b]
            total_hand_count += 1
            continue
        if action == "double" and _can_double(cards, bool(hand.get("from_split")), rules) and (
            extra_budget is None or extra_budget >= float(hand.get("bet", 1.0))
        ):
            if extra_budget is not None:
                extra_budget -= float(hand.get("bet", 1.0))
            hand["cards"].append(draw_card(counts, rng))
            hand["bet"] = float(hand.get("bet", 1.0)) * 2
            hand["done"] = True
            draw_steps += 1
            index += 1
            continue
        if action == "surrender" and not hand.get("from_split"):
            hand["surrendered"] = True
            hand["done"] = True
            index += 1
            continue
        if action == "split" and hand.get("split_aces") and rules["split_aces_one_card"]:
            hand["done"] = True
            index += 1
            continue
        if action == "hit":
            hand["cards"].append(draw_card(counts, rng))
            draw_steps += 1
            if hand_value(hand["cards"])[0] >= 21:
                hand["done"] = True
                index += 1
            elif draw_steps >= max_draws:
                hand["done"] = True
                index += 1
            continue
        hand["done"] = True
        index += 1
    return queue


def _hand_net(
    hand: dict[str, Any],
    dealer_result: str,
    dealer_bj: bool,
    rules: dict[str, Any],
) -> float:
    bet = float(hand.get("bet", 1.0))
    cards = hand["cards"]
    total, _ = hand_value(cards)
    if dealer_bj:
        if is_blackjack(cards) and not hand.get("from_split"):
            return 0.0
        if hand.get("surrendered"):
            return -bet
        return -bet
    if hand.get("surrendered"):
        return -0.5 * bet
    if total > 21:
        return -bet
    if is_blackjack(cards) and not hand.get("from_split"):
        return bet * _payout_multiplier(rules["blackjack_payout"])
    if dealer_result == "bust":
        return bet
    dealer_total = int(dealer_result)
    if total > dealer_total:
        return bet
    if total < dealer_total:
        return -bet
    return 0.0


def _payout_multiplier(label: str) -> float:
    return {"3:2": 1.5, "6:5": 1.2, "1:1": 1.0}[label]


def _evaluate_one_sample(
    action: str,
    hand: dict[str, Any],
    dealer_up: str,
    counts: list[int],
    rules: dict[str, Any],
    mode: str,
    peek_no_blackjack: bool,
    total_hand_count: int,
    rng: random.Random,
    available: float | None = None,
) -> float:
    remaining = list(counts)
    hole: str | None = None
    if mode != NO_HOLE:
        hole = _draw_dealer_hole(remaining, rng, dealer_up, peek_no_blackjack)

    current_cards = list(hand["cards"])
    from_split = bool(hand.get("from_split"))
    split_aces = bool(hand.get("split_aces"))
    unit_bet = 1.0
    extra_budget = (
        None if available is None else max(0.0, float(available) / max(0.01, float(hand.get("wager", 1.0))))
    )
    if action == "surrender":
        played_hands = [{"cards": current_cards, "from_split": from_split, "bet": unit_bet, "surrendered": True}]
    elif action == "stand":
        played_hands = [{"cards": current_cards, "from_split": from_split, "split_aces": split_aces, "bet": unit_bet}]
    elif action == "double":
        current_cards.append(draw_card(remaining, rng))
        played_hands = [{"cards": current_cards, "from_split": from_split, "split_aces": split_aces, "bet": 2.0}]
    elif action == "hit":
        current_cards.append(draw_card(remaining, rng))
        starting = [{"cards": current_cards, "from_split": from_split, "split_aces": split_aces, "bet": unit_bet}]
        if hand_value(current_cards)[0] > 21 or hand_value(current_cards)[0] == 21:
            played_hands = starting
        else:
            played_hands = _play_rollout_hands(
                starting, remaining, dealer_up, rules, rng, total_hand_count, extra_budget
            )
    elif action == "split":
        is_aces = current_cards[0] == "A"
        children = [
            {"cards": [current_cards[0]], "from_split": True, "split_aces": is_aces, "needs_card": True, "bet": unit_bet},
            {"cards": [current_cards[1]], "from_split": True, "split_aces": is_aces, "needs_card": True, "bet": unit_bet},
        ]
        if extra_budget is not None:
            extra_budget = max(0.0, extra_budget - unit_bet)
        played_hands = _play_rollout_hands(
            children, remaining, dealer_up, rules, rng, total_hand_count + 1, extra_budget
        )
    else:
        raise ValueError(f"Unknown action: {action}")

    dealer_cards, dealer_result = simulate_dealer(dealer_up, hole, remaining, rules, rng)
    dealer_bj = dealer_result == "blackjack"
    return sum(_hand_net(result_hand, dealer_result, dealer_bj, rules) for result_hand in played_hands) / unit_bet


def _stable_seed(value: Any) -> int:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return int.from_bytes(hashlib.sha256(encoded).digest()[:8], "big")


def estimate_action_evs(
    round_state: dict[str, Any],
    hand_index: int,
    counts: list[int],
    simulations: int = 1000,
    available: float | None = None,
) -> dict[str, dict[str, float]]:
    hand = round_state["hands"][hand_index]
    actions = legal_actions(round_state, hand_index, available)
    fingerprint = {
        "hand": hand["cards"],
        "from_split": hand.get("from_split", False),
        "split_aces": hand.get("split_aces", False),
        "up": round_state["dealer_up"],
        "counts": counts,
        "rules": round_state["rules"],
        "peek": round_state.get("peek_no_blackjack", False),
        "hands": len(round_state["hands"]),
        "actions": actions,
    }
    base_seed = _stable_seed(fingerprint)
    estimates: dict[str, dict[str, float]] = {}
    for action_index, action in enumerate(actions):
        rng = random.Random(base_seed + action_index * 7919)
        values = [
            _evaluate_one_sample(
                action,
                hand,
                round_state["dealer_up"],
                counts,
                round_state["rules"],
                round_state["rules"]["dealer_mode"],
                _has_peek_constraint(round_state),
                len(round_state["hands"]),
                rng,
                available,
            )
            for _ in range(simulations)
        ]
        mean = sum(values) / simulations
        variance = sum((value - mean) ** 2 for value in values) / max(1, simulations - 1)
        estimates[action] = {
            "ev": mean,
            "se": (variance / simulations) ** 0.5,
            "samples": simulations,
        }
    return estimates


def dealer_distribution(
    round_state: dict[str, Any], counts: list[int], simulations: int = 1800
) -> dict[str, float]:
    rules = round_state["rules"]
    up = round_state["dealer_up"]
    constraint = _has_peek_constraint(round_state)
    seed = _stable_seed({"dealer": up, "counts": counts, "rules": rules, "peek": constraint})
    rng = random.Random(seed)
    outcomes: dict[str, int] = {"blackjack": 0, "bust": 0, "17": 0, "18": 0, "19": 0, "20": 0, "21": 0}
    for _ in range(simulations):
        remaining = list(counts)
        hole = _draw_dealer_hole(remaining, rng, up, constraint) if rules["dealer_mode"] != NO_HOLE else None
        _, result = simulate_dealer(up, hole, remaining, rules, rng)
        outcomes[result] = outcomes.get(result, 0) + 1
    return {key: value / simulations for key, value in outcomes.items()}


def decision_analysis(
    round_state: dict[str, Any],
    shoe: dict[str, Any],
    hand_index: int,
    available: float | None = None,
) -> dict[str, Any]:
    counts = unseen_counts(shoe, round_state)
    actions = legal_actions(round_state, hand_index, available)
    evs = estimate_action_evs(round_state, hand_index, counts, available=available)
    recommendation = max(evs, key=lambda action: evs[action]["ev"])
    player_cards = round_state["hands"][hand_index]["cards"]
    distribution = dealer_distribution(round_state, counts)
    return {
        "actions": actions,
        "evs": evs,
        "recommended": recommendation,
        "bust_probability": bust_probability(
            player_cards,
            counts,
            round_state["dealer_up"],
            _has_peek_constraint(round_state),
        ) if "hit" in actions else None,
        "dealer_outcomes": distribution,
        "unseen_counts": counts,
        "unseen_total": sum(counts),
        "physical_remaining": sum(shoe["cards"]),
        "simulation_count": 1000,
        "method": "Finite-shoe Monte Carlo; rule-aware basic-strategy continuation",
    }


def insurance_analysis(
    round_state: dict[str, Any], shoe: dict[str, Any], can_take: bool = True
) -> dict[str, Any]:
    counts = unseen_counts(shoe, round_state)
    total = sum(counts)
    up = round_state["dealer_up"]
    target = {RANK_INDEX[rank] for rank in RANKS if card_value(rank) == 10} if up == "A" else {RANK_INDEX["A"]}
    probability = sum(counts[index] for index in target) / total if total else 0.0
    ev = probability * 1.0 + (1 - probability) * -0.5
    return {
        "dealer_blackjack_probability": probability,
        "insurance_ev_per_main_wager": ev,
        "recommended": "take insurance" if ev > 0 and can_take else "decline insurance",
        "take_available": can_take,
        "unseen_counts": counts,
        "unseen_total": total,
        "physical_remaining": sum(shoe["cards"]),
    }


def _next_phase_after_peek(round_state: dict[str, Any]) -> None:
    rules = round_state["rules"]
    mode = rules["dealer_mode"]
    up = round_state["dealer_up"]
    hole = round_state.get("dealer_hole")
    can_peek = mode == HOLE_PEEK and hole is not None and (up == "A" or card_value(up) == 10)
    if can_peek and dealer_has_blackjack(up, hole):
        round_state["dealer_blackjack"] = True
        round_state["hole_revealed"] = True
        dealer_cards = [up, hole]
        round_state["dealer_cards"] = dealer_cards
        round_state["dealer_result"] = "blackjack"
        _complete_round(round_state, dealer_cards, "blackjack")
        return
    if can_peek:
        round_state["peek_no_blackjack"] = True
    if is_blackjack(round_state["hands"][0]["cards"]):
        round_state["phase"] = "dealer"
    else:
        round_state["phase"] = "player"


def deal_round(game: dict[str, Any], wager: float) -> None:
    balance = float(game.get("balance", game.get("starting_balance", 2500.0)))
    if wager <= 0 or wager > balance:
        raise ValueError("The wager must be at least 1 credit and no larger than your balance.")
    shoe = game["shoe"]
    rules = game["rules"]
    if game.get("round") and game["round"].get("phase") != "complete":
        raise ValueError("Finish the current round before dealing another hand.")
    if rules["reshuffle_mode"] == "Penetration auto":
        dealt_fraction = 1 - sum(shoe["cards"]) / max(1, shoe["initial_total"])
        if dealt_fraction >= float(rules["penetration"]):
            shoe = new_shoe(rules)
            game["shoe"] = shoe
    rng = random.SystemRandom()
    player_one = draw_card(shoe["cards"], rng)
    dealer_up = draw_card(shoe["cards"], rng)
    player_two = draw_card(shoe["cards"], rng)
    hole = draw_card(shoe["cards"], rng) if rules["dealer_mode"] != NO_HOLE else None
    shoe["rounds"] += 1
    round_state = {
        "id": uuid.uuid4().hex[:10].upper(),
        "shoe_id": shoe["id"],
        "rules": deepcopy(rules),
        "initial_wager": float(wager),
        "balance_before": balance,
        "dealer_up": dealer_up,
        "dealer_hole": hole,
        "dealer_cards": [dealer_up],
        "hole_revealed": False,
        "hands": [
            {
                "cards": [player_one, player_two],
                "wager": float(wager),
                "from_split": False,
                "split_aces": False,
                "status": "active",
                "actions": [],
                "outcome": None,
                "net": None,
            }
        ],
        "current_hand": 0,
        "phase": "insurance" if rules["insurance"] and dealer_up == "A" else "pending_peek",
        "insurance_taken": False,
        "insurance_ev": None,
        "peek_no_blackjack": False,
        "dealer_blackjack": False,
        "actions": [],
        "decisions": [],
        "started_at": _timestamp(),
        "shoe_remaining_before": sum(shoe["cards"]) + 3 + (1 if hole else 0),
    }
    game["round"] = round_state
    if round_state["phase"] == "pending_peek":
        _next_phase_after_peek(round_state)


def choose_insurance(game: dict[str, Any], take: bool, analysis: dict[str, Any]) -> None:
    round_state = game["round"]
    if not round_state or round_state["phase"] != "insurance":
        return
    insurance_cost = float(round_state["initial_wager"]) * 0.5
    if take and available_balance(game) < insurance_cost:
        raise ValueError("There are not enough available credits for insurance.")
    round_state["insurance_taken"] = bool(take)
    round_state["insurance_ev"] = analysis["insurance_ev_per_main_wager"]
    round_state["decisions"].append(
        {
            "type": "insurance",
            "dealer_up": round_state["dealer_up"],
            "probabilities": {"dealer_blackjack": analysis["dealer_blackjack_probability"]},
            "evs": {
                "take insurance": analysis["insurance_ev_per_main_wager"],
                "decline insurance": 0.0,
            },
            "recommended": analysis["recommended"],
            "chosen": "take insurance" if take else "decline insurance",
            "unseen_counts": list(analysis["unseen_counts"]),
            "unseen_total": analysis["unseen_total"],
            "physical_remaining": analysis["physical_remaining"],
            "method": "Exact composition probability; 2:1 insurance payout",
        }
    )
    _next_phase_after_peek(round_state)


def _advance_to_active_hand(round_state: dict[str, Any]) -> None:
    for index in range(round_state.get("current_hand", 0), len(round_state["hands"])):
        if round_state["hands"][index]["status"] == "active":
            round_state["current_hand"] = index
            round_state["phase"] = "player"
            return
    for index, hand in enumerate(round_state["hands"]):
        if hand["status"] == "active":
            round_state["current_hand"] = index
            round_state["phase"] = "player"
            return
    round_state["phase"] = "dealer"


def apply_player_action(
    game: dict[str, Any],
    action: str,
    analysis: dict[str, Any],
) -> None:
    round_state = game["round"]
    if not round_state or round_state["phase"] != "player":
        return
    index = int(round_state["current_hand"])
    hand = round_state["hands"][index]
    actions = legal_actions(round_state, index, available_balance(game))
    if action not in actions:
        raise ValueError(f"{action} is not legal for this hand.")
    rng = random.SystemRandom()
    chosen_ev = analysis["evs"][action]["ev"]
    recommended = analysis["recommended"]
    decision = {
        "type": "player",
        "hand_number": index + 1,
        "cards": list(hand["cards"]),
        "dealer_up": round_state["dealer_up"],
        "probabilities": {
            "bust_on_hit": analysis["bust_probability"],
            "dealer_outcomes": deepcopy(analysis["dealer_outcomes"]),
        },
        "evs": deepcopy(analysis["evs"]),
        "recommended": recommended,
        "chosen": action,
        "chosen_ev": chosen_ev,
        "recommendation_gap": max(0.0, analysis["evs"][recommended]["ev"] - chosen_ev),
        "unseen_counts": list(analysis["unseen_counts"]),
        "unseen_total": analysis["unseen_total"],
        "physical_remaining": analysis["physical_remaining"],
        "simulation_count": analysis["simulation_count"],
        "method": analysis["method"],
        "recorded_at": _timestamp(),
    }
    round_state["decisions"].append(decision)
    hand["actions"].append(action)
    round_state["actions"].append({"hand_number": index + 1, "action": action, "cards_before": list(hand["cards"])})

    if action == "stand":
        hand["status"] = "stood"
    elif action == "hit":
        card = draw_card(game["shoe"]["cards"], rng)
        hand["cards"].append(card)
        round_state["actions"][-1]["card"] = card
        total, _ = hand_value(hand["cards"])
        if total > 21:
            hand["status"] = "bust"
        elif total == 21:
            hand["status"] = "stood"
    elif action == "double":
        hand["wager"] *= 2
        card = draw_card(game["shoe"]["cards"], rng)
        hand["cards"].append(card)
        round_state["actions"][-1]["card"] = card
        hand["status"] = "bust" if hand_value(hand["cards"])[0] > 21 else "stood"
    elif action == "split":
        left, right = hand["cards"]
        is_aces = left == right == "A"
        old_wager = hand["wager"]
        hand.update(
            {
                "cards": [left],
                "from_split": True,
                "split_aces": is_aces,
                "status": "active",
                "actions": hand["actions"][:],
            }
        )
        new_hand = {
            "cards": [right],
            "wager": old_wager,
            "from_split": True,
            "split_aces": is_aces,
            "status": "active",
            "actions": [],
            "outcome": None,
            "net": None,
        }
        round_state["hands"].insert(index + 1, new_hand)
        first_card = draw_card(game["shoe"]["cards"], rng)
        second_card = draw_card(game["shoe"]["cards"], rng)
        hand["cards"].append(first_card)
        new_hand["cards"].append(second_card)
        round_state["actions"][-1]["split_cards"] = [first_card, second_card]
        if is_aces and round_state["rules"]["split_aces_one_card"]:
            for child in (hand, new_hand):
                if not (
                    child["cards"][0] == child["cards"][1] == "A"
                    and round_state["rules"]["resplit_aces"]
                    and split_allowed(child["cards"], child, round_state["rules"], len(round_state["hands"]))
                ):
                    child["status"] = "stood"
        for child in (hand, new_hand):
            if hand_value(child["cards"])[0] >= 21:
                child["status"] = "stood"
    _advance_to_active_hand(round_state)


def _main_hand_net(hand: dict[str, Any], dealer_result: str, dealer_bj: bool, rules: dict[str, Any]) -> tuple[float, str]:
    bet = float(hand["wager"])
    cards = hand["cards"]
    total, _ = hand_value(cards)
    if dealer_bj:
        if is_blackjack(cards) and not hand.get("from_split"):
            return 0.0, "Push (both blackjack)"
        if hand["status"] == "surrendered":
            return -bet, "Loss (dealer blackjack; surrender loses full bet without a peek)"
        return -bet, "Loss (dealer blackjack)"
    if hand["status"] == "surrendered":
        return -0.5 * bet, "Surrender"
    if total > 21:
        return -bet, "Bust"
    if is_blackjack(cards) and not hand.get("from_split"):
        return bet * _payout_multiplier(rules["blackjack_payout"]), f"Blackjack +{rules['blackjack_payout']}"
    if dealer_result == "bust":
        return bet, "Win (dealer bust)"
    dealer_total = int(dealer_result)
    if total > dealer_total:
        return bet, "Win"
    if total < dealer_total:
        return -bet, "Loss"
    return 0.0, "Push"


def _complete_round(round_state: dict[str, Any], dealer_cards: list[str], dealer_result: str) -> None:
    rules = round_state["rules"]
    dealer_bj = dealer_result == "blackjack"
    round_state["dealer_cards"] = list(dealer_cards)
    round_state["dealer_result"] = dealer_result
    round_state["dealer_blackjack"] = dealer_bj
    round_state["hole_revealed"] = True
    for hand in round_state["hands"]:
        net, label = _main_hand_net(hand, dealer_result, dealer_bj, rules)
        hand["net"] = net
        hand["outcome"] = label
    insurance_net = 0.0
    if round_state.get("insurance_taken"):
        insurance_net = 1.0 * round_state["initial_wager"] if dealer_bj else -0.5 * round_state["initial_wager"]
    round_state["insurance_net"] = insurance_net
    round_state["total_net"] = sum(float(hand["net"] or 0.0) for hand in round_state["hands"]) + insurance_net
    round_state["total_wagered"] = sum(float(hand["wager"]) for hand in round_state["hands"]) + (
        round_state["initial_wager"] * 0.5 if round_state.get("insurance_taken") else 0.0
    )
    round_state["shoe_remaining_after"] = None
    round_state["completed_at"] = _timestamp()
    round_state["phase"] = "complete"


def play_dealer(game: dict[str, Any]) -> None:
    round_state = game.get("round")
    if not round_state or round_state["phase"] != "dealer":
        return
    shoe = game["shoe"]
    rules = round_state["rules"]
    rng = random.SystemRandom()
    up = round_state["dealer_up"]
    hole = round_state.get("dealer_hole")
    if hole is None:
        hole = draw_card(shoe["cards"], rng)
        round_state["dealer_hole"] = hole
    dealer_cards = [up, hole]
    if is_blackjack(dealer_cards):
        result = "blackjack"
    else:
        total, soft = hand_value(dealer_cards)
        while total < 17 or (total == 17 and soft and rules["dealer_soft_17"] == "Hit soft 17"):
            dealer_cards.append(draw_card(shoe["cards"], rng))
            total, soft = hand_value(dealer_cards)
        result = "bust" if total > 21 else str(total)
    _complete_round(round_state, dealer_cards, result)
    round_state["shoe_remaining_after"] = sum(shoe["cards"])


def commit_round_to_history(game: dict[str, Any]) -> None:
    round_state = game.get("round")
    if not round_state or round_state.get("phase") != "complete" or round_state.get("history_saved"):
        return
    shoe = game["shoe"]
    if round_state.get("shoe_remaining_after") is None:
        round_state["shoe_remaining_after"] = sum(shoe["cards"])
    if not round_state.get("balance_settled"):
        balance = float(game.get("balance", game.get("starting_balance", 2500.0)))
        round_state.setdefault("balance_before", balance)
        game["balance"] = balance + float(round_state.get("total_net", 0.0))
        round_state["balance_after"] = game["balance"]
        round_state["balance_settled"] = True
    round_state["shoe_state"] = {
        "shoe_id": round_state["shoe_id"],
        "cards_remaining_before": round_state["shoe_remaining_before"],
        "cards_remaining_after": round_state["shoe_remaining_after"],
        "remaining_counts_after": list(shoe["cards"]),
    }
    game.setdefault("history", []).append(deepcopy(round_state))
    round_state["history_saved"] = True


def session_summary(history: list[dict[str, Any]]) -> dict[str, float | int]:
    if not history:
        return {"rounds": 0, "player_hands": 0, "wins": 0, "losses": 0, "pushes": 0, "net": 0.0, "decision_accuracy": 0.0}
    wins = losses = pushes = 0
    total_net = 0.0
    decision_count = matched = 0
    player_hands = 0
    for round_state in history:
        total_net += float(round_state.get("total_net", 0.0))
        for hand in round_state.get("hands", []):
            player_hands += 1
            result = hand.get("outcome", "")
            if result.startswith("Win") or result.startswith("Blackjack"):
                wins += 1
            elif result.startswith("Loss") or result == "Bust" or result == "Surrender":
                losses += 1
            elif result.startswith("Push") or result == "Push":
                pushes += 1
        for decision in round_state.get("decisions", []):
            if decision.get("type") == "player":
                decision_count += 1
                matched += decision.get("chosen") == decision.get("recommended")
    return {
        "rounds": len(history),
        "player_hands": player_hands,
        "wins": wins,
        "losses": losses,
        "pushes": pushes,
        "net": total_net,
        "decision_accuracy": matched / decision_count if decision_count else 0.0,
    }

