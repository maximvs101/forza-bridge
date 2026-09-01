# Forza Horizon telemetry bridge

Turns *Forza Horizon 6* telemetry into interaction sources for any software
that speaks **OSC** or **WebSocket**: visual creation (TouchDesigner,
cables.gl, vvvv), lighting (QLC+, Chataigne), sound (SuperCollider, Pure Data,
Sonic Pi, VCV Rack), streaming overlays.

The bridge listens to the game's "Data Out" stream, decodes the 92 packet
fields, computes 20 more already scaled for use, and rebroadcasts everything.

## Quick start

```bash
pip install -r requirements.txt
python gui.py
```

In the game: **Settings → HUD and Gameplay → Data Out**, enable it, enter the
machine's network address and port **5300**.

Command line, no interface:

```bash
python main.py
```

## About the game's stream

The game sends **one packet per rendered frame**, so the rate follows the
frame rate rather than the protocol. Measured on the same machine: 30 Hz and
60 Hz while driving depending on load, 60 Hz when stationary.

The "Horizon Dash" format is **323 bytes**, plus a trailing byte on recent
packets — that is what FH6 sends today (**324**, measured over 2701 consecutive
packets). Also accepted: the "sled" format on its own (232), and **339/340
bytes**, which carry the four tyre-wear floats after the dash block.

Any other size is **refused, and counted**. The refusal is deliberate: a `>=`
test decoded any foreign 323-byte-or-longer datagram into nonsense floats that
went straight out over OSC. But a silent refusal is worse — the interface would
report "no packets from the game" while packets were arriving. So the bridge
reports the sizes it dropped, in the status bar, on the command line, and in
the WebSocket `status` frame:

```
Warning: 4 packet(s) of unsupported size (500 B, 331 B); expected [232, 323, 324, 339, 340]
```

The game sends from the machine's network address, not from `127.0.0.1`, so
the bridge listens on `0.0.0.0`.

## Outputs

### OSC

One address per channel, prefixed `/forza/` — `/forza/speed_kmh`,
`/forza/rpm_ratio`… Several destinations are possible, which lets you feed
multiple programs at once:

```bash
python main.py --osc 127.0.0.1:7000 --osc 192.168.0.50:9000
python main.py --osc "127.0.0.1:7000, 192.168.0.50:9000"
```

IPv6 addresses go in brackets: `[::1]:7000`. An unreachable destination is
reported in the status bar **without stopping the others** or the WebSocket
broadcast.

The vehicle name is sent on `/forza/car_name` as a string, and only when the
car changes. Not every receiver accepts a string on its main input: in
TouchDesigner you need an **OSC In DAT**, not an OSC In CHOP.

### WebSocket

```bash
python main.py --ws-port 8765
```

The **demo overlay is served on the same port**: <http://localhost:8765/> —
usable directly as an OBS browser source (transparent background).

The server listens on `127.0.0.1` by default. The stream carries the vehicle
position; `--ws-lan` opens it to the local network, which is a deliberate
choice.

**Per-client settings**, in the connection URL:

| Parameter | Effect |
|---|---|
| `?full=1` | complete state on every frame, nothing to merge |
| `?channels=speed_kmh,gear` | receive only these channels |

Or by JSON command after connecting: `{"subscribe": [...]}`,
`{"subscribe": "*"}`, `{"full": true}`.

Three message types:

- `hello` — channel schema, units, categories, rate, current vehicle. A client
  needs nothing hard-coded.
- `telemetry` — the measurements. **Differential** by default: only changed
  fields are sent, with a complete state every 2 s. A client with no
  accumulated state should ask for `?full=1`.
- `status` — every second, doubling as a heartbeat. `receiving: false` means
  no packet is arriving from the game; packets that arrive without changing
  anything (menu, stationary car) stay `true`.

## Channels

**92 raw channels** decoded from the packet, plus **20 computed channels**.
Raw channels are never replaced: everything is added.

Four of the raw ones — `tire_wear_fl/fr/rl/rr` — exist only in 339-byte
packets. Their offsets (323, 327, 331, 335) come from an independent FH6
parser, not from a measurement here: the stream measured on the development
machine is 324 bytes, so those fields are absent and their rows stay empty.
A wrong offset would show up as visibly absurd values rather than as quiet
corruption.

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
`--no-derived` turns them off.

### `gear` reports 11 while shifting

Measured on two different cars: the game sends `gear = 11` in bursts of 150 to
400 ms, and **every** gear change passes through it — `3 → 11 → 4`, never
`3 → 4`. Real gears each hold a coherent speed band (3rd: 82-140 km/h, 4th:
131-162 km/h); 11 spans all of them and holds none, which is the signature of
a transient, not a ratio. One of the two cars is a 5-speed, so 11 cannot be an
eleventh gear: it is the game's way of saying no gear is engaged.

Proven on 45 s of raw capture — 2701 packets, all 324 bytes, 168 of them at
`gear = 11` in 13 bursts. In those frames **only byte 319 changes**: its
neighbours (`accel`, `brake`, `clutch`, `hand_brake`, `steer`,
`normalized_driving_line`) stay put, which rules out a misalignment. The game's
own timestamp stays strictly increasing at 16 ms, `is_race_on` stays 1, and
every burst sits between two *different* gears (1→2, 2→3, 3→4, 4→3, 3→2, 2→1).
The offsets match an independent FH6 parser
([TheBanHammer/fh6-tel](https://github.com/TheBanHammer/fh6-tel)) field for
field. Turn 10 does not document the value, so "no gear engaged" is an
observation, not an official name.

The value is passed through untouched, like every other raw field; the derived
`shifting` channel carries the flag instead. The test is `gear == 11`, not
`gear > 10`: a threshold would silently swallow any other unknown value, while
strict equality leaves it visible in `gear`.

### Smoothing

Telemetry is noisy. Smoothing is set per channel, as a time constant in
seconds:

```bash
python main.py --smooth "slip_max=0.15, g_lateral=0.15"
```

It is **additive**: `slip_max_smooth` appears next to `slip_max`, which stays
untouched. A filter delays and clips extremes — overwriting the raw value
would falsify the telemetry for anyone analysing it. Measured on real data:
60 to 75 % less jitter on noisy channels, extremes preserved in the raw one.

Meaningful integers (gear, lap number, vehicle identifier) are never
smoothed: averaging two gears would give 2.7.

## Graphical interface

`python gui.py`

Settings are grouped by role — **Input**, **OSC output**, **WebSocket
output** — rather than stacked in one block.

The channel table lists all 112 channels with their category, unit, live
value and smoothing. Clicking the **Send** column toggles a channel; the rest
of the row selects it, so several channels can be picked at once (Space
toggles the selection). **Filter** plus the **Filtered** button is the usual
gesture: type `tire`, then send everything shown.

Smoothing applies to the selection: pick rows, type a duration, press **Apply
to selection**. Channels that must not be smoothed are named in the status
bar rather than silently skipped.

Settings that can be applied while the bridge runs are applied immediately:
the WebSocket **Enabled** box really starts and stops the server, and **Only
while racing** and **Computed channels** take effect on the next packet. The
ones that cannot — the Forza UDP port, the OSC destinations, and the WebSocket
port, rate and scope — are **greyed out** while they would have no effect.
An active control that does nothing is the interface lying to you.

A colour-coded state indicator sits in the status bar and in the system tray.
Closing the window hides the app in the tray without stopping the bridge.
Settings are saved to `config.json`.

The window sizes itself from what its content actually measures, and cannot be
shrunk below that. A hard-coded size only holds for the font and display
scaling of the machine it was measured on: it truncated labels and pushed the
status bar out of frame.

## TouchDesigner

`touchdesigner/` holds two builder scripts, to paste into a **Text DAT**
(Python) and run once:

- `build_forza_bridge_component.py` — creates a `forza_bridge` component with
  a configured OSC In CHOP (`Strip Prefix Segments = 1`, so `/forza/speed`
  becomes the `speed` channel), a Null CHOP output and the channel table.
  Saved as a reusable `.tox`.
- `build_forza_dashboard.py` — basic dashboard: speed, rpm, gear, G-meter.
  Run it **inside** the component.

## cables.gl

`cables/build_cables_patch.py` generates a complete `.cables` patch wired to
the bridge, showing vehicle, speed and rpm in a sidebar.

```bash
python cables/build_cables_patch.py --template path/to/a_patch.cables
```

`--template` reuses the local identity and software version of an existing
patch, which avoids format mismatches. Open it with **File → Open patch**:
drag and drop goes to the asset uploader and fails.

The patch URL carries `?full=1`, because cables handles each message in
isolation: in differential mode a static field would arrive empty.

## Vehicle table

`car_ordinals.json` maps the numeric identifier the game sends to a readable
name. It comes from a community list, so it is frozen: cars added by game
updates show as "Unknown vehicle (ordinal N)", and those ordinals are logged
to `car_ordinals_unknown.json`.

The list is **not mine and not official**: it is the community gist
["All Car Ordinal id's for Forza Horizon 6"](https://gist.github.com/HDR/0659d1717bc61504bf83750628963f4f)
by **HDR**, inverted here from name → ordinal into ordinal → name. Credit goes
there; corrections are worth sending upstream as well as here. That is also
why the update merges rather than replaces (see below).

```bash
python tools/update_car_table.py           # preview the differences
python tools/update_car_table.py --write   # apply the merge
```

The update **merges**: local entries missing from the source are kept, since
the source is not official. `--remove` removes them explicitly. Renames
coming from the source are applied, and printed before writing — so a stale
source can revert a local name correction.

## Tests

```bash
python -m unittest discover -v
```

The tests themselves only use the standard library, but they import the
project's modules, so `python-osc` and `websockets` must be installed (see
`requirements.txt`). They cover packet decoding, the catalogue, computed
channels, smoothing, OSC destinations, the bridge loop, the WebSocket server
and the HTTP service.

Every test that protects a fix carries a comment naming the defect it keeps
from coming back. Several are **counter-checks**: they verify that turning the
tested option off restores the old behaviour, without which the main test
would pass even if the feature did nothing.

Two of them guard things a functional test would never notice:

- `test_langue_affichee.py` — every user-facing string must be in English.
  Long messages are screened for French markers; short labels and units are
  checked against a closed vocabulary, because a near-cognate ("Recommande"
  for "Recommended") slips through any word-spotting. Verified by mutation.
- `test_gui_layout.py` — the window must be at least as large as its content
  demands, and `minsize` must cover it too. It checks the *relationship*, not
  a hard-coded size: the hard-coded size was the defect.
- `test_gui_reglages_a_chaud.py` — a checkbox that changes something must
  really change it, and one that cannot must be greyed out. It also asserts
  the widgets carry a `command` at all: a checkbox wired to nothing compiles,
  runs, and passes every functional test while doing nothing. Some cases drive
  the widget through `invoke()` — the click path — rather than calling the
  handler, and one uses a **real** `Bridge` rather than a fake, because a fake
  cannot notice a missing wiring.
- `test_sources_compilent.py` — every source file must **compile**, and each
  command-line tool must answer `--help`. `ast.parse` does not enforce
  `from __future__` placement, so the language check happily read a tool that
  no longer started; nothing imported it, so nothing noticed.
- `test_update_car_table.py` — the maintenance tool, the only module that can
  destroy curated data. Covers the merge, the atomic write, `--remove`, and
  malformed sources: an empty or broken source must leave the table untouched.
- `test_overlay.py` + `overlay_harness.mjs` — the overlay's own JavaScript,
  loaded from the shipped file into a `vm` context with a stubbed DOM,
  WebSocket and clock. It covers the differential merge, the status
  precedence, gauge clamping and malformed frames. A counter-check breaks a
  string in `overlay.html` and requires the harness to fail, proving it reads
  the real file. Needs `node`; the test skips without it.

## Layout

| File | Role |
|---|---|
| `forza_telemetry.py` | UDP packet decoding |
| `channel_catalog.py` | categories, units, default selection |
| `derived_channels.py` | computed channels |
| `smoothing.py` | additive time-based smoothing |
| `osc_targets.py` | OSC destination parsing and formatting |
| `car_lookup.py` | ordinal → vehicle, classes, drivetrains |
| `bridge.py` | receive loop → OSC + WebSocket |
| `ws_server.py` | WebSocket server (differential, subscriptions, status) |
| `http_assets.py` | overlay served on the WebSocket port |
| `main.py` / `gui.py` | command line / interface |
| `tray.py` | system tray icon |
| `web/overlay.html` | demo overlay |

Comments and docstrings are in French, the author's working language; every
user-facing string is in English.

## Dependencies

`python-osc` and `websockets` are required. `pystray` and `Pillow` are only
used for the tray icon: without them the interface stays an ordinary window.

## Confirmations wanted

Three things here were established by measurement on **one** machine and
**one** game version. If your stream differs, an issue would settle them —
they are the only claims in this README that are not backed by data taken
here.

- **Tyre wear at offsets 323/327/331/335.** Never seen: this machine's stream
  is 324 bytes, so those fields are absent. The offsets come from
  [TheBanHammer/fh6-tel](https://github.com/TheBanHammer/fh6-tel). If your
  packets are 339 or 340 bytes, do `tire_wear_*` read as plausible 0-1
  fractions? Anything else means the offsets are wrong.
- **`gear` = 11 while shifting.** Verified on two cars, both with automatic
  transmission — `clutch` stayed 0 throughout, so the clutch byte could not
  corroborate it. Does a manual-with-clutch setup show the same 11, and does
  `clutch` move during those frames?
- **Packet sizes.** 232, 323, 324, 339 and 340 are accepted; anything else is
  refused **and reported** with its size. If you see that warning, the size it
  names is exactly what is missing here.

## License

MIT, see [LICENSE](LICENSE).

One exception, and it is not mine to license: `car_ordinals.json` is derived
from the community gist credited under [Vehicle table](#vehicle-table). It is
included so the tool works out of the box; if its author objects, it can be
fetched at first run instead — `tools/update_car_table.py` already does
exactly that.
