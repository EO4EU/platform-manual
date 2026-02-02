from pathlib import Path

import rasterio
from rasterio.windows import from_bounds
from rasterio.windows import transform as window_transform
from pyproj import Transformer

# --- requirements ---
# rasterio==1.3.10
# pyproj

EO4EU_FAAS_OPTIONS = {
    "group_by_path": "source/.+/([0-9,A-Z]+)_.*.jp2",
    "number_of_jobs": 3,
}

def bounds_to_tuple(b):
    return (b.left, b.bottom, b.right, b.top)


def intersect_bounds(a, b):
    l = max(a[0], b[0])
    btm = max(a[1], b[1])
    r = min(a[2], b[2])
    t = min(a[3], b[3])
    if (r <= l) or (t <= btm):
        return None
    return (l, btm, r, t)


def transform_bounds(bounds, src_crs, dst_crs):
    if src_crs == dst_crs:
        return bounds

    transformer = Transformer.from_crs(src_crs, dst_crs, always_xy=True)
    l, b, r, t = bounds
    corners = [(l, b), (l, t), (r, b), (r, t)]
    xs, ys = [], []
    for x, y in corners:
        X, Y = transformer.transform(x, y)
        xs.append(X)
        ys.append(Y)
    return (min(xs), min(ys), max(xs), max(ys))


def center_crop_bounds(common_bounds, fraction=None, size_m=None):
    l, b, r, t = common_bounds
    cx = 0.5 * (l + r)
    cy = 0.5 * (b + t)
    w = r - l
    h = t - b

    if size_m is not None:
        half = 0.5 * float(size_m)
        return (cx - half, cy - half, cx + half, cy + half)

    frac = float(fraction)
    if not (0.0 < frac <= 1.0):
        raise ValueError("--fraction must be in (0, 1].")
    half_w = 0.5 * w * frac
    half_h = 0.5 * h * frac
    return (cx - half_w, cy - half_h, cx + half_w, cy + half_h)


def pick_jp2_driver():
    # Prefer JP2OpenJPEG (most common). Fallback to JPEG2000.
    with rasterio.Env() as env:
        drv = env.drivers()
    if "JP2OpenJPEG" in drv:
        return "JP2OpenJPEG"
    if "JPEG2000" in drv:
        return "JPEG2000"
    raise RuntimeError(
        "No JPEG2000 write driver found in GDAL. Need JP2OpenJPEG or JPEG2000 enabled."
    )


def crop_one_to_jp2(src_path: Path, dst_path: Path, crop_bounds, ref_crs, out_driver: str, lossless: bool, quality: int):
    with rasterio.open(src_path) as ds:
        cb = transform_bounds(crop_bounds, ref_crs, ds.crs)

        win = from_bounds(*cb, transform=ds.transform)
        win = win.round_offsets().round_lengths()

        full = rasterio.windows.Window(0, 0, ds.width, ds.height)
        win = win.intersection(full)
        if win.width <= 0 or win.height <= 0:
            raise RuntimeError(f"Crop window empty for {src_path}")

        data = ds.read(window=win)
        out_transform = window_transform(win, ds.transform)

        profile = ds.profile.copy()
        profile.update(
            driver=out_driver,
            height=data.shape[1],
            width=data.shape[2],
            transform=out_transform,
        )

        # JP2OpenJPEG creation options:
        # - REVERSIBLE=YES -> lossless
        # - QUALITY=xx -> lossy quality (ignored if REVERSIBLE=YES)
        creation_opts = {}
        if out_driver == "JP2OpenJPEG":
            if lossless:
                creation_opts["REVERSIBLE"] = "YES"
            else:
                creation_opts["REVERSIBLE"] = "NO"
                creation_opts["QUALITY"] = str(int(quality))
        else:
            # For other JPEG2000 drivers, options vary; keep minimal.
            # Many ignore REVERSIBLE/QUALITY or name them differently.
            if lossless:
                creation_opts["REVERSIBLE"] = "YES"

        dst_path.parent.mkdir(parents=True, exist_ok=True)
        with rasterio.open(dst_path, "w", **profile, **creation_opts) as out:
            out.write(data)


def main(input_paths: list[str]) -> list[str]:
    jp2_files = []
    for p in input_paths:
        path = Path(p)
        if path.suffix == ".jp2":
            jp2_files.append(path)

    fraction = 0.5
    size_m = 1000
    suffix = ""
    lossless = True
    quality = 25
    out_root = "output"

    if not jp2_files:
        raise SystemExit(f"No .jp2 files found in input")

    out_driver = pick_jp2_driver()

    # Reference CRS + intersection bounds in reference CRS
    with rasterio.open(jp2_files[0]) as ref:
        ref_crs = ref.crs
        if ref_crs is None:
            raise SystemExit(f"Reference file has no CRS: {jp2_files[0]}")
        common = bounds_to_tuple(ref.bounds)

    for p in jp2_files[1:]:
        with rasterio.open(p) as ds:
            if ds.crs is None:
                raise SystemExit(f"File has no CRS: {p}")
            b = bounds_to_tuple(ds.bounds)
            b_in_ref = transform_bounds(b, ds.crs, ref_crs)
            common = intersect_bounds(common, b_in_ref)
            if common is None:
                raise SystemExit("No common overlap exists across all JP2 files (intersection became empty).")

    crop_bounds = center_crop_bounds(common, fraction=fraction, size_m=size_m)

    print(f"Found {len(jp2_files)} JP2 files")
    print(f"JP2 output driver: {out_driver}")
    print(f"Reference CRS: {ref_crs}")
    print(f"Common overlap bounds (ref CRS): {common}")
    print(f"Crop bounds (ref CRS):          {crop_bounds}")
    print(f"Output folder: {out_root}")
    print(f"Mode: {'lossless' if lossless else f'lossy quality={quality}'}")

    output_paths = []
    for src in jp2_files:
        dst_str = f"{out_root}/{src.stem}{suffix}.jp2"
        output_paths.append(dst_str)
        crop_one_to_jp2(src, Path(dst_str), crop_bounds, ref_crs, out_driver, lossless, quality)

    print("Done.")
    return output_paths
