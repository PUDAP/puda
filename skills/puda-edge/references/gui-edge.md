# Build a PUDA GUI edge from task instructions

## Start from edge-python-gui-template

Use [PUDAP/edge-python-gui-template](https://github.com/PUDAP/edge-python-gui-template) on GitHub as the scaffold and [PUDAP/opentrons-gui-edge](https://github.com/PUDAP/opentrons-gui-edge) as the worked instrument example. Read the template's `README.md`, `driver.py`, `gui_driver.py`, `cua_client.py`, `main.py`, and tests before adapting it.

The architecture is `EdgeRunner` → `Driver(GuiDriver)` → `CuaDriverClient` → `cua-driver` MCP → instrument application. The AI interprets a manual or screenshots with task instructions and writes Python workflows. At runtime the driver selects exact accessibility controls and checks results; it does not invoke an LLM to interpret each action.

The GitHub template was verified at commit `63b9295f44f50a040e468f63b951291299dbe9a9`. The Opentrons example was inspected at `a0762ba358887633b07693ec753669d5e022fa6c`. These commits identify reviewed examples, not mandatory pins. Use the GitHub repository as the source; no pre-existing local template directory is required.

Clone it into a new machine project:

```bash
git clone https://github.com/PUDAP/edge-python-gui-template.git <machine-name>-gui-edge
cd <machine-name>-gui-edge
uv sync
```

Preserve the template's launchers, dependencies, and tests in the new machine project. Read Python and package requirements from the template's current `pyproject.toml` and lockfile. Follow its setup instructions; adapt project metadata and `.env.example` for the new instrument.

## Explore, then implement machine workflows

Keep `capture_screenshot(include_elements=True)` as the only low-level remote command. It supplies the image, capture context, and accessibility elements needed to inspect the application. Expose machine-specific workflows with `@command`.

`GuiDriver` supplies undecorated Python helpers for `find_element`, `wait_for_element`, `click_element`, `set_value`, `type_text`, `scroll`, `press_key`, and `click_at`. Compose these inside high-level workflows; do not expose them as remote commands. If a template revision still includes decorated delegates for these helpers, remove the delegates while retaining the inherited implementations.

Use screenshots, task instructions, and any available manual to establish labels, roles, transitions, and completion indicators, then implement workflows in `driver.py`'s high-level section. Adapt `import_file`'s example Import/Browse/error labels and its completion check; they are placeholders, not a universal import procedure. Opentrons replaces that example with `import_protocol` and exposes machine workflows plus `capture_screenshot`.

## Gather the machine context

Use the available manual or user-provided screenshots and instructions to understand one atomic task. A manual is optional: annotated screenshots or a sequence of screenshots showing where to click, which fields to fill, what text to type, and what completion looks like can supply the procedure. Do not block implementation solely because no manual exists. Keep source material and generated notes under `docs/`.

1. Identify the instrument model, installed application version, operating system, desktop session, and requested workflows. Review the provided screenshots and task description. Record the starting screen, ordered actions, variable inputs, and expected final state. If a manual is available, record its source and revision and check applicability.
2. If using a PDF manual, extract searchable text while retaining page boundaries. When Poppler is available:

   ```bash
   pdfinfo docs/vendor-manual.pdf
   pdftotext -layout docs/vendor-manual.pdf docs/vendor-manual.txt
   rg -n -i 'setup|start|pause|cancel|alarm|interlock|calibrat' docs/vendor-manual.txt
   ```

   Adapt search terms to the requested workflows. Inspect rendered pages for diagrams, screenshots, tables, and warnings that text extraction misses. Use OCR for scanned pages. Cite one-based PDF page numbers and printed page labels where different; search-result line numbers are not page numbers.
3. Generate concise task notes from the supplied instructions and screenshots, adding relevant manual details when available. Link each step to its screenshot or manual page. Include known prerequisites, inputs, expected outcomes, and relevant errors or side effects. Separate supplied instructions, observed behavior, and unresolved assumptions; do not invent missing details.
4. When desktop access is available, inspect the installed application using `capture_screenshot(include_elements=True)`. Record window identity, exact labels and roles, control hierarchy, enabled states, dialogs, and observed transitions. Save relevant screenshots and matching accessibility data under `docs/captures/`, removing sensitive information. Use live accessibility data to confirm exact selectors. Supplied screenshots identify intended targets but do not establish accessibility roles or reusable capture IDs. Without live access, implement from supported evidence and record selectors or transitions that still need verification.
5. Generate a workflow contract in `docs/gui-contract.md` linking the supplied procedure to controls and success evidence. Record any discrepancies between the source material and installed application. Use the notes and captures to implement machine-specific commands and offline test fixtures.
6. If documentation or desktop access is incomplete, continue with supported scaffolding and identify the exact missing evidence. Keep unverified actions unexposed or fail before input. Ask only for information you cannot obtain from available sources; do not ask the user to transcribe documents you can read.

Keep generated notes traceable to their sources. Encode supported workflows in Python so runtime commands do not need to reinterpret the instructions or screenshots.

## Define commands from procedures

Record each workflow contract in project notes (for example, `docs/gui-contract.md`) and its command docstring. Include:

| Field | Required detail |
| --- | --- |
| Purpose and source | Operator outcome and user instructions, screenshot references, or manual pages; app version when known |
| Inputs | Types, units, bounds, defaults, path location, exact matching and duplicate handling |
| Preconditions | Starting screen, instrument/protocol/run identity, readiness and relevant interlocks |
| Actions | Named controls and expected screen transitions; known confirmation behavior |
| Success | Fresh observable evidence and precisely what it proves |
| Failure | Missing/disabled/ambiguous controls, unexpected dialogs, terminal errors, partial results |
| Timing and recovery | Bounded waits, possible side effects after timeout, reconciliation and retry rules |

Build operator-level commands such as `list_protocols`, `import_protocol`, `start_setup`, `select_robot`, `start_run`, and `get_run_status` from the explored steps. Document the chosen remote catalog separately from the inherited operations used internally.

Separate workflow stages when they have different effects. In the Opentrons example, importing a file is not proof of successful analysis; opening setup is not starting a run; selecting a robot and proceeding creates/uploads setup; observing Running is not proof of completion. Determine equivalent distinctions from the supplied procedure and observed application behavior.

## Implement the machine driver

Turn the user's description of one atomic task into one deterministic `@command` method in `driver.py`. The user can describe the intended outcome and the buttons to click, fields to fill, or text to type. Use supplied screenshots, live observations, and any available manual to resolve missing details; do not require the user to supply code or a formal specification.

1. Identify the task's starting state, variable inputs, ordered GUI steps, and observable completion condition. Keep the command focused on that task; do not append later workflow stages.
2. Inspect `capture_screenshot(include_elements=True)` to resolve the described controls to exact labels and roles. Ask only when the intended action or target remains ambiguous.
3. Encode the steps as ordinary Python calls to inherited helpers such as `click_element`, `set_value`, `type_text`, `press_key`, and `wait_for_element`. Use typed parameters for values that vary between calls. Keep these helpers internal; `capture_screenshot` remains the only low-level remote command.
4. Check the starting state, execute each input once, and wait for the expected state between steps. Return JSON-compatible evidence after a fresh, task-specific completion check. Raise on missing or ambiguous controls, unexpected dialogs, or timeout; do not guess another path or repeat an uncertain action.
5. Add a concise docstring describing inputs and what success proves. Test the sequence and its failure cases with mocked GUI observations. Preserve the template's connection and cleanup code.

For example, “Open Settings, enter the supplied name in Sample name, and click Save” becomes a `set_sample_name(name: str)` command that clicks Settings, waits for the field, sets its value, clicks Save once, and verifies that the supplied name was saved. Determine the actual selectors and save indicator from the app.

Follow the Opentrons pattern: the agent interprets the user's procedure while writing the driver; the resulting command runs a fixed sequence of low-level Python operations with explicit checks, without runtime AI decisions.

## Uncertain outcomes

After a timeout or lost response following input, inspect the current operation and instrument identity before deciding whether to retry. Do not automatically repeat imports or start actions. Reconnecting the edge does not establish that replaying an action is safe. Neither reviewed implementation supplies durable replay protection; add and test it only when the project's delivery/restart requirements need it, and do not claim it already exists.

## Validate and deliver

1. Run offline tests with fake backend responses. Cover the intended catalog, successful transitions, duplicate/disabled/missing selectors, stale captures, changed identity, malformed/partial data, known and unknown dialogs, timeout after input, and cleanup. Assert that an uncertain action dispatches at most once. Test restart/redelivery behavior if adding persistent recovery.
2. Both the template and Opentrons use `uv run python -m unittest discover -s tests`. Retain the template tests and add machine-specific fixtures and assertions. Offline passes establish logic against fixtures, not live GUI compatibility.
3. Run the driver on the application's interactive desktop. The reviewed MCP implementation supports Windows and Linux X11; verify display/session access and `cua-driver` availability. Preserve platform launchers and Windows UTF-8 initialization. Ordinary headless services/containers do not provide the required interactive session.
4. Verify desktop capture and read-only workflows before consequential operations. Check `puda machine info`, `state`, and `commands` against the intended machine and catalog. Use installed CLI help for command syntax and run lifecycle requirements.
5. Exercise physical operations only within the user's authorization and the procedure's actual prerequisites. Account for implicit actions: the Opentrons reference observed homing even in a comment-only protocol's run preview. Pause/cancel are not necessarily motion-free or equivalent to an emergency stop; establish consequences from available documentation, user instructions, and the current app.
6. Deliver the driver, configuration example, task/source notes, completed command contract, offline fixtures/tests, and a short account of live validation and remaining unknowns. Record actual app/backend versions. Preserve hardware interlocks and distinguish software status from independently verified physical completion.
