# Proposal: remember the apartment

**Status:** not started. Written while building movement, so the movement code
leaves room for it.

Today Eva moves reactively: a command starts a movement, the range sensor stops
it before a wall. She has no idea where she is, where she has been, or what is
behind her. "Go to the kitchen" is not a command she could ever execute,
because nothing in the system knows what a kitchen is or where it might be.

This is the plan for changing that: a persistent occupancy map of the
apartment, a pose within it, and movement that consults both.

---

## What already helps

Three things were built with this in mind and do not need changing:

- **`sensor.range` is a topic, not a function call.** The obstacle reflex
  subscribes to it. A map builder is a second subscriber, and neither knows
  about the other.
- **One owner of the wheels.** Every movement goes through
  `MoveBaseHandler`, so odometry has exactly one place to observe what the
  base was asked to do.
- **The capability handshake decides the vocabulary.** A `navigate_to` action
  appears in the model's grammar only for a robot that declares it can
  localise. Robots without a map never get offered map-based commands, and
  nothing else has to know why.

## What is missing, in order of how much it hurts

### 1. Odometry — the blocker

A map needs to know where readings were taken from. Right now the robot knows
what it *asked* the wheels to do and nothing about what they did. Wheel slip,
carpet, a low battery — all of them make commanded motion and actual motion
diverge, and the error accumulates without bound.

**The current hardware cannot do this.** The parts list has no wheel encoders,
and dead reckoning from PWM duty cycle alone drifts unusably within a few
metres. One of these has to happen first:

| Option | Cost | Notes |
|---|---|---|
| **Wheel encoders** | ~€5 | Slotted-disc or hall pairs on the existing motors. Simplest and most accurate for a flat floor. Needs 2 free GPIOs and interrupt counting. **Recommended.** |
| **Visual odometry** | €0 more | The OV9281 is already in the parts list, and a global shutter is genuinely good for this — no rolling-shutter smear while turning. But it is a large amount of work and CPU on a Pi 4 that is already streaming audio. |
| **IMU dead reckoning** | ~€3 | An MPU-6050 gives heading well and position badly. Useful *alongside* encoders to correct turn angle; not a substitute. |

Recommendation: encoders for position, and revisit the camera later for
loop closure.

### 2. A map to put readings in

An occupancy grid — a 2D array of cells, each holding the log-odds that the
cell is occupied. Log-odds rather than probability so that repeated
observations are added rather than multiplied, which keeps the update cheap
and numerically stable.

- **Resolution:** 5 cm per cell. An apartment of 100 m² is 40 000 cells, a few
  hundred KB — nothing.
- **Update:** each range reading marks the cells along the beam as free and
  the cell at the end as occupied, weighted by the sensor's confidence.
- **The sensor's shape matters.** A US-100 has roughly a 15° cone, not a ray.
  Treating it as a ray writes walls that are not there. The beam model needs
  to spread the occupied update across the arc at that distance.

### 3. Somewhere to keep it

Persisted as a NumPy `.npz` on the Pi, written on a timer and on clean
shutdown, loaded at startup. Version the file with the resolution and origin so
a config change cannot silently corrupt an old map.

The map lives on the **robot**, not the server. It is needed for reflexes when
the network is down, it is specific to one robot's sensors, and it would
otherwise have to be re-uploaded on every reconnect.

### 4. Deciding where to go

Once there is a map and a pose, `navigate_to(x, y)` becomes possible: A* or
D* Lite over the grid, then a pure-pursuit controller emitting the same wheel
speeds `MoveBaseHandler` already takes.

Named places ("the kitchen") are a thin layer on top: a dictionary of labels to
coordinates, taught by driving Eva somewhere and saying "this is the kitchen".
That is a nice demo and cheap once the rest exists.

---

## The changes, concretely

**New on the robot:**

```
robot/mapping/occupancy_grid.py    the grid, its update rule, load and save
robot/mapping/pose.py              x, y, heading from encoder ticks
robot/mapping/beam_model.py        one range reading → cell updates
robot/sensors/wheel_encoder.py     GPIO edge counting, publishes sensor.odometry
robot/behaviors/map_builder.py     subscribes sensor.range + sensor.odometry
robot/navigation/planner.py        grid + goal → waypoints
robot/navigation/follower.py       waypoints → wheel speeds
```

**Changed:**

- `robot/config.py` — `MappingConfig` (resolution, map path, save interval),
  `EncoderConfig` (pins, ticks per revolution, wheel diameter, track width).
- `robot/actions/move_base_handler.py` — grows a velocity path the follower can
  drive, alongside the discrete commands. The discrete ones stay: "turn left"
  should not need a planner.
- `robot/runtime.py` — wire the new services.
- `server/actions.py` — `navigate_to(place)` and `where_are_you()`, both
  requiring a new `localisation` capability so they are only offered to a robot
  that has one.
- `robot/HARDWARE.md` — encoder wiring.

**Unchanged, deliberately:** the protocol envelope, the handshake, the obstacle
reflex, and everything about how speech becomes a command. A map makes commands
better; it does not change how they arrive.

## Plan

1. **Encoders and pose.** Wire them, count ticks, publish `sensor.odometry`.
   Done when driving a measured 2 m and reading back 2 m ± 10 cm, and a
   commanded 360° turn ends up facing the same way.
2. **The grid and the beam model, offline.** Build the map from a recorded
   drive rather than live — much easier to debug against a log than against a
   moving robot.
3. **Live mapping and persistence.** `map_builder` on the bus, saving and
   loading. Done when a map survives a restart and a second drive sharpens the
   first one's walls rather than smearing them.
4. **A map view in the debug dashboard.** The server already serves `/debug`
   over a telemetry socket; the map is another frame on it. Worth doing before
   the planner, because "why did it go there?" is unanswerable without seeing
   what it believed.
5. **Planner and follower.** A* over the grid, pure pursuit to drive it.
6. **`navigate_to` in the registry, behind the `localisation` capability.**
   Named places last, once the coordinates work.

## Risks

- **Drift is the whole problem.** Without loop closure the map degrades over
  long runs. Mitigation: keep sessions short at first, and treat the map as a
  hint for planning rather than ground truth. The obstacle reflex stays the
  authority on what is actually in front of Eva right now — a map should never
  be allowed to overrule a live sensor reading.
- **One forward-facing cone is a thin sensor for mapping.** It maps what Eva
  drove past, not what is around her. A second sensor either side, or slow
  rotation scans at waypoints, would fill it in considerably.
- **CPU.** The Pi is already streaming 16 kHz audio continuously. The grid
  update is cheap; the planner should run on demand, not on a loop.

## Not in scope here

Semantic mapping (rooms, objects, "the sofa") needs the camera and a vision
model, which is its own piece of work. The occupancy grid is the substrate that
would sit under it.
