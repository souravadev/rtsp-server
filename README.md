# rtsp-server

Upload video files in a web panel. Each video is served as a looping, live RTSP stream.

- **Web panel** (FastAPI and vanilla JS) at `http://localhost:8020`. Use it to upload, rename, enable or disable, preview and delete streams.
- **RTSP server** ([MediaMTX](https://github.com/bluenviron/mediamtx)) at `rtsp://localhost:8554/<stream-name>`.
- Both run in containers via Docker Compose.

## Quick start

```sh
cp .env.example .env        # optional
docker compose up --build -d
open http://localhost:8020
```

Drop a video into the panel. When it shows **Ready**, play it:

```sh
ffplay -rtsp_transport tcp rtsp://localhost:8554/<stream-name>
# or VLC: Media → Open Network Stream
```

## How it works

```
 browser ──HTTP :8090──► panel ──control API :9997──► mediamtx ◄──RTSP :8554── clients
                           │ writes                      │ spawns ffmpeg (reads)
                           └────────► [videos volume] ◄──┘
```

1. **Upload.** The file is streamed to disk. `ffprobe` checks it:
   - If it is already H.264/H.265 (4:2:0) with AAC/Opus audio (or no audio), it is remuxed to MP4. This is fast and keeps the original quality.
   - Otherwise it is transcoded once to H.264/AAC.
2. **Publish.** For each enabled video, the panel registers a MediaMTX path whose command is
   `ffmpeg -re -stream_loop -1 -i /videos/<id>.mp4 -c copy -f rtsp …`. Streaming therefore costs almost no CPU.
3. **Modes.**
   - *On demand* (the default): ffmpeg starts when the first client connects and stops 10s after the last one leaves.
   - *Always on*: the stream runs all the time, so clients join a stream that is already playing.
4. **Self-healing.** MediaMTX keeps API-created paths only in memory. The panel reconciles its database against MediaMTX every 15s and after every change, so paths come back after a MediaMTX restart.

## Configuration (`.env`)

| Variable | Default | Purpose |
|---|---|---|
| `PANEL_PORT` | `8020` | Web panel port on the host |
| `RTSP_PORT` | `8554` | RTSP port on the host |
| `HLS_PORT` | `8890` | HLS port used by the panel's Preview button |
| `PANEL_USER` / `PANEL_PASSWORD` | empty | Turns on HTTP Basic auth for the panel when set |
| `MAX_UPLOAD_MB` | `4096` | Upload size limit |
| `TRANSCODE_CONCURRENCY` | `1` | Number of uploads converted in parallel |

RTSP over UDP uses ports `8000/udp` and `8001/udp`. Clients that have trouble with UDP through NAT can use TCP (`-rtsp_transport tcp`).

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/videos` | Lists videos with their live state (ready, viewers) |
| `POST` | `/api/videos?filename=<name>[&stream_name=<name>]` | The raw file is the request body |
| `PATCH` | `/api/videos/{id}` | JSON body with any of: `stream_name`, `enabled`, `mode` (`on_demand` \| `always_on`) |
| `DELETE` | `/api/videos/{id}` | Stops the stream and deletes the file |
| `GET` | `/api/health` | Health check |

Upload with curl:

```sh
curl -X POST -T clip.mp4 -H 'Content-Type: application/octet-stream' \
  "http://localhost:8020/api/videos?filename=clip.mp4&stream_name=cam1"
```

## Security notes

- The MediaMTX control API is not exposed to the host.
- Only ffmpeg processes inside the MediaMTX container can publish streams.
- Anyone who can reach port 8554 can watch the streams. Firewall the port, or add RTSP credentials in `mediamtx/mediamtx.yml` (`authInternalUsers`), if that matters for you.
- Uploaded videos, pending uploads and the SQLite database live in the `videos` Docker volume. `docker compose down -v` erases them.

## Project layout

```
docker-compose.yml
mediamtx/mediamtx.yml       RTSP server config
panel/
  Dockerfile
  app/main.py               HTTP API + static UI
  app/media.py              ffprobe + remux/transcode jobs
  app/mediamtx.py           MediaMTX API client, path command
  app/reconciler.py         DB → MediaMTX sync loop
  app/db.py                 SQLite storage
  app/static/               Web UI
```
