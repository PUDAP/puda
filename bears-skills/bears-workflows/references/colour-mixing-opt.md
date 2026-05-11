---
name: colour-mixing-opt
description: Iteratively mix RGB colours on an Opentrons OT-2 and minimize Delta E 2000 error between the mixed colour and a target colour using real-time camera feedback and BO or LLM optimization.
---

# Colour Mixing Optimization

description: Iteratively mix RGB colours on an Opentrons OT-2 and minimize Delta E 2000 error between the mixed colour and a target colour using real-time camera feedback and BO or LLM optimization.

## Required Skills

Invoke these skills before generating any commands:
- **puda-machines** → opentrons machine (liquid handling + `camera_capture`)
- **puda-protocol** → protocol generation and execution
- **puda-memory** → update `experiment.md` after every protocol creation and run
- **puda-report** → resolve the report **save path / output folder** only (the report filename and markdown layout are defined in this document)

## Required Machine

- **Opentrons OT-2** with camera attached (`machine_id: "opentrons"`)

## Core Principle 
The system must operate in a strict single-run, sequential execution loop.
At any time:
- Only **One active run** is allowed 
- Each iteration sues a **NEW run_id**
-No downstream step executres unless the run is **confirmed successful**

## Optimization Approaches

Ask the user which approach to use if not specified:

| Approach | When to use |
|---|---|
| **Bayesian Optimization (BO)** | Efficient for continuous volume ratios; fewer iterations to converge |
| **LLM** | Flexible reasoning; good when constraints or colour theory context matters |

See [optimization.md](optimization.md) for implementation details.

---

## Workflow

### Phase 0 — Run Lifecycle Safety

This applies to every iteration.

Mandatory Rules
-Never send play twice on same run
-Always poll until run reaches terminal state: successded, failed or stopped 

Hard Gate Condition

Proceed ONLY IF:
run.status == "succeeded"

Otherwise:
-STOP optimization loop
-Log failure
-Require recovery before continuing

### Phase 1 — Initialization

**Step 1 — Inputs (ask user before proceeding)**

Collect all of the following before starting. Do not proceed until every value is confirmed:

| Input | Description |
|---|---|
| Sample name | User-provided sample name to use in saved image filenames |
| Target colour source | Choose either `manual_rgb` or `measured_target_mix` |
| Target colour — if `manual_rgb` | `(R, G, B)` where each value is 0–255 |
| Target mix volumes — if `measured_target_mix` | One `(R_vol, G_vol, B_vol, water_vol)` set in µL to dispense, capture, process, and use as the target RGB |
| Target mix volume well — if `measured_target_mix` | Mapping of the target mix volume set to the destination well, for example `(100, 100, 100) µL -> C1` |
| Target mix destination well — if `measured_target_mix` | Well used for the target-mix calibration run; this target well is not an optimization seed well |
| Total well volume | Total volume in µL per well (e.g. 300 µL) |
| **R dye source — deck slot** | OT-2 deck slot (`"1"`–`"11"`) for the labware holding **red** dye only |
| **G dye source — deck slot** | Deck slot for the labware holding **green** dye only |
| **B dye source — deck slot** | Deck slot for the labware holding **blue** dye only |
| `x_init` — 3 initial mixes | User-provided volume sets (see below) |
| `x_init` destination wells | Three user-selected destination wells, one for each `x_init` mix |
| Optimization approach | BO (EI or LCB) or LLM (choose model) |
| Maximum iterations | Stop after this many iterations |

**Critical — RGB dye labware are three separate deck positions**

The R, G, and B dyes are loaded as **three independent `load_labware` calls** with **three separate `location` values**. You must **ask the user for each slot individually** (R, then G, then B — or present one form with three distinct fields). **Do not** ask a single question such as “which slot is the dye plate?” and reuse that answer for R, G, and B. **Do not** assume all three dye plates share the same slot.

When generating protocols, map aspirate sources to the user’s **R slot / G slot / B slot** explicitly — never copy one slot onto all three dye labware loads.

**Target colour source**

Ask the user how the target RGB should be obtained before starting:

| Option | Workflow |
|---|---|
| `manual_rgb` | Use the existing method: the user directly provides the target `(R, G, B)` values, each 0-255. |
| `measured_target_mix` | The user provides one RGB dye volume combination. Generate and run a target-mix protocol, capture an image, process the target well, and use the measured median RGB as the target for optimization. |

For `manual_rgb`:
- Validate that the provided target has exactly three numeric values.
- Validate that every value is between 0 and 255.
- Use this RGB tuple directly as `(R_target, G_target, B_target)`.

For `measured_target_mix`:
- Ask for one target mix volume set `(R_vol, G_vol, B_vol, water_vol)` in µL.
- Validate that the target mix volumes sum to `total_volume` (±1 µL tolerance): `R+G+B+water=total_volume`.
- Ask for the destination well used for this target-mix calibration run.
- Record the target mix volume well mapping explicitly, for example `(R_vol, G_vol, B_vol, water_vol) -> target_well`.
- Generate a standalone protocol that dispenses only this target mix.
- Execute the protocol, then capture one whole-wellplate image.
- Run `run_pipeline(image_path, well_ids=[target_well], config=DEFAULT_CONFIG)`.
- Use the measured median RGB from `target_well` as `(R_target, G_target, B_target)` for all later Delta E 2000 calculations.
- Do not include the target-mix calibration well in `x_init` observations or optimizer history.
- If protocol execution, image capture, or image processing fails, stop before generating `x_init` and require recovery.

After deriving the measured target RGB, record it as the target colour and continue to `x_init` without asking for another user confirmation.

**`x_init` — Initial volume inputs**

Ask the user to provide exactly 3 initial volume combinations for R, G, B, and water in µL. Each set must sum to the total well volume.
Validate each set before generating the protocol — reject and re-ask if any set does not sum to `total_volume` (±1 µL tolerance).

Ask the user to choose exactly 3 destination wells for `x_init`, one well for each initial volume combination.

Validation rules:
- Each `x_init` well must be a valid well ID for the destination labware.
- The 3 `x_init` wells must be unique.
- The selected wells must be mapped explicitly to the 3 initial volume combinations, for example: `x_init 1 -> B1`, `x_init 2 -> B2`, `x_init 3 -> B3`.
- If `measured_target_mix` used a well in the same destination plate, the `x_init` wells must not include the target well unless the user explicitly confirms the plate has been cleared or replaced.
- Do not assume `A1`, `A2`, and `A3`; use only the wells confirmed by the user.

**Step 1a — User confirmation before execution**
After all inputs have been collected and validated, present a setup summary back to the user that also states the labware positions, and ask for explicit confirmation before generating or executing any protocol.

The confirmation summary must include:
- Sample name
- Target colour source
- Total well volume
- Labware positions
- R / G / B source deck slots
- If `manual_rgb`: target colour RGB
- If `measured_target_mix`: target mix volumes, target mix destination well, target mix volume well mapping, and planned target image filename
- All 3 `x_init` volume combinations
- All 3 `x_init` destination wells and their mapping to the initial volume combinations
- Optimization approach
- Maximum iterations


Do not generate the `x_init` protocol until the user confirms that the full setup is correct.

If `measured_target_mix` is selected, the target-mix calibration protocol may be generated and executed only after the user confirms the target-mix setup. After the target image is processed successfully, continue directly to `x_init` using the measured target RGB.

**Step 2 — Initial mixes (`x_init`)**
Generate a single protocol that dispenses all 3 initial volume combinations into the 3 user-selected `x_init` destination wells and execute it on the Opentrons. Record which confirmed well received which `(R_vol, G_vol, B_vol, water_vol)` set.

If `measured_target_mix` used a well in the same destination plate, reserve that target well and do not reuse it for `x_init` or later optimization wells unless the user explicitly confirms the plate has been cleared or replaced.

Tip usage must advance in row-major order on the tip rack:

```text
A1, A2, A3, ... A12, B1, B2, ... H12
```
Use tips strictly in that exact order across the target-mix calibration run, `x_init`, and all later iterations. For example, if `manual_rgb` is used and `x_init` uses 3 tips, they must be `A1`, `A2`, `A3`; the next iteration must continue with `A4`, then `A5`, then `A6`, and so on. If `measured_target_mix` uses 1 tip first, that target run must use `A1`, `x_init` must continue with `A2`, `A3`, `A4`, and the next iteration must continue from `A5`.

**Execution Sequence (MUST FOLLOW EXACTLY)**
1. Upload protocol
2. Create run -> store `run_id`
3. Verify:
   - No active run
   - Robot not in error state
4. Start run (`play`)
5. Poll run status until terminal

**Step 3 — Capture whole-wellplate image**
After the protocol completes (all 3 mixes dispensed), use `camera_capture` **once** to capture the entire wellplate showing the whole wellplate with 3 mixed colours. Save the image as:
```
colour-RGB-<Sample name that user input>-<N>.jpg
```
Use the exact sample name provided by the user in the filename. `<N>` is the run number and must increment for every new run so images never overwrite earlier files. Do not omit `<N>`, and do not save the file as only `colour-RGB-<Sample name>.jpg`.

Run numbering for image filenames:
- If `manual_rgb` is used: `x_init` image -> `colour-RGB-<Sample name that user input>-1.jpg`
- If `measured_target_mix` is used: target-mix image -> `colour-RGB-<Sample name that user input>-1.jpg`, then `x_init` image -> `colour-RGB-<Sample name that user input>-2.jpg`
- First BO/LLM-suggested run -> next available `<N>` after `x_init`
- Second BO/LLM-suggested run -> next available `<N>` after the first BO/LLM-suggested run
- Continue increasing by 1 for every later run

> **Important**: Capture ONE image after the `x_init` protocol is dispensed, and then ONE image after each later optimization iteration — not one image per mix.

If `measured_target_mix` is used, also capture ONE image after the target-mix calibration protocol. This target image is used only to derive `(R_target, G_target, B_target)` and is not counted as `x_init` or as an optimization iteration.

**Step 3a — Image processing (`x_init` and every optimization iteration)**
The image processing pipeline uses fixed, calibrated parameters — no VLM is needed. Call `run_pipeline()` on the captured image. The steps run in this exact order:
1. Apply fixed perspective correction using calibrated `src_corners` and `dst_corners` → flat deck image
2. Slice the warped plate image into a `row_num × col_num` ROI grid (one patch per well)
3. Compute median RGB for each requested well by `well_id`

All parameters are stored in `DEFAULT_CONFIG` in `image_processing.py`. Re-calibrate only if the camera is physically moved. See [image-processing.md](image-processing.md) for the full field reference.

---

### Phase 2 — Per-Iteration Loop

**Step 4 — Image processing**
Call `run_pipeline(image_path, well_ids, config=DEFAULT_CONFIG)` on the captured image. The pipeline uses fixed calibrated parameters for perspective correction and ROI slicing.

For the `x_init` image, `well_ids` must be the 3 user-selected `x_init` destination wells in the same order as the confirmed `x_init` mapping.

See [image-processing.md](image-processing.md).

**Step 5 — ROI extraction for all wells**
Slice the warped plate image into one ROI patch per well, in row-major order (left to right, top to bottom). This covers every well on the plate regardless of whether it has a mix or is empty.

**Step 6 — RGB extraction from active wells**
Compute the median RGB for each extracted ROI patch. Then select the RGB values for the wells that contain the mixes (by `well_id`, derived from the protocol's well assignments):
- User-selected `x_init 1` well → `(R_mix_1, G_mix_1, B_mix_1)`
- User-selected `x_init 2` well → `(R_mix_2, G_mix_2, B_mix_2)`
- User-selected `x_init 3` well → `(R_mix_3, G_mix_3, B_mix_3)`

**Step 7 — Delta E 2000 calculation**
Compute Delta E 2000 for each well that received a mix.
Use [../scripts/metric.py](../scripts/metric.py) and `calculate_delta_e_2000((R_mix, G_mix, B_mix), (R_target, G_target, B_target))`.
For the 3 initial mixes this produces `DeltaE_1`, `DeltaE_2`, `DeltaE_3`.

**Step 8 — Optimizer feedback**
Pass all `(volume_ratios, Delta E 2000)` pairs (one per active well) to the chosen optimizer:
- **BO**: seed the surrogate model with all 3 initial `(ratio, Delta E 2000)` observations
- **LLM**: provide the full list of `(ratios, RGB, Delta E 2000)` for all 3 initial mixes and request the next suggestion

**Step 9 — New volume ratio suggestion**
The optimizer returns the next `(R_vol, G_vol, B_vol, water_vol)` to try.

**Step 10 — Iteration report**
For each new set of optimization, create a new report file named `colour-mixing-report-<sample name that user input>.md`. Defer to the **puda-report** skill only for the save path / output folder — the filename above and the markdown layout described below in this document are authoritative (puda-report decides **where** the file is written, not **how** it is written). Do not count the 3 `x_init` mixes as iterations. After the initial protocol finishes, append three separate seed log blocks titled `x_init 1`, `x_init 2`, and `x_init 3` (one block per initial mix). Then start optimization iteration counting from the first parameter set suggested by BO or LLM and append one block after every optimization iteration.

Each `x_init` log block must record:
- Which seed run it is: `x_init 1`, `x_init 2`, or `x_init 3`
- The user-selected destination well for that seed run
- Delta E 2000 for that initial mix only
- The volume ratio and measured RGB value for that initial mix only

If `measured_target_mix` was used, the report must also record a target calibration block before the `x_init` blocks:
- Target colour source: `measured_target_mix`
- Target mix volume ratio
- Target mix destination well
- Target image filename
- Measured target RGB used for optimization

Example target calibration log block:

```markdown
## Target Colour Calibration

| Field | Value |
|---|---|
| Target colour source | measured_target_mix |
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target well | <target_well> |
| Target mix volume ratio (R, G, B, water µL) | (<R_vol>, <G_vol>, <B_vol>, <water_vol>) |
| Measured target colour RGB | (<R_target>, <G_target>, <B_target>) |
```

Example `x_init` log block:

```markdown
## x_init 1

| Field | Value |
|---|---|
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |

### Wells processed in x_init 1

| Well | Volume ratio (R, G, B, water µL) | Mixed colour RGB | Delta E 2000 |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

```markdown
## Iteration <N>

| Field | Value |
|---|---|
| Iteration | <N> |
| Image saved | colour-RGB-<Sample name that user input>-<N>.jpg |
| Target colour RGB | (<R_target>, <G_target>, <B_target>) |
| Next suggested ratio (R, G, B, water) | (<R_next> µL, <G_next> µL, <B_next> µL, <water_next> µL) |
| Stop condition reached | Yes / No |

### Wells processed this iteration

| Well | Volume ratio (R, G, B, water µL) | Mixed colour RGB | Delta E 2000 |
|---|---|---|---|
| <well_id> | (<R_vol>, <G_vol>, <B_vol>) | (<R_mix>, <G_mix>, <B_mix>) | <value> |
```

The 3 initial `x_init` mixes are seed observations, not iterations, so they should not be written as `Iteration <N>` blocks. They must instead be recorded as three separate blocks titled `x_init 1`, `x_init 2`, and `x_init 3`. After those seed entries, the first BO/LLM-suggested run must be recorded as `Iteration 1`, then `Iteration 2`, `Iteration 3`, and so on. Each optimization iteration block should have 1 row in "Wells processed" for the single BO/LLM-suggested mix.

**Step 11 — Generate and execute protocol**
Use **puda-protocol** to generate a new protocol with the suggested volumes and execute it on the Opentrons.

---

### Phase 3 — Stop Condition

Stop only when this is met:

| Condition | Description |
|---|---|
| `iteration ≥ max_iter` | Maximum optimization iterations reached (not counting the 3 `x_init` mixes) |

On stop: generate a final summary report using the markdown structure defined in this document, and write it to `colour-mixing-report-<sample name that user input>.md` at the save path resolved by the **puda-report** skill.

## Rules

- Always ask for target colour source and max iterations **before** starting.
- If target colour source is `manual_rgb`, validate and use the user-provided target RGB.
- If target colour source is `measured_target_mix`, run the target-mix calibration, process the target well image, and use the measured RGB as the target before generating `x_init`.
- Always ask the user to choose exactly 3 unique `x_init` destination wells; never assume `A1`, `A2`, and `A3`.
- Always collect **three separate deck slots** for R, G, and B dye source labware before any `load_labware` for those sources; never use one slot for all three.
- Always ask the user for explicit confirmation after all required inputs are collected and validated, before the first protocol is generated or executed.
- Never ask the user to paste API keys, tokens, passwords, or other secrets into chat.
- If `LLM` optimization requires credentials such as `OPENROUTER_API_KEY`, require them to be pre-configured in the local environment outside the chat before running.
- If the required LLM credential is missing, stop and tell the user to set it locally, but do not ask them to reveal the secret value and do not write the secret into prompts, config files, protocol files, or shell commands.
- `OPENROUTER_BASE_URL` must also be set in the local `.env` file before running any LLM optimizer. If it is not found, stop and instruct the user to add it and do not proceed until the variable is confirmed set.
- Never assume volume ratios — they must come from the optimizer at each iteration.
- Image names must follow `colour-RGB-<Sample name that user input>-<N>.jpg` exactly, where `<N>` is the run number and increments on every run.
- Tip pickup order must be strictly `A1, A2, ... A12, B1, B2, ... H12`
- Protocol must always end with no tip attached (Opentrons sequencing rule).
- Invoke **puda-memory** after every protocol creation and run.
- Use **puda-report** only to resolve the report **save path / output folder**. The report filename (`colour-mixing-report-<sample name that user input>.md`) and the markdown layout (`x_init N` blocks, `Iteration N` blocks, final summary) are defined in this document and must not be changed by puda-report.
- **If unsure about any input, parameter, or decision — ask the user. Do not assume.**