# rtsp-server

Upload video files in a web panel. Each video is served as a looping, live RTSP stream.

- **Web panel** (FastAPI and vanilla JS) at `http://localhost:8020`. Use it to upload, rename, enable or disable, preview and delete streams.
- **RTSP server** ([MediaMTX](https://github.com/bluenviron/mediamtx)) at `rtsp://localhost:8556/<stream-name>`.
- Both run in containers via Docker Compose.

## Quick start

```sh
cp .env.example .env        # optional
docker compose up --build -d
open http://localhost:8020
```

Drop a video into the panel. When it shows **Ready**, play it:

```sh
ffplay -rtsp_transport tcp rtsp://localhost:8556/<stream-name>
# or VLC: Media → Open Network Stream
```

## How it works

```
 browser ──HTTP :8020──► panel ──control API :9997──► mediamtx ◄──RTSP :8556── clients
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
| `RTSP_PORT` | `8556` | RTSP port on the host |
| `HLS_PORT` | `8890` | HLS player port (the panel's **HLS** button) |
| `WEBRTC_PORT` | `8891` | WebRTC player and WHEP port (the panel's **Preview** button) |
| `WEBRTC_HOSTS` | `127.0.0.1` | Comma-separated IPs or hostnames that browsers use to reach WebRTC media |
| `PLAYBACK_PORT` | `8996` | Archive playback port (time-range requests) |
| `RECORD_RETENTION` | `6h` | How long archived video is kept before MediaMTX deletes it |
| `RECORD_SEGMENT_DURATION` | `10m` | Length of each recording segment on disk |
| `PANEL_USER` / `PANEL_PASSWORD` | empty | Turns on HTTP Basic auth for the panel when set |
| `MAX_UPLOAD_MB` | `4096` | Upload size limit |
| `TRANSCODE_CONCURRENCY` | `1` | Number of uploads converted in parallel |

RTSP over UDP uses ports `8000/udp` and `8001/udp`. Clients that have trouble with UDP through NAT can use TCP (`-rtsp_transport tcp`).

### WebRTC

Each stream can also be played in a browser over WebRTC, with sub-second latency:

- **Player page:** `http://<host>:8891/<stream-name>/`
- **WHEP endpoint:** `http://<host>:8891/<stream-name>/whep`, for embedding the stream in your own page or app.

WebRTC signalling runs over HTTP on `8891`. Media goes over `8190/udp`, or `8190/tcp` as a fallback. In Docker, MediaMTX can't discover the host's address on its own, so set `WEBRTC_HOSTS` to the address viewers use to reach this machine:

```sh
WEBRTC_HOSTS=192.168.1.50            # LAN
WEBRTC_HOSTS=stream.example.com      # public; open 8190/udp+tcp in the firewall
```

With the default (`127.0.0.1`), WebRTC only works in a browser running on the Docker host itself.

Browsers can't play AAC over WebRTC, so streams from files with AAC audio play **without sound** there. RTSP and HLS still carry the audio. Uploads with Opus audio keep their sound over WebRTC.

## API

| Method | Path | Notes |
|---|---|---|
| `GET` | `/api/videos` | Lists videos with their live state (ready, viewers) |
| `POST` | `/api/videos?filename=<name>[&stream_name=<name>]` | The raw file is the request body |
| `PATCH` | `/api/videos/{id}` | JSON body with any of: `stream_name`, `enabled`, `mode` (`on_demand` \| `always_on`), `archive` |
| `DELETE` | `/api/videos/{id}` | Stops the stream and deletes the file |
| `GET` | `/api/health` | Health check |

Upload with curl:

```sh
curl -X POST -T clip.mp4 -H 'Content-Type: application/octet-stream' \
  "http://localhost:8020/api/videos?filename=clip.mp4&stream_name=cam1"
```

## Archive (time-range playback)

Turn **Archive** on for a stream and the server records it, so a client can later ask for
any window of it rather than only the live edge. The panel shows the URL template to give
that client:

```
http://<host>:8996/get?path=<stream>&start={start}&duration={duration}
```

Substitute `{start}` with an RFC 3339 UTC instant and `{duration}` with whole seconds:

```sh
curl -o clip.mp4 \
  "http://localhost:8996/get?path=cam1&start=2026-09-26T07:45:10Z&duration=20"
```

`GET /list?path=<stream>` on the same port reports what is actually on disk, and the panel
shows the same thing under each archived stream ("2 segments · 13:15 → 13:17 · kept 6h").

**Archiving forces the stream always-on.** An on-demand stream only publishes while someone
is watching, so its recording would have a hole wherever nobody was. Switching an archived
stream back to on demand is refused with a 409; turn the archive off first.

**Recording is what fills disks.** One 2 Mbps stream is ~21 GB/day, thirty is ~648 GB/day.
`RECORD_RETENTION` defaults to a deliberately short **6h** — raise it once you know the
volume has room. Recordings live in their own `recordings` Docker volume, separate from
uploads, and `docker compose down -v` erases them.

> **Browsers cannot play H.265.** Uploads are remuxed rather than re-encoded when they are
> already H.264 **or H.265**, so an H.265 source is archived as H.265 — which Chrome and
> Firefox decode as a blank frame, live and archived alike. Measured: an HEVC stream yields
> 0 decoded frames, the same file in H.264 yields video. If the archive is for a browser,
> the source must be H.264.

## Security notes

- The MediaMTX control API is not exposed to the host.
- Only ffmpeg processes inside the MediaMTX container can publish streams.
- Anyone who can reach port 8556 can watch the streams. Firewall the port, or add RTSP credentials in `mediamtx/mediamtx.yml` (`authInternalUsers`), if that matters for you.
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
