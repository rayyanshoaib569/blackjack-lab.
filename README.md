# Blackjack Lab

A solo blackjack practice table built with Streamlit and Python. Play a finite shoe, choose the rules before a new shoe, optionally inspect probability and expected-value estimates at each decision, and keep hand history in the browser on the device you use.

## Run locally

Requires Python 3.10 or newer.

```bash
python -m venv .venv
```

Activate the environment, then install the dependency and start Streamlit. In Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

On macOS or Linux:

```bash
source .venv/bin/activate
```

Then run:

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

Open the local address printed by Streamlit. There is no database, account, or deployment configuration in this project.

## What is included

- A playable table with hit, stand, double, split, resplit, surrender, insurance, and dealer play when those actions are legal under the active rules.
- A selectable practice balance from 1,000 to 10,000 credits. Wagers, insurance, doubles, and splits are limited by the available balance; the hand history records balance movement.
- Presets plus configurable deck count, blackjack payout, soft-17 rule, double restrictions, double after split, pair-matching rule, split-hand limit, split-ace behavior, surrender, insurance, dealer hole-card procedure, and reshuffle behavior.
- One finite shoe carried across hands. Cards already dealt are removed from the physical shoe. The app can reshuffle automatically at the selected penetration or wait for a manual reshuffle.
- A closed-by-default **Show hand math** panel with exact immediate bust and insurance probabilities, estimated dealer outcomes, EVs for legal actions, standard errors, and expandable reasoning.
- A history view with the rules snapshot, shoe state, dealt cards, actions, result, and probabilities/EVs recorded when each decision was made.
- Browser-local saving, a JSON session backup download, and an erase control.

## Local saving and privacy

The app uses a small inline Streamlit custom component to read and write `localStorage` in the browser. The selected starting balance, current balance, shoe, in-progress hand, active and draft rules, and completed hand history are stored under one versioned browser key. Each browser profile and app origin has its own persistent copy; no account or shared server-side history file is used. While the app is open, Streamlit sends the current game state to the Python session for game and EV calculations. If the browser blocks local storage or reaches its quota, the sidebar reports the issue and the History tab offers a JSON backup download.

Clearing browser site data also removes the saved session. The in-app **Erase saved data** control clears the local saved session and starts a fresh shoe. Different browser profiles, devices, hostnames, or ports have separate local storage.

## Probability and EV assumptions

Ranks are tracked as 2 through Ace, with four of each rank per deck (16 ten-value cards). Suits have no effect on blackjack probability and are decorative in the card display. Actual gameplay draws uniformly without replacement from the remaining physical shoe.

During American hole-card play, the dealer's hidden card is not shown or treated as revealed. It is included in the unseen-card composition used by the analysis. If a peek rules out dealer blackjack, the simulation conditions the hidden card on that information. With European no-hole-card rules, the dealer's second card is drawn after player action.

Immediate hit-bust probability and insurance probability are calculated from the current composition (including the negative-peek condition when relevant). Dealer outcome percentages and player action EVs are Monte Carlo estimates. The EV panel shows the estimated standard error and sample count. Each candidate action is sampled without replacement; after the candidate action, the player hand(s) are completed using a disclosed, rule-aware basic-strategy continuation policy, then the dealer is played under the active rules. Available practice credits also limit later doubles and splits; an unfunded rollout double or split falls back to a hit, while one-card split aces stand. The app recommends the candidate with the highest estimated EV under that continuation. This is not an exact globally optimal strategy solver, and close estimates can be statistically indistinguishable.

EV for a main-hand action is expected **net** return per one unit of the current hand wager; a split EV includes both split hands. Insurance is shown separately as expected net return per unit of the original main wager, assuming the standard 2:1 insurance payout. Dealer blackjack against a late surrender in no-peek play loses the full wager. In no-peek and European play, additional split/double wagers also lose to dealer blackjack. All decisions save the shoe composition and estimates that existed at that moment.

The displayed practice balance is a virtual credit total with no cash value. The main wager is reserved while a hand is in progress; extra wagers for insurance, doubles, and splits must fit within the remaining available credits. Completed-hand net results update the balance once when the hand is saved.

## Project layout

```text
app.py                 Streamlit UI, browser storage bridge, and views
blackjack_engine.py    Shoe, rules, play flow, probabilities, and EV rollout
requirements.txt       Python dependency
.streamlit/config.toml Streamlit theme and server defaults
```

The engine, presentation, and browser persistence are kept in separate areas so later additions can build on the same hand and session records.
