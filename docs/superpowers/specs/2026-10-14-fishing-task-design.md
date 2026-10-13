# FishingTask: auto Premium Request (Riccioli Islands fishing) — design

Status: draft for review. No product code has been written.

## Goal

A one-time task, `FishingTask`, that completes the **Premium Request** of the permanent event
"Old Man and the…" (Planck the octopus, Riccioli Islands) once per run, then sells all fish at the Dock Shop.

Out of scope: Common Requests, Chanty Bounty, paid refreshes, and any request other than Premium.

Premium refreshes about hourly. If no Premium entry is listed, the task exits cleanly without sailing.

## Constraints and decisions made with the user

- **Night.** Before Set Sail, always select **Night** and tick **Automatically restore durability**.
- **Time of day.** All fish are available at night. When the target marker does not show, set the in-game time
  to night: Esc, clock icon, drag the dial to 18:00 or later, Confirm. In-game time runs fast, so it reaches 19:00 within minutes.
- **Human-like input (hard requirement).** The tool must not look like a macro:
  - key holds, pauses, and camera moves use random durations, never fixed ones;
  - camera turns are split into several small, uneven mouse steps;
  - clicks land at small random offsets inside the target, not on exact pixels;
  - random short pauses between actions; no fixed-interval polling loops.
- **No middle-click camera recentre.** The camera is aimed with relative mouse movement.
- **Tool Key must be `t`.** `configs/Game Hotkey.json` has `mouse_x2`, which the installed `ok` library cannot send.
  The task checks this at start and stops with a clear message.
- **Elevation.** The game runs elevated, so the project runs elevated (`run_main_admin.bat`).
- **Real cursor for drags.** Message-based drags do not move cargo pieces or the time dial. Drags use the real cursor
  with the game in the foreground. Do not restore or resize the game window while doing this.

## Approach

One `FishingTask(WWOneTimeTask, BaseWWTask)` state machine, registered in `config.py` `onetime_tasks`.
The cargo packer is a separate pure module. Screens are detected by OCR; the marker and radar by colour
and geometry in code. This needs no new template annotations.

Files:
- `src/task/FishingTask.py`: the task and its states.
- `src/fishing/cargo_packer.py`: pure packing function (unit-testable without the game).
- `src/fishing/human_input.py`: jittered holds, chunked camera turns, offset clicks.
- `tests/TestCargoPacker.py`: packer tests.
- `config.py`: register the task.
- `configs/Game Hotkey.json`: `Tool Key` to `t`.

## Flow (one pass)

1. **Go to dock.** Events icon, "Old Man and the…", wait for loading (30–60 s). F on Planck.
2. **Pick request.** Fishing Request. If Premium is not listed, exit. Otherwise select it and Track.
3. **Prepare.** Set Sail, then in Sailing Preparation select **Night**, tick **Automatically restore durability
   before sailing**, then Set Sail and confirm. (Fractions of the 1920×1080 client: Night about (0.928, 0.256),
   checkbox about (0.703, 0.796), confirm about (0.83, 0.93).)
4. **Sail.** See "Sailing" below.
5. **Fish.** At the "[F] Fish" prompt, press F. The mini-game finishes by itself in about 15 s. Close
   "Fishing Complete" by clicking a blank area. Repeat sailing and fishing until all objectives show complete.
6. **Cargo.** On the Catches screen, for each needed fish: click its card, press Space if the preview is green,
   otherwise drag it to the cell chosen by the packer. Click Finish.
7. **Deliver.** T (Fast Travel to Dock), Confirm, F "Return to the dock", the request's "…", Deliver, close rewards.
8. **Sell.** Open Dock Shop, then press **Sell All** once. If a fish is still selected, the game says
   "Please handle the selected item first", so place it on a free cell (drag if red), then Sell All.
   Sell All sells the whole Catch List, including catches never placed in the cargo. If a "Request items for
   sale" dialog appears, press Confirm. Verify the Catch List reads "No Catch".

## Sailing

- **Signal.** The 3D purple round marker with its distance label. Find it as a connected component in the
  purple colour range, filtered by size and aspect ratio (the boat's purple sail must not match).
  Not the radar arrow: its heading was read 180° wrong in testing, and the minimap cannot reliably separate land from water.
- **Controls.** Movement is camera-relative. Aim the camera with relative mouse movement, hold W, and use A/D only
  for small corrections. Measured: about 21 px of screen per degree for the marker offset, about 83°/s for A/D.
- **Approach.** Steer in short, randomised W presses. Inside about 30 m use short presses until the
  "[F] Fish" prompt appears (it appears at about 5–7 m). Stop on the prompt, never on the distance alone.
- **Land.** A land collision costs a heart. Rule: on heart loss or no movement across steps, reverse (S) for a
  randomised 1–2 s, turn the camera about 45° away, and retry; go around islands and rock faces, not through them.
- **Hazards.** Ghosts (for example "Ghost Medusa") and tornadoes cost hearts too, and the "Threat Level" bar rises.
  Detect heart loss by counting red heart pixels in the bottom row. Steer away from the hazard (turn about 90°, then
  continue). Abort when hearts reach 2 or fewer.
- **Marker lost.** If the marker is not visible, sweep the camera in small steps. If it is still not found after a
  full turn, set the time to night (see Constraints) and retry once, then stop with a message.
- **Never** stand idle for long at sea: in-game time passes and the night ends.

## Cargo packer

Input: the free cells of the 52-slot grid (7 rows, blocked corner cells excluded) and the shape of each
fish as a set of cells (four-cell and five-cell tetromino-like pieces, with rotation by R).
Output: for each fish, a rotation and an anchor cell.
Algorithm: backtracking over pieces, largest first, trying rotations and placements; the grid is small, so this is fast.
Needs per-fish shape reading from the Catches screen preview (the highlighted cells). The default spawn position
often overlaps blocked or occupied cells (shown red); always drag, never rely on it.

## Errors and recovery

Each state has a timeout. On timeout, an unexpected dialog, or hearts at 2 or fewer: save a screenshot, log, call
`ensure_main`, and stop. The task never loops indefinitely. Do not press Esc blindly: Esc can open the system
menu, and the X at the top right of the dock is **Disembark**, which prompts a dialog.

## Testing

- `TestCargoPacker`: fixtures with blocked corners, rotations, and the shapes seen in this session.
- Marker and heart detectors: tested on saved screenshots in `tests/` (frames from the probe run).
- The task itself: run live while the user watches. Start from the main world screen.

## Open items to settle during implementation

- How the project's input layer should perform real-cursor drags (the probes used a separate elevated helper).
- The ship dash key was never found; it is optional and left out.
- Per-fish shape reading for the packer; fall back to dragging to the first free cell when reading fails.
- Whether to add a `DailyTask` hook (left out for now).
