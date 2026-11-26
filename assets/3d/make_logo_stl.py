"""Builds the 3D Clinora logo (a rounded tile with a raised medical cross) as an ASCII STL file.

GitHub shows .stl files, and ```stl blocks in Markdown, in an interactive 3D viewer you can rotate and zoom.
Run:  python3 assets/3d/make_logo_stl.py   ->  assets/3d/clinora-logo.stl
"""
import math
from pathlib import Path


def norm(a, b, c):
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    n = [u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0]]
    length = math.sqrt(sum(x * x for x in n)) or 1
    return [x / length for x in n]


def prism(poly, z0, z1):
    """Triangles of a convex polygon (counter-clockwise, seen from above) extruded from z0 to z1."""
    tris = []
    cx = sum(p[0] for p in poly) / len(poly)
    cy = sum(p[1] for p in poly) / len(poly)
    n = len(poly)
    for i in range(n):
        a, b = poly[i], poly[(i + 1) % n]
        tris.append(((cx, cy, z1), (a[0], a[1], z1), (b[0], b[1], z1)))        # top
        tris.append(((cx, cy, z0), (b[0], b[1], z0), (a[0], a[1], z0)))        # bottom
        tris.append(((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)))    # side
        tris.append(((a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)))
    return tris


def rounded_square(half, r, seg=8):
    pts = []
    for cx, cy, start in [(half - r, half - r, 0), (-half + r, half - r, 90), (-half + r, -half + r, 180), (half - r, -half + r, 270)]:
        for k in range(seg + 1):
            ang = math.radians(start + 90 * k / seg)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
    return pts


def rect(x0, y0, x1, y1):
    return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]


def cross(w, l, z0, z1):
    """One clean solid "plus" shape: a single outline for the walls, five rectangles for the top and bottom
    (no overlapping parts, so viewers draw it without flicker)."""
    h = w / 2
    outline = [(h, -l), (h, -h), (l, -h), (l, h), (h, h), (h, l), (-h, l), (-h, h), (-l, h), (-l, -h), (-h, -h), (-h, -l)]
    tris = []
    for i in range(len(outline)):
        a, b = outline[i], outline[(i + 1) % len(outline)]
        tris.append(((a[0], a[1], z0), (b[0], b[1], z0), (b[0], b[1], z1)))
        tris.append(((a[0], a[1], z0), (b[0], b[1], z1), (a[0], a[1], z1)))
    for x0, y0, x1, y1 in [(-h, -h, h, h), (-h, h, h, l), (-h, -l, h, -h), (h, -h, l, h), (-l, -h, -h, h)]:
        tris.append(((x0, y0, z1), (x1, y0, z1), (x1, y1, z1)))
        tris.append(((x0, y0, z1), (x1, y1, z1), (x0, y1, z1)))
        # no bottom faces: the cross sits sunk into the tile, so nothing overlaps or flickers
    return tris


def tilt(v, ax=-50, az=25):
    """Rotate a point so viewers that look straight at the model see it from a 3/4 angle."""
    x, y, z = v
    c, s = math.cos(math.radians(az)), math.sin(math.radians(az))
    x, y = x * c - y * s, x * s + y * c
    c, s = math.cos(math.radians(ax)), math.sin(math.radians(ax))
    y, z = y * c - z * s, y * s + z * c
    return (x, y, z)


def build():
    tris = []
    tris += prism(rounded_square(20, 7), 0, 3)          # the app-icon tile
    tris += cross(11, 15, 1.5, 14)                       # the raised medical cross, sunk 1.5 into the tile
    tris = [tuple(tilt(v) for v in tri) for tri in tris]   # open at a 3/4 angle in viewers
    lines = ["solid clinora_logo"]
    for a, b, c in tris:
        n = norm(a, b, c)
        lines.append(f"  facet normal {n[0]:.4f} {n[1]:.4f} {n[2]:.4f}")
        lines.append("    outer loop")
        for p in (a, b, c):
            lines.append(f"      vertex {p[0]:.3f} {p[1]:.3f} {p[2]:.3f}")
        lines.append("    endloop")
        lines.append("  endfacet")
    lines.append("endsolid clinora_logo")
    return "\n".join(lines) + "\n", len(tris)


if __name__ == "__main__":
    text, count = build()
    out = Path(__file__).with_name("clinora-logo.stl")
    out.write_text(text)
    print(f"wrote {out} ({count} triangles, {len(text) // 1024} KB)")
