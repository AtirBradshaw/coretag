"""Built-in GPU load test.

Renders dense arithmetic offscreen with OpenGL (moderngl). Nothing is drawn
on screen and nothing is written to the card. Then it records the card's
own sensors every 2 seconds while the load runs.

The agent records RAW samples only. Peak, average, "throttled" and every
other judgement is computed by the server from these samples.
"""

import time

from .collectors.gpu_nvidia import read_sample
from .util import safe

# Dense fused-multiply-add chains on vec4s saturate the FP32 pipeline, which
# is what draws power. A few transcendentals stop the compiler folding the loop.
FRAGMENT_SHADER = """
#version 330
out vec4 fragColor;
uniform float t;
uniform int iters;
void main() {
    vec2 uv = gl_FragCoord.xy * 0.0021;
    vec4 a = vec4(uv, uv.x + t, uv.y - t);
    vec4 b = vec4(0.7071, 0.5412, 0.3827, 0.9239);
    vec4 c = vec4(uv.y, uv.x, t * 0.01, 1.0);
    vec4 d = vec4(0.3, 0.6, 0.9, 0.2);
    for (int i = 0; i < iters; i++) {
        a = a * b + c;  c = c * d + a;  b = b * a + d;  d = d * c + b;
        a = fract(a * 1.0007); b = fract(b * 1.0003);
        c = fract(c * 1.0011); d = fract(d * 1.0005);
        a += vec4(dot(b, c), dot(c, d), dot(d, a), dot(a, b)) * 0.01;
        b -= vec4(dot(a, d), dot(b, a), dot(c, b), dot(d, c)) * 0.01;
        if ((i & 31) == 0) { a += sin(a * 3.1) * 0.02; c += cos(c * 2.7) * 0.02; }
    }
    fragColor = fract(a + b + c + d);
}
"""

VERTEX_SHADER = """
#version 330
in vec2 pos;
void main() { gl_Position = vec4(pos, 0.0, 1.0); }
"""

SAMPLE_INTERVAL_S = 2.0
MAX_ITERS = 20000

# Safety: stop loading the card if it gets this hot, or if its own hardware
# protection keeps kicking in. The card protects itself anyway; this makes
# sure Coretag never keeps pushing a card that is already in trouble.
ABORT_TEMP_C = 93
ABORT_HW_SLOWDOWN_SAMPLES = 5
HW_SLOWDOWN_BITS = 8 | 64 | 128   # hw_slowdown, hw_thermal, hw_power_brake


def _load_worker(size, batch, iters_val, frames_val, stop_evt, msgs):
    """The GPU load, running in its OWN process.

    It used to be a thread, but waiting on the GPU (ctx.finish) holds
    Python's global lock, which starved the sensor-reading loop: samples
    arrived 5-12 s apart instead of every 2 s. A separate process can't
    block the readings, and if the graphics driver misbehaves it takes down
    only this worker, not the agent.
    """
    try:
        import moderngl
        import numpy as np

        ctx = moderngl.create_standalone_context()
        # Which chip did Windows give us? On laptops this can be the
        # built-in graphics instead of the NVIDIA card.
        renderer = str(ctx.info.get("GL_RENDERER", ""))
        prog = ctx.program(vertex_shader=VERTEX_SHADER, fragment_shader=FRAGMENT_SHADER)
        vbo = ctx.buffer(np.array([-1, -1, 3, -1, -1, 3], dtype="f4").tobytes())
        vao = ctx.simple_vertex_array(prog, vbo, "pos")
        tex = ctx.texture((size, size), 4)
        fbo = ctx.framebuffer(color_attachments=[tex])
        fbo.use()
    except Exception as e:
        msgs.put(("error", f"{type(e).__name__}: {e}"))
        return

    msgs.put(("ready", renderer))
    try:
        # calibration: a load that saturates a GTX 1060 idles an RTX 4090.
        # Scale until one batch takes ~60 ms.
        prog["t"].value = 0.0
        for _ in range(10):
            prog["iters"].value = iters_val.value
            t0 = time.perf_counter()
            for _ in range(batch):
                vao.render()
            ctx.finish()
            dt = time.perf_counter() - t0
            with iters_val.get_lock():
                if dt < 0.012:
                    iters_val.value = min(iters_val.value * 4, MAX_ITERS)
                elif dt < 0.045:
                    iters_val.value = min(int(iters_val.value * 1.7), MAX_ITERS)
                elif dt > 0.130:
                    iters_val.value = max(int(iters_val.value * 0.6), 32)
                else:
                    break
        msgs.put(("calibrated", iters_val.value))

        start = time.perf_counter()
        while not stop_evt.is_set():
            prog["t"].value = time.perf_counter() - start
            prog["iters"].value = iters_val.value
            for _ in range(batch):
                vao.render()
            ctx.finish()          # queue a batch, then sync, so the GPU never waits
            with frames_val.get_lock():
                frames_val.value += batch
    except Exception as e:
        msgs.put(("error", f"{type(e).__name__}: {e}"))
    finally:
        for obj in (fbo, tex, vbo, ctx):
            safe(obj.release)


class GPULoad:
    """Background GPU load in a separate process. Start it, sample while it
    runs, stop it."""

    def __init__(self, size=2048, iters=256, batch=4):
        import multiprocessing as mp
        self._mp = mp.get_context("spawn")
        self._iters = self._mp.Value("i", iters)
        self._frames = self._mp.Value("q", 0)
        self._stop = self._mp.Event()
        self._msgs = self._mp.Queue()
        self._proc = None
        self.size, self.batch = size, batch
        self.available = False
        self.error = None
        self.renderer = None
        self.calibrated_iters = None

    @property
    def iters(self):
        return self._iters.value

    @property
    def frames(self):
        return self._frames.value

    def bump(self, factor=1.7):
        with self._iters.get_lock():
            self._iters.value = min(int(self._iters.value * factor), MAX_ITERS)

    def _drain(self):
        import queue
        while True:
            try:
                kind, val = self._msgs.get_nowait()
            except (queue.Empty, OSError, EOFError):
                return
            if kind == "calibrated":
                self.calibrated_iters = val
            elif kind == "error":
                self.error = val

    def start(self) -> bool:
        self._proc = self._mp.Process(
            target=_load_worker, daemon=True,
            args=(self.size, self.batch, self._iters, self._frames, self._stop, self._msgs))
        self._proc.start()
        try:
            kind, val = self._msgs.get(timeout=30)
        except Exception:
            self.error = "the load process didn't start"
            self.stop()
            return False
        if kind == "ready":
            self.available, self.renderer = True, val
        else:
            self.error = val
        return self.available

    def stop(self):
        self._stop.set()
        if self._proc:
            self._proc.join(timeout=10)
            if self._proc.is_alive():
                self._proc.terminate()
        self._drain()


def _live_logger(path):
    """Write each sample to disk the instant it's taken (one JSON line each),
    flushed to the drive. If the PC loses power mid-test, the readings right
    before the shutdown survive, which helps diagnose the cause."""
    if not path:
        return lambda rec: None
    import json
    import os
    f = open(path, "a", encoding="utf-8")

    def write(rec):
        f.write(json.dumps(rec) + "\n")
        f.flush()
        safe(lambda: os.fsync(f.fileno()))
    return write


def run_load_test(duration_s=300, progress=print, self_load=True, live_log=None):
    """Load the GPU(s) and record every NVIDIA card's sensors every 2 s.

    Returns {uuid: load_test_dict} so each card's recording can be attached
    to that card in the report.
    """
    import pynvml
    log = _live_logger(live_log)
    pynvml.nvmlInit()
    load, abort_reason, bumps = None, None, 0
    try:
        handles = []
        for i in range(pynvml.nvmlDeviceGetCount()):
            h = pynvml.nvmlDeviceGetHandleByIndex(i)
            uuid = safe(lambda: pynvml.nvmlDeviceGetUUID(h))
            uuid = uuid.decode() if isinstance(uuid, bytes) else uuid
            limit = safe(lambda: pynvml.nvmlDeviceGetEnforcedPowerLimit(h) / 1000.0)
            handles.append((uuid, h, limit))
        if not handles:
            return {}

        load = None
        if self_load:
            load = GPULoad()
            if load.start():
                progress(f"  Load generator running on: {load.renderer}")
                if "nvidia" not in (load.renderer or "").lower():
                    progress("  ! Windows gave the load to a different graphics chip.")
                    progress("    On a laptop: Settings > System > Display > Graphics,")
                    progress("    add Python, choose 'High performance', then run again.")
            else:
                progress(f"  Couldn't start the built-in load ({load.error}).")
                progress("  Start a game or benchmark now instead.")
                load = None

        recordings = {u: [] for u, _, _ in handles}
        start = time.monotonic()
        tick, next_check, bumps, last_print = 0, 15.0, 0, -30.0
        main_uuid, main_h, main_limit = handles[0]
        abort_reason, hw_slow_streak = None, 0

        while abort_reason is None:
            target = start + tick * SAMPLE_INTERVAL_S
            delay = target - time.monotonic()
            if delay > 0:
                time.sleep(delay)
            elapsed = time.monotonic() - start
            if elapsed > duration_s:
                break
            for uuid, h, _ in handles:
                s = read_sample(pynvml, h)
                s["t"] = round(elapsed, 2)
                recordings[uuid].append(s)
                log({"uuid": uuid, "iters": load.iters if load else None, **s})
                temp, mask = s.get("temp_c"), s.get("throttle_mask") or 0
                if isinstance(temp, (int, float)) and temp >= ABORT_TEMP_C:
                    abort_reason = f"temperature reached {temp} C"
                if mask & HW_SLOWDOWN_BITS:
                    hw_slow_streak += 1
                    if hw_slow_streak >= ABORT_HW_SLOWDOWN_SAMPLES:
                        abort_reason = "the card's hardware protection kept slowing it down"
                else:
                    hw_slow_streak = 0
            tick += 1
            if abort_reason:
                progress(f"  SAFETY STOP: {abort_reason}. Load removed.")
                break

            # a load that leaves the card at 60% of its power budget would hide the
            # very faults this test looks for: push until it's really working
            if load and main_limit and elapsed >= next_check and bumps < 5:
                last5 = recordings[main_uuid][-5:]
                recent = [s["power_w"] for s in last5 if isinstance(s.get("power_w"), (int, float))]
                busy = [s["util_pct"] for s in last5 if isinstance(s.get("util_pct"), (int, float))]
                fully_busy = bool(busy) and min(busy) >= 97
                if recent:
                    frac = (sum(recent) / len(recent)) / main_limit
                    if fully_busy and frac < 0.88:
                        # Already 100% busy: more work per frame can't add power, it only
                        # makes frames longer. Some cards simply draw less on this workload.
                        progress(f"  (card fully busy at {frac * 100:.0f}% of its "
                                 f"{main_limit:.0f} W limit; holding load steady)")
                        next_check = float("inf")
                    elif frac < 0.88:
                        load.bump()
                        bumps += 1
                        progress(f"  (raising load: card at {frac * 100:.0f}% of its "
                                 f"{main_limit:.0f} W limit)")
                        next_check = elapsed + 12.0
                    else:
                        next_check = float("inf")

            if elapsed - last_print >= 30:
                last_print = elapsed
                s = recordings[main_uuid][-1]
                left = max(0, int(duration_s - elapsed))
                progress(f"  {int(elapsed):>3}s  {s.get('temp_c')} C  {s.get('core_mhz')} MHz  "
                         f"{s.get('power_w')} W  {s.get('util_pct')}% busy   ({left}s left)")
    finally:
        if load:
            load.stop()
        safe(pynvml.nvmlShutdown)

    meta = {
        "interval_s": SAMPLE_INTERVAL_S,
        "load_source": "coretag_builtin" if load else "external",
        "aborted": abort_reason,
        "renderer": load.renderer if load else None,
        "generator": ({"calibrated_iters": load.calibrated_iters, "final_iters": load.iters,
                       "bumps": bumps, "frames": load.frames, "error": load.error}
                      if load else None),
    }
    return {u: {**meta, "samples": recordings[u]} for u in recordings}
