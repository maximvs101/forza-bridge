# Forza Horizon telemetry bridge

Turns *Forza Horizon 6* telemetry into **OSC** and **WebSocket** streams, for
any software that speaks either — visuals, lighting, sound, streaming overlays.

It decodes the 92 fields of the game's "Data Out" packet, computes 20 more
already scaled for use, and rebroadcasts everything.

## Quick start

```bash
pip install -r requirements.txt
python gui.py
```

In the game: **Settings → HUD and Gameplay → Data Out**, enable it, enter the
machine's network address and port **5300**.

Command line, no interface:

```bash
python main.py --osc 127.0.0.1:7000 --ws-port 8765
```

`python-osc` and `websockets` are required; `pystray` and `Pillow` only add the
system-tray icon.

## The game's stream

One packet **per rendered frame**, so the rate follows the frame rate, not the
protocol: 30 Hz and 60 Hz measured while driving, 60 Hz when stationary.

Accepted sizes: 232 (sled), 323/324 (Horizon Dash — 324 is what FH6 sends),
339/340 (with tyre wear). Any other size is **refused and reported with its
size**, because a silent refusal looks exactly like "the game is not sending".

The game sends from the machine's network address, not from `127.0.0.1`, so the
bridge listens on `0.0.0.0`.

## OSC

One address per channel, prefixed `/forza/`. Several destinations at once:

```bash
python main.py --osc 127.0.0.1:7000 --osc 192.168.0.50:9000
```

IPv6 goes in brackets: `[::1]:7000`. An unreachable destination is reported
without stopping the others.

The vehicle name is sent on `/forza/car_name` as a **string**, and only when
the car changes. Some OSC receivers accept numbers only on their main input:
check yours has a way in for strings.

## WebSocket

```bash
python main.py --ws-port 8765
```

The **demo overlay is served on the same port**: <http://localhost:8765/>,
usable directly as an OBS browser source. The server listens on `127.0.0.1`;
`--ws-lan` opens it to the local network, which is deliberate — the stream
carries the vehicle position.

Per-client settings in the URL: `?full=1` (complete state every frame, nothing
to merge) and `?channels=speed_kmh,gear`. Same thing by JSON command:
`{"subscribe": [...]}`, `{"full": true}`.

Three message types: **hello** (channel schema, units, rate — nothing to
hard-code), **telemetry** (differential by default, complete state every 2 s),
**status** (every second, doubles as a heartbeat).

`status` carries two counters, not one: `packets_received` answers "is the game
sending?", `packets` answers "how many frames were forwarded". They differ when
`--only-racing` filters — and while it does, the interface still shows what the
game is sending, because the filter governs what is *sent*, not what is
*displayed*.

## Channels

**92 raw channels** plus **20 computed**. Raw channels are never replaced:
everything is added.

| Computed | From | Unit |
|---|---|---|
| `speed_kmh`, `speed_mph` | `speed` (m/s) | km/h, mph |
| `rpm_ratio` | rpm ÷ max rpm | 0-1 |
| `throttle`, `brake_pedal`, `clutch_pedal`, `handbrake_pedal` | 0-255 bytes | 0-1 |
| `steer_norm` | `steer` (-127..127) | -1..1 |
| `g_lateral`, `g_vertical`, `g_longitudinal` | accelerations (m/s²) | g |
| `yaw_deg`, `pitch_deg`, `roll_deg` | radians | degrees |
| `tire_temp_*_c` | °F | °C |
| `slip_max` | greatest of the 4 slips | normalised |
| `shifting` | `gear == 11` | 0/1 |

Bounded values map straight onto an opacity, a scale or a volume.
`--no-derived` turns them off. `tire_wear_*` exists only in 339-byte packets.

### Smoothing

```bash
python main.py --smooth "slip_max=0.15, g_lateral=0.15"
```

**Additive**: `slip_max_smooth` appears next to `slip_max`, which stays
untouched — a filter delays and clips extremes, and overwriting the raw value
would falsify the telemetry. Measured: 87 % less jitter on a noisy channel, 2 %
on an already clean one, extremes preserved in the raw channel. Meaningful
integers (gear, lap, vehicle id) are never smoothed.

### `gear` reports 11 while shifting

The game writes **11** into `gear` during a gear change — bursts of 130 to
400 ms, and every change passes through it (`3 → 11 → 4`, never `3 → 4`).

Established on 45 s of raw capture: in the 168 frames concerned, **only byte 319
changes** while its neighbours (`accel`, `brake`, `clutch`, `hand_brake`,
`steer`) stay put, which rules out a misalignment; the game's timestamp stays
strictly increasing and every burst sits between two *different* gears. One of
the two cars tested is a 5-speed, so 11 is not an eleventh gear.

The value is passed through untouched; the derived `shifting` channel carries
the flag. The test is `gear == 11`, not `gear > 10`: a threshold would silently
swallow any other unknown value.

## Interface

`python gui.py` — settings grouped by role, and a table of all 112 channels with
category, unit, live value and smoothing. Click the **Send** column to toggle a
channel; select rows to apply smoothing to several at once.

Settings that can be applied while running are applied immediately (WebSocket
on/off, "only while racing", computed channels); those that cannot are greyed
out rather than pretending. **Open overlay** says what is missing instead of
opening a dead page when the server is off. Closing the window hides the app in
the tray without stopping the bridge.

## Vehicle table

`car_ordinals.json` maps the identifier the game sends to a readable name.
Unknown cars show as "Unknown vehicle (ordinal N)" and are logged to
`car_ordinals_unknown.json`.

The list is **not mine and not official**: it is the community gist
["All Car Ordinal id's for Forza Horizon 6"](https://gist.github.com/HDR/0659d1717bc61504bf83750628963f4f)
by **HDR**, inverted here into ordinal → name. Corrections are worth sending
upstream too.

```bash
python tools/update_car_table.py           # preview the differences
python tools/update_car_table.py --write   # apply the merge
```

The update **merges**: local entries missing from the source are kept, since the
source is not official. `--remove` drops them explicitly.

## Tests

```bash
python -m unittest discover
```

348 tests, standard library only. They cover packet decoding, the catalogue,
computed channels, smoothing, OSC destinations, the bridge loop, the WebSocket
server, the interface and the overlay's own JavaScript (that one needs `node`,
and skips without it).

## Confirmations wanted

Three things were established on **one** machine and **one** game version. If
your stream differs, an issue would settle them.

- **Tyre wear at offsets 323/327/331/335** — never seen here (this machine's
  stream is 324 bytes, so the fields are absent). Offsets taken from
  [TheBanHammer/fh6-tel](https://github.com/TheBanHammer/fh6-tel). If your
  packets are 339/340 bytes, do `tire_wear_*` read as plausible 0-1 fractions?
- **`gear` = 11** — verified on two cars, both automatic, so `clutch` stayed 0
  throughout and could not corroborate. Does a manual-with-clutch setup show the
  same 11?
- **Packet sizes** — anything outside the accepted list is refused and reported
  with its size. If you see that warning, its size is exactly what is missing.

## License

MIT, see [LICENSE](LICENSE). One exception, not mine to license:
`car_ordinals.json` is derived from the gist credited above.

Comments and docstrings are in French, the author's working language; every
user-facing string is in English.
