# Transferable error catalog

| Symptom | Likely layer | First evidence | Safe response |
|---|---|---|---|
| Repository 404/403 | source access | `gh repo view`, `git ls-remote` | verify org/SSO/team access |
| CLI missing | host/PUDA | `command -v puda` | install official verified release |
| NATS works on host but not container | network/Compose | container TCP test | correct host address or intentional host networking |
| Healthy container, missing machine | edge readiness | logs and fresh discovery | inspect driver init/NATS/subscriptions, not healthcheck alone |
| Stale machine state | heartbeat/KV | timestamp age | inspect publisher, timer, network, and retained state |
| Import/package failure | packaging | image import and lockfile | copy/install all workspace packages; verify Python compatibility |
| bytes/string parser exception | driver | traceback and payload type | normalize payload type; add regression fixture |
| Protocol validates but command fails | live registry | `puda machine commands` | replace stale command; run only reviewed suffix |
| RUN_ID_MISMATCH | run lifecycle | edge run/state logs | inspect active run; recover without replaying uncertain actions |
| Motion says success but pose unchanged | driver/controller | independent measured pose | preserve responses/alarms; fix verification; do not retry blindly |
| Joint-limit/IK alarm | controller/kinematics | official alarm table | review branch/orientation and safe-height ordering |
| Gripper action reversed | hardware mapping | stationary observed test | correct polarity and regression; do not rerun transfer automatically |
| Alignment collision/near miss | labware | pose and clearance evidence | stop, retreat safely, recalibrate progressively |

Append newly proven errors with source, root cause status, fix, regression, and portability notes.
