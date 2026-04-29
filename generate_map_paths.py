#!/usr/bin/env python3
"""
generate_map_paths.py
---------------------
Generates accurate US state SVG paths + label centroids for the storm app.
Uses the same us-atlas TopoJSON that the browser would have loaded.

Run from your project folder:
    cd /Users/stevejaye/Documents/vibe_apps/SevereStorm_Comparison
    pip install requests topojson numpy
    python generate_map_paths.py

Outputs:
    map_paths.js  — paste this into storm-comparator.jsx to replace the
                    USMap component with a static embedded version
"""

import json, math, requests, os

OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))

# ── Download TopoJSON ──────────────────────────────────────────────────────────
print("Downloading US states TopoJSON...")
url = "https://cdn.jsdelivr.net/npm/us-atlas@3/states-10m.json"
topo = requests.get(url, timeout=30).json()
print("  Done.")

# ── Minimal TopoJSON → GeoJSON conversion ─────────────────────────────────────
def decode_arc(arc, scale, translate):
    """Decode a single TopoJSON arc into absolute [x,y] coordinates."""
    pts = []
    x, y = 0, 0
    for dx, dy in arc:
        x += dx
        y += dy
        pts.append([x * scale[0] + translate[0], x * scale[1] + translate[1]])
        # fix: proper separate x/y
    # redo properly
    pts = []
    x, y = 0, 0
    for dp in arc:
        x += dp[0]
        y += dp[1]
        pts.append([x * scale[0] + translate[0], y * scale[1] + translate[1]])
    return pts

def stitch_rings(arcs_idx, all_arcs, scale, translate):
    """Convert TopoJSON arc indices to a list of coordinate rings."""
    rings = []
    for ring_idxs in arcs_idx:
        ring = []
        for idx in ring_idxs:
            if idx >= 0:
                pts = decode_arc(all_arcs[idx], scale, translate)
            else:
                pts = decode_arc(all_arcs[~idx], scale, translate)[::-1]
            if ring and ring[-1] == pts[0]:
                ring.extend(pts[1:])
            else:
                ring.extend(pts)
        rings.append(ring)
    return rings

transform = topo.get("transform", {"scale": [1,1], "translate": [0,0]})
scale = transform["scale"]
translate = transform["translate"]
all_arcs = topo["arcs"]

# ── Albers USA projection (matches d3.geoAlbersUsa) ───────────────────────────
# Parameters from D3 source for geoAlbersUsa().scale(1300).translate([487.5, 305])
# We use two conic equal-area projections + Hawaii/Alaska insets

def to_radians(deg):
    return deg * math.pi / 180

def albers_conic(phi0, phi1, lam0, phi_origin, x0, y0, k=1300):
    """Albers equal-area conic projection."""
    phi0r = to_radians(phi0)
    phi1r = to_radians(phi1)
    phi_or = to_radians(phi_origin)
    lam0r = to_radians(lam0)

    n = (math.sin(phi0r) + math.sin(phi1r)) / 2
    C = math.cos(phi0r)**2 + 2*n*math.sin(phi0r)
    rho0 = math.sqrt(C - 2*n*math.sin(phi_or)) / n

    def project(lon, lat):
        lam = to_radians(lon)
        phi = to_radians(lat)
        rho = math.sqrt(max(0, C - 2*n*math.sin(phi))) / n
        theta = n * (lam - lam0r)
        x = k * rho * math.sin(theta) + x0
        y = k * (rho0 - rho * math.cos(theta)) + y0
        return x, y

    return project

# Lower 48
lower48 = albers_conic(29.5, 45.5, -96, 37.5, 487.5, 305)
# Alaska inset
alaska   = albers_conic(55, 65, -154, 50, 122, 490, k=375)
# Hawaii inset
hawaii   = albers_conic(8, 18, -157, 20.9, 204, 490, k=1300)

FIPS_TO_ABBR = {
    "01":"AL","04":"AZ","05":"AR","06":"CA","08":"CO","09":"CT","10":"DE",
    "12":"FL","13":"GA","16":"ID","17":"IL","18":"IN","19":"IA","20":"KS","21":"KY",
    "22":"LA","23":"ME","24":"MD","25":"MA","26":"MI","27":"MN","28":"MS","29":"MO",
    "30":"MT","31":"NE","32":"NV","33":"NH","34":"NJ","35":"NM","36":"NY","37":"NC",
    "38":"ND","39":"OH","40":"OK","41":"OR","42":"PA","44":"RI","45":"SC","46":"SD",
    "47":"TN","48":"TX","49":"UT","50":"VT","51":"VA","53":"WA","54":"WV","55":"WI",
    "56":"WY","02":"AK","15":"HI"
}

APP_STATES = {
    "AL","AR","AZ","CA","CO","FL","GA","IA","ID","IL","IN","KS","KY",
    "LA","MA","MD","MI","MN","MO","MS","MT","NC","ND","NE","NJ","NM",
    "NV","NY","OH","OK","OR","PA","SC","SD","TN","TX","VA","WA","WI","WV","WY",
    "CT","DE","ME","NH","RI","VT"
}

def get_proj(abbr):
    if abbr == "AK": return alaska
    if abbr == "HI": return hawaii
    return lower48

def rings_to_svg_path(rings, proj):
    parts = []
    for ring in rings:
        if len(ring) < 2:
            continue
        coords = []
        for lon, lat in ring:
            x, y = proj(lon, lat)
            coords.append((round(x, 1), round(y, 1)))
        d = f"M {coords[0][0]},{coords[0][1]}"
        for x, y in coords[1:]:
            d += f" L {x},{y}"
        d += " Z"
        parts.append(d)
    return " ".join(parts)

def centroid_of_rings(rings, proj):
    """Approximate centroid of the largest ring."""
    best = max(rings, key=len) if rings else []
    if not best:
        return None, None
    xs, ys = [], []
    for lon, lat in best:
        x, y = proj(lon, lat)
        xs.append(x)
        ys.append(y)
    return round(sum(xs)/len(xs), 1), round(sum(ys)/len(ys), 1)

# ── Process each state ─────────────────────────────────────────────────────────
print("Processing states...")
results = {}

for feature in topo["objects"]["states"]["geometries"]:
    fips = str(feature["id"]).zfill(2)
    abbr = FIPS_TO_ABBR.get(fips)
    if not abbr or abbr not in APP_STATES:
        continue

    proj = get_proj(abbr)
    geo_type = feature["type"]

    if geo_type == "Polygon":
        rings = stitch_rings(feature["arcs"], all_arcs, scale, translate)
        path = rings_to_svg_path(rings, proj)
        cx, cy = centroid_of_rings(rings, proj)
    elif geo_type == "MultiPolygon":
        all_rings = []
        for poly_arcs in feature["arcs"]:
            all_rings.extend(stitch_rings(poly_arcs, all_arcs, scale, translate))
        path = rings_to_svg_path(all_rings, proj)
        # centroid of largest polygon
        best_poly = max(feature["arcs"], key=lambda p: len(p[0]) if p else 0)
        best_rings = stitch_rings(best_poly, all_arcs, scale, translate)
        cx, cy = centroid_of_rings(best_rings, proj)
    else:
        continue

    results[abbr] = {"path": path, "cx": cx, "cy": cy}
    print(f"  {abbr}: cx={cx}, cy={cy}")

# ── Write JS output ────────────────────────────────────────────────────────────
lines = [
    "// AUTO-GENERATED by generate_map_paths.py",
    "// Accurate Albers USA projection — viewBox 0 0 975 610",
    "",
    "export const STATE_PATHS = {"
]
for abbr, v in sorted(results.items()):
    lines.append(f'  {abbr}: {{ d: "{v["path"]}", cx: {v["cx"]}, cy: {v["cy"]} }},')
lines.append("};")

out_path = os.path.join(OUTPUT_DIR, "map_paths.js")
with open(out_path, "w") as f:
    f.write("\n".join(lines))

print(f"\nDone! Written to {out_path}")
print("Upload map_paths.js to Claude and it will embed the paths into the app.")
