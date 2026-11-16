# Manual dashboard layout and URLs

## Layout and livestream

Prefer a **single-screen layout**: livestream and all controls visible together. Do not hide core controls in tabs unless explicitly requested.

- Put **Start** / **Complete** / **Reset** at the top.
- Put compact machine controls on the left and the camera on the right when screen width allows.

When Tailnet MagicDNS is enabled, use the machine's MagicDNS name for cross-machine/player URLs rather than a changing Tailnet IP. Discover it with `tailscale status --json` (`Self.DNSName` locally, or the target peer's `DNSName`) and remove its trailing dot.

Use the short MagicDNS hostname when it resolves for the operator, otherwise the full MagicDNS name:

```text
http://<machine-hostname>:<player-port>/<path>
http://<machine-hostname>.<tailnet>.ts.net:<player-port>/<path>
```

Embed the player URL in `st.iframe(...)` and optionally link its API endpoint. Verify the selected player URL returns HTTP 200 before sharing or embedding. A Tailnet IP is a fallback only when neither MagicDNS form is available.

### Dashboard URL

For a deployed manual-control dashboard, share its reachable MagicDNS hostname and Streamlit port:

```text
http://<machine-hostname>:<streamlit-port>/
```

Verify `http://<machine-hostname>:<streamlit-port>/_stcore/health` returns HTTP 200 before reporting it. **Example only:** the First dashboard currently uses `http://first:8501/`; do not hard-code First or port 8501 for another machine.
