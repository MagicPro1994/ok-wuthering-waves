# BaitFishingTask: farm fish with Sandworm bait near the dock — design

Status: draft for review. No product code has been written.

## Goal

A one-time task, `BaitFishingTask`, that repeats one loop until the Sandworm bait runs out: launch bait to create a
fish spot, catch the fish, load every catch into the cargo, return to the dock, sell all, set sail again.

Out of scope: requests (Premium, Common, Chanty Bounty), long-distance sailing, marker steering, other bait types.
The Premium Request task is described in `2026-10-14-fishing-task-design.md`; this task reuses its helpers.

## Constraints (carried over from the Premium task)

- Human-like input: random key holds and pauses, offset clicks, no fixed-interval polling.
- Tool Key must be `t` (the `ok` library cannot send `mouse_x2`); the task checks this at start.
- The game runs elevated, so the project runs elevated. Drags use the real cursor (`RealInput`).
- Every state has a timeout. On a timeout, an unexpected dialog, low hearts, or a round with no progress: save a
  screenshot, notify, call `ensure_main`, stop. Never loop indefinitely.

## Observed UI (from the user's screenshots)

- **Bait utility icon** (bottom right): a bag with a "?" , the bait count at its top left (for example `189`),
  `0/3` under it, and the Tool Key `T` below.
- **Use Bait dialog** (after pressing `t` with Baiting equipped): "Use Sandworm as bait?" with Cancel and Confirm.
  Then the message "Sandworm launched" shows and a fish spot exists.
- **Fishing Complete screen**: shows only on the Sweet Puff path. Lists each catch with its cargo shape and value;
  "Tap the blank area to close".
- **Normal catch**: `[F] Fish` prompt, then the Space-timing mini-game, which finishes by itself in 15–30 s.
- **Sweet Puff**: a utility. Equip it, press `t`, and "Fishing Complete" shows at once. Optional: without it the
  task fishes normally. Out of stock means its utility count reads 0.
- **Utility switch**: press Tab (cursor mode), click the utility's image, then leave cursor mode. The equipped
  utility is the one on the bottom-right icon.
- **`0/3`**: the most fish spots bait can have at once. The task always creates one and fishes it, so it is ignored.
- **Dock bay**: the boat stays at the dock. `[F] Return to the dock` shows while it is close enough. Near the fish
  spot, `[F] Fish` shows as a second entry below it, and the entry list needs a mouse-wheel scroll down to select Fish.
- **Normal mini-game** ends by itself and moves straight to the Cargo screen.

## Approach

`BaitFishingTask(FishingTask)` in `src/task/BaitFishingTask.py`, registered in `config.py` `onetime_tasks`. It overrides
`run` and reuses `FishingTask` helpers: `go_to_dock`, `prepare_and_sail`, `hold_key`, `click_at`, `texts`,
`has_text`, `click_ocr_text`, `fail`, heart detection (`detect.hearts_state`), and `sell_all`. New code is kept in
small units:

- `src/task/BaitFishingTask.py`: the loop and its states.
- `src/fishing/cargo_screen.py`: reads the Cargo screen (free cells, fish shapes) and plans placements with the
  existing `cargo_packer.pack` / `pack_best`. Pure functions where possible, tested on saved screenshots.
- `src/fishing/human_input.py`: add a short, uneven "nudge" press helper if the existing ones do not fit.
- `config.py`: register the task.
- `tests/TestBaitFishing.py`, `tests/TestCargoScreen.py`: pure-logic tests and screenshot fixtures in
  `tests/images/fishing/`.

Alternative rejected: extracting the shared helpers into a mixin. It is cleaner, but it touches working code for no gain now.

## Flow

**Setup**
1. Check Tool Key is `t`. `ensure_main`.
2. If not already sailing (sea HUD absent), `go_to_dock`, then `prepare_and_sail`.
3. Equip the Baiting utility.

**Round** (repeat)
1. Read the bait count from the utility icon. If it is 0 or unreadable twice in a row: stop and notify
   "no bait left".
2. **Position**: if `[F] Return to the dock` is shown, press W in short, uneven presses until it disappears. The
   fish spot is created ahead of the boat, outside the dock prompt.
3. Equip Baiting if it is not. Press `t`, click Confirm on "Use Sandworm as bait?", wait for "Sandworm launched".
4. **Sweet Puff available?** (its utility count is above 0)
   - Yes: equip Sweet Puff, press `t`, wait for "Fishing Complete", click a blank area to close it.
   - No: press W in short, uneven presses (2–3) until `[F] Fish` shows, scroll the prompt list down to select
     Fish, press F, wait for the mini-game to end by itself (timeout about 60 s). It goes straight to the Cargo screen.
5. **Cargo screen**: read the free cells, each catch's shape and its value, choose placements with
   `pack_best` (value-optimising: big or high-value fish first, so the best catches fit), place the chosen
   catches (click its card, press Space if the preview is green, otherwise drag with the real cursor), click Finish.
6. Press S in short, uneven presses until `[F] Return to the dock` shows (bounded number of tries).
7. Press F, open the Dock Shop, Sell All (confirm "Request items for sale" if it shows), verify the Catch List
   reads "No Catch". If a fish is still selected ("Please handle the selected item first"), place it, then Sell All.
8. Set Sail again (reuse the Set Sail leg of `prepare_and_sail`). Next round.

Sell happens every round; there is no "sell when full" logic.

## Safety

- Heart check (existing detector) whenever the boat moves; abort at low hearts.
- If bait count does not drop after a launch, or no `[F] Fish` / "Fishing Complete" shows within its timeout, count a
  no-progress round; two in a row stops the task.
- Never press Esc blindly: it can open the system menu, and the dock's top-right X is Disembark.
- The boat must stay near the dock: nudges are short, and the task presses S back toward the dock when the dock
  prompt is lost.

## Testing

- Unit tests: bait count parsing, Use Bait dialog / message detection, Sweet Puff availability, round bookkeeping
  (count drop, no-progress counter), cargo planning on saved screens (including the empty-cargo fixture
  `tests/images/fishing/cargo_empty.png`).
- Live: run with the user watching, starting at sea near the dock with bait in stock.

## Open items, settled by live probing before the plan

- Utility switch: Tab menu layout, the click position of each utility image, and how to read the equipped utility
  and its count (bait, Sweet Puff).
- The Cargo screen: **the repo has no screen reading yet** (`handle_catches` is a stub; only `cargo_packer.py`
  exists). Needed: grid origin and cell size, free and blocked cells, each fish's shape and value, preview colour,
  the Finish button.
- Which catches the packer leaves out when cargo is full (they stay in the Catch List and Sell All sells them).
- How the `[F]` prompt list scrolls and which entry is selected by default.
- How many W presses clear the dock prompt, so the fish spot is not created too close to the dock.

## Build order

1. Utilities, bait launch, and the fishing step (both paths).
2. Cargo screen reading and placement.
3. The dock and sell leg, then the full loop.
