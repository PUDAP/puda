# Manual UI layout and livestream

## Layout

Prefer a **single-screen layout**: livestream and all controls visible together. Put **Start** / **Complete** at the top and keep machine controls beside the camera when screen width allows. Do not hide core controls in tabs unless explicitly requested.

## Livestream URLs

Read livestreams from the fleet registry through machine info:

```bash
puda machine info <machine_id>
```

The machine's entry in the JSON `results` array has a `livestreams` array. Each item has `name`, `host`, `description`, and `urls` with `hls`, `webrtc`, `rtsp`, and `rtmp`. Embed `urls.hls` or `urls.webrtc` (browser player pages) and optionally link the other. An empty array means no stream is registered for that machine; register one with the **puda** skill's livestream setup rather than hard-coding a URL. Verify the selected player URL returns HTTP 200 before sharing or embedding.

## Deployed UI URL

Share the UI host's reachable MagicDNS hostname and port (e.g. `http://<machine-hostname>:<port>/`). Verify the framework's health or root endpoint returns HTTP 200 locally and through that URL before reporting it reachable. **Example only:** a Streamlit app exposes `/_stcore/health`; do not hard-code a host or port.
