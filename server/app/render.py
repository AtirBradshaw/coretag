"""SVG thermal trace for the report page.

Only numbers computed on the server go into this SVG, never text from the
agent, so it's safe to insert into the page as-is.
"""

W, H = 900, 260
PAD_L, PAD_R, PAD_T, PAD_B = 46, 46, 22, 30


def thermal_trace(points) -> str:
    pts = [p for p in (points or []) if isinstance(p.get("temp"), (int, float))]
    if len(pts) < 2:
        return ""

    ts = [p["t"] for p in pts]
    temps = [p["temp"] for p in pts]
    clocks = [p["core"] for p in pts if isinstance(p.get("core"), (int, float))]

    t0, t1 = min(ts), max(ts)
    tmin, tmax = min(temps) - 6, max(temps) + 6
    cmin, cmax = (min(clocks) * 0.92, max(clocks) * 1.04) if clocks else (0, 1)

    def x(t):
        return PAD_L + (t - t0) / max(t1 - t0, 1) * (W - PAD_L - PAD_R)

    def y_temp(v):
        return PAD_T + (1 - (v - tmin) / max(tmax - tmin, 1)) * (H - PAD_T - PAD_B)

    def y_clock(v):
        return PAD_T + (1 - (v - cmin) / max(cmax - cmin, 1)) * (H - PAD_T - PAD_B)

    temp_path = " ".join(f"{x(p['t']):.1f},{y_temp(p['temp']):.1f}" for p in pts)
    clock_path = " ".join(f"{x(p['t']):.1f},{y_clock(p['core']):.1f}"
                          for p in pts if isinstance(p.get("core"), (int, float)))

    bands, start = [], None
    for p in pts:
        if p.get("bad") and start is None:
            start = p["t"]
        elif not p.get("bad") and start is not None:
            bands.append((start, p["t"]))
            start = None
    if start is not None:
        bands.append((start, pts[-1]["t"]))
    band_svg = "".join(
        f'<rect class="band" x="{x(a):.1f}" y="{PAD_T}" '
        f'width="{max(x(b) - x(a), 2):.1f}" height="{H - PAD_T - PAD_B}"/>'
        for a, b in bands)

    grid = labels = ""
    g = int(tmin // 10 * 10) + 10
    while g < tmax:
        yy = y_temp(g)
        grid += f'<line class="grid" x1="{PAD_L}" y1="{yy:.1f}" x2="{W - PAD_R}" y2="{yy:.1f}"/>'
        labels += f'<text class="axis" x="{PAD_L - 8}" y="{yy + 3:.1f}" text-anchor="end">{g}°</text>'
        g += 10

    ticks = "".join(
        f'<text class="axis" x="{x(t0 + (t1 - t0) * f):.1f}" y="{H - 10}" '
        f'text-anchor="middle">{int((t1 - t0) * f)}s</text>'
        for f in (0, 0.25, 0.5, 0.75, 1.0))

    return f'''<svg viewBox="0 0 {W} {H}" role="img" aria-label="Temperature and core clock over the load test">
  <defs><pattern id="hatch" width="6" height="6" patternTransform="rotate(45)" patternUnits="userSpaceOnUse">
    <line x1="0" y1="0" x2="0" y2="6" stroke="var(--alarm)" stroke-width="1.4" opacity=".28"/></pattern></defs>
  {grid}{band_svg}
  <polyline class="pen-clock" points="{clock_path}"/>
  <polyline class="pen-temp" points="{temp_path}"/>
  {labels}{ticks}
</svg>'''
