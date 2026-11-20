"""Build the two-class YOLO dataset (0 = pothole, 1 = obstacle) from public sources.

Sources are configured in configs/sources.yaml:
  * RDD2022 (figshare, CC BY 4.0): D40 boxes become `pothole`. The archive is a single 13 GB ZIP;
    only its central directory, the annotations and the selected images are downloaded, using
    HTTP Range requests.
  * TerrainSense (Mendeley Data, CC BY 4.0): `obstacle` and `pothole` boxes are kept.
  * Optional local folders with the team's own labelled photos (YOLO format).

Splits are leakage-aware: RDD2022 by blocks of consecutive image ids, TerrainSense by whole
source video, local folders by blocks of consecutive files.

Usage (from ml/):
    python prepare_dataset.py                  # download what is missing, then build
    python prepare_dataset.py --limit 50       # quick smoke test with a few images per source
    python prepare_dataset.py --skip-download  # rebuild splits from the local cache only
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import http.client
import io
import json
import os
import random
import re
import shutil
import struct
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
import zlib
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from PIL import Image

ML_DIR = Path(__file__).resolve().parent
USER_AGENT = "viasegura-dataset-prep/1.0"
SPLITS = ("train", "val", "test")
# Transient network failures worth retrying (dropped connections raise IncompleteRead).
RETRYABLE = (urllib.error.URLError, OSError, http.client.HTTPException)
GENERATED_MARKER = ".generated-by-prepare_dataset"


# --------------------------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------------------------
@dataclass
class Sample:
    source: str
    stem: str
    image_path: Path
    group: str
    boxes: list[tuple[int, float, float, float, float]] = field(default_factory=list)
    split: str = ""


# --------------------------------------------------------------------------------------------
# HTTP helpers
# --------------------------------------------------------------------------------------------
def _open(url: str, headers: dict[str, str] | None = None, timeout: float = 120):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, **(headers or {})})
    return urllib.request.urlopen(request, timeout=timeout)  # noqa: S310 - https URLs from config


def http_get(url: str, retries: int = 6, timeout: float = 180) -> bytes:
    for attempt in range(retries):
        try:
            with _open(url, timeout=timeout) as response:
                return response.read()
        except RETRYABLE:
            if attempt == retries - 1:
                raise
            time.sleep(min(30, 2**attempt))
    raise AssertionError("unreachable")


class HttpRanges:
    """Fetches byte ranges of one remote file; follows redirects and refreshes expired URLs."""

    def __init__(self, url: str) -> None:
        self.url = url
        self._resolve()

    def _resolve(self) -> None:
        # Follow redirects once (figshare -> pre-signed storage URL) and learn the total size.
        with _open(self.url, {"Range": "bytes=0-0"}, timeout=60) as response:
            content_range = response.headers.get("Content-Range", "")
            if response.status != 206 or "/" not in content_range:
                raise OSError("server does not support HTTP Range requests")
            self.final_url = response.geturl()
            self.size = int(content_range.rsplit("/", 1)[1])

    def fetch(self, start: int, length: int, retries: int = 6) -> bytes:
        end = min(self.size, start + length) - 1
        for attempt in range(retries):
            try:
                with _open(self.final_url, {"Range": f"bytes={start}-{end}"}, timeout=300) as resp:
                    data = resp.read()
                    if resp.status != 206 or len(data) != end - start + 1:
                        raise OSError(f"bad range response ({resp.status}, {len(data)} bytes)")
                    return data
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    self._resolve()  # the pre-signed URL expired
                if attempt == retries - 1:
                    raise
            except RETRYABLE:
                if attempt == retries - 1:
                    raise
            time.sleep(min(30, 2**attempt))
        raise AssertionError("unreachable")


class RemoteFile(io.RawIOBase):
    """Read-only, seekable window [base, base + size) of a remote file (HTTP Range requests).

    A window lets zipfile open a ZIP that is stored uncompressed inside another remote ZIP.
    """

    def __init__(
        self, source: str | HttpRanges, base: int = 0, size: int | None = None,
        block_size: int = 4 << 20,
    ) -> None:
        super().__init__()
        self.http = source if isinstance(source, HttpRanges) else HttpRanges(source)
        self.base = base
        self.size = self.http.size - base if size is None else size
        self.block_size = block_size
        self._blocks: dict[int, bytes] = {}
        self._pos = 0

    def fetch(self, start: int, length: int) -> bytes:
        length = min(length, self.size - start)
        return self.http.fetch(self.base + start, length)

    # io.RawIOBase interface, used by zipfile to read the central directory.
    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def tell(self) -> int:
        return self._pos

    def seek(self, offset: int, whence: int = io.SEEK_SET) -> int:
        base = {io.SEEK_SET: 0, io.SEEK_CUR: self._pos, io.SEEK_END: self.size}[whence]
        self._pos = base + offset
        return self._pos

    def readinto(self, buffer) -> int:  # type: ignore[override]
        count = min(len(buffer), self.size - self._pos)
        if count <= 0:
            return 0
        buffer[:count] = self._read_cached(self._pos, count)
        self._pos += count
        return count

    def _read_cached(self, start: int, count: int) -> bytes:
        size = self.block_size
        first, last = start // size, (start + count - 1) // size
        missing = [block for block in range(first, last + 1) if block not in self._blocks]
        if missing:
            low, high = missing[0], missing[-1]
            blob = self.fetch(low * size, (high - low + 1) * size)
            for block in range(low, high + 1):
                self._blocks[block] = blob[(block - low) * size : (block - low + 1) * size]
        joined = b"".join(self._blocks[block] for block in range(first, last + 1))
        offset = start - first * size
        return joined[offset : offset + count]


_LOCAL_HEADER = struct.Struct("<4s5H3I2H")  # 30-byte ZIP local file header


def _span(info: zipfile.ZipInfo) -> int:
    """Upper bound of the bytes occupied by a member (local header + data) plus some slack."""
    return 30 + len(info.filename.encode("utf-8")) + len(info.extra) + info.compress_size + 2048


def _member_bytes(blob: bytes, offset: int, info: zipfile.ZipInfo) -> bytes | None:
    """Decode the member whose local header starts at blob[offset]; None if blob is too short."""
    if offset + 30 > len(blob):
        return None
    fields = _LOCAL_HEADER.unpack_from(blob, offset)
    if fields[0] != b"PK\x03\x04":
        raise ValueError(f"bad local header for {info.filename}")
    start = offset + 30 + fields[9] + fields[10]
    end = start + info.compress_size
    if end > len(blob):
        return None
    raw = blob[start:end]
    if info.compress_type == zipfile.ZIP_STORED:
        data = raw
    elif info.compress_type == zipfile.ZIP_DEFLATED:
        data = zlib.decompress(raw, -15)
    else:
        raise ValueError(f"unsupported compression {info.compress_type} in {info.filename}")
    if zlib.crc32(data) & 0xFFFFFFFF != info.CRC:
        raise ValueError(f"CRC mismatch for {info.filename}")
    return data


def fetch_member(remote: RemoteFile, info: zipfile.ZipInfo) -> bytes:
    blob = remote.fetch(info.header_offset, _span(info))
    data = _member_bytes(blob, 0, info)
    if data is None:  # the local extra field was larger than the central one
        fields = _LOCAL_HEADER.unpack_from(blob, 0)
        exact = 30 + fields[9] + fields[10] + info.compress_size
        data = _member_bytes(remote.fetch(info.header_offset, exact), 0, info)
    if data is None:
        raise ValueError(f"could not read {info.filename}")
    return data


def fetch_contiguous(remote: RemoteFile, infos: list[zipfile.ZipInfo], max_run: int = 4 << 20):
    """Yield (info, bytes) for many small members using few large Range requests."""
    ordered = sorted(infos, key=lambda info: info.header_offset)
    run: list[zipfile.ZipInfo] = []

    def flush(batch: list[zipfile.ZipInfo]):
        start = batch[0].header_offset
        blob = remote.fetch(start, batch[-1].header_offset + _span(batch[-1]) - start)
        for member in batch:
            data = _member_bytes(blob, member.header_offset - start, member)
            yield member, data if data is not None else fetch_member(remote, member)

    for info in ordered:
        if run:
            gap = info.header_offset - (run[-1].header_offset + _span(run[-1]))
            too_long = info.header_offset + _span(info) - run[0].header_offset > max_run
            if gap > (1 << 20) or too_long:
                yield from flush(run)
                run = []
        run.append(info)
    if run:
        yield from flush(run)


# --------------------------------------------------------------------------------------------
# Shared helpers
# --------------------------------------------------------------------------------------------
def to_yolo(box: tuple[float, float, float, float], width: int, height: int):
    """Pixel (x1, y1, x2, y2) -> normalized (cx, cy, w, h); None for degenerate boxes."""
    x1, y1, x2, y2 = box
    x1, x2 = sorted((max(0.0, min(x1, width)), max(0.0, min(x2, width))))
    y1, y2 = sorted((max(0.0, min(y1, height)), max(0.0, min(y2, height))))
    if x2 - x1 < 2 or y2 - y1 < 2:
        return None
    return ((x1 + x2) / 2 / width, (y1 + y2) / 2 / height, (x2 - x1) / width, (y2 - y1) / height)


def split_groups(samples: list[Sample], ratios: dict, seed: int) -> None:
    """Assign whole groups to splits so that related images never cross split boundaries."""
    by_group: dict[str, list[Sample]] = defaultdict(list)
    for sample in samples:
        by_group[sample.group].append(sample)
    groups = sorted(by_group)
    random.Random(seed).shuffle(groups)
    total = len(samples)
    targets = {"test": ratios.get("test", 0.15) * total, "val": ratios.get("val", 0.10) * total}
    filled = {"test": 0, "val": 0}
    for group in groups:
        members = by_group[group]
        split = "train"
        for candidate in ("test", "val"):
            if filled[candidate] < targets[candidate]:
                split = candidate
                filled[candidate] += len(members)
                break
        for sample in members:
            sample.split = split


def run_parallel(tasks, worker, workers: int, label: str) -> list:
    results, failures, started = [], 0, time.time()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(worker, task): task for task in tasks}
        for done, future in enumerate(as_completed(futures), start=1):
            try:
                results.append(future.result())
            except Exception as exc:  # noqa: BLE001 - keep going, report at the end
                failures += 1
                print(f"  ! {label}: {futures[future]!r} failed: {exc}")
            if done % 200 == 0 or done == len(futures):
                rate = done / max(time.time() - started, 1e-6)
                print(f"  {label}: {done}/{len(futures)} ({rate:.1f}/s, {failures} failed)")
    return results


def save_image(data: bytes, path: Path, max_side: int | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if max_side:
        with Image.open(io.BytesIO(data)) as image:
            if max(image.size) > max_side:
                image = image.convert("RGB")
                image.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
                tmp = path.with_suffix(".tmp")
                image.save(tmp, "JPEG", quality=92)
                tmp.replace(path)
                return
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


# --------------------------------------------------------------------------------------------
# RDD2022
# --------------------------------------------------------------------------------------------
_RDD_XML = re.compile(r"(?:^|/)train/annotations/xmls/(?P<stem>[^/]+)\.xml$")
_RDD_IMG = re.compile(r"(?:^|/)train/images/(?P<stem>[^/]+)\.(?:jpg|jpeg|png)$", re.I)


def open_country_archives(url: str, countries: set[str]) -> dict[str, RemoteFile]:
    """Open each country's inner ZIP as a window of the outer archive (both stay remote).

    The published archive stores one ZIP per country *uncompressed*, so every inner ZIP is a
    contiguous byte range of the outer file and can be read without downloading the rest.
    """
    http = HttpRanges(url)
    outer_view = RemoteFile(http)
    windows: dict[str, RemoteFile] = {}
    for info in zipfile.ZipFile(outer_view).infolist():
        country = Path(info.filename).stem
        if country not in countries:
            continue
        if info.compress_type != zipfile.ZIP_STORED:
            raise SystemExit(f"{info.filename} is compressed; it cannot be read as a window")
        fields = _LOCAL_HEADER.unpack_from(outer_view.fetch(info.header_offset, 30), 0)
        data_start = info.header_offset + 30 + fields[9] + fields[10]
        windows[country] = RemoteFile(http, base=data_start, size=info.file_size)
    print(f"RDD2022: {http.size / 1e9:.2f} GB archive; opened {sorted(windows)} remotely")
    return windows


def parse_voc(xml_bytes: bytes):
    if b"<!DOCTYPE" in xml_bytes or b"<!ENTITY" in xml_bytes:
        raise ValueError("XML with DTD/entities refused")
    root = ET.fromstring(xml_bytes)  # noqa: S314 - DTD/entities refused above
    size = root.find("size")
    width = int(float(size.findtext("width", "0"))) if size is not None else 0
    height = int(float(size.findtext("height", "0"))) if size is not None else 0
    objects = []
    for obj in root.iter("object"):
        box = obj.find("bndbox")
        if box is None:
            continue
        coords = tuple(float(box.findtext(key, "0")) for key in ("xmin", "ymin", "xmax", "ymax"))
        objects.append(((obj.findtext("name") or "").strip(), coords))
    return width, height, objects


def prepare_rdd2022(cfg: dict, classes: list[str], raw: Path, args) -> list[Sample]:
    cache = raw / "rdd2022"
    index_path = cache / "annotations.json"
    countries = set(cfg["countries"])
    class_ids = {name: classes.index(target) for name, target in cfg["class_map"].items()}

    windows: dict[str, RemoteFile] | None = None
    annotations = {}
    if index_path.exists():
        annotations = json.loads(index_path.read_text(encoding="utf-8"))
    if not annotations:
        if args.skip_download:
            raise SystemExit("RDD2022 annotations are not cached; run without --skip-download")
        print("RDD2022: reading central directories (no full download)...")
        windows = open_country_archives(cfg["url"], countries)
        for country, window in sorted(windows.items()):
            infos = zipfile.ZipFile(window).infolist()
            xml_members = [info for info in infos if _RDD_XML.search(info.filename)]
            images = {
                match["stem"]: info.filename
                for info in infos
                if (match := _RDD_IMG.search(info.filename))
            }
            print(f"RDD2022 {country}: {len(xml_members)} annotations, {len(images)} images")
            for info, data in fetch_contiguous(window, xml_members):
                stem = _RDD_XML.search(info.filename)["stem"]
                width, height, objects = parse_voc(data)
                annotations[f"{country}/{stem}"] = {
                    "width": width,
                    "height": height,
                    "objects": objects,
                    "member": images.get(stem),
                }
        if not annotations:
            raise SystemExit("RDD2022: no annotations found; the archive layout may have changed")
        cache.mkdir(parents=True, exist_ok=True)
        index_path.write_text(json.dumps(annotations), encoding="utf-8")

    # Select pothole images and a share of background (crack-only / clean) images per country.
    rng = random.Random(args.seed)
    selected: list[str] = []
    for country in sorted(countries):
        keys = sorted(k for k in annotations if k.startswith(f"{country}/"))
        keys = [k for k in keys if annotations[k].get("member")]
        positives = [k for k in keys if any(n in class_ids for n, _ in annotations[k]["objects"])]
        positive_set = set(positives)
        negatives = [k for k in keys if k not in positive_set]
        if args.limit:
            positives = positives[: args.limit]
        quota = min(len(negatives), round(len(positives) * cfg.get("negatives_ratio", 0.0)))
        chosen_negatives = rng.sample(negatives, quota)
        print(f"RDD2022 {country}: {len(positives)} pothole images, {quota} background images")
        selected += positives + chosen_negatives

    missing = [k for k in selected if not (cache / "images" / f"{k}.jpg").exists()]
    if missing and not args.skip_download:
        windows = windows or open_country_archives(cfg["url"], countries)
        members = {
            country: {info.filename: info for info in zipfile.ZipFile(window).infolist()}
            for country, window in windows.items()
        }
        print(f"RDD2022: downloading {len(missing)} images...")

        def download(key: str) -> str:
            country = key.split("/", 1)[0]
            info = members[country][annotations[key]["member"]]
            save_image(fetch_member(windows[country], info), cache / "images" / f"{key}.jpg")
            return key

        run_parallel(missing, download, args.workers, "rdd2022")

    samples = []
    block = cfg["split"].get("block_size", 20)
    for key in selected:
        path = cache / "images" / f"{key}.jpg"
        if not path.exists():
            continue
        record = annotations[key]
        width, height = record["width"], record["height"]
        if not width or not height:
            with Image.open(path) as image:
                width, height = image.size
        boxes = []
        for name, coords in record["objects"]:
            if name in class_ids and (yolo := to_yolo(coords, width, height)):
                boxes.append((class_ids[name], *yolo))
        country, stem = key.split("/")
        number = int(re.sub(r"\D", "", stem) or 0)
        samples.append(Sample("rdd2022", f"{country}_{stem}", path, f"{country}-{number // block}"))
        samples[-1].boxes = boxes
    split_groups(samples, cfg["split"], args.seed)
    return samples


# --------------------------------------------------------------------------------------------
# TerrainSense
# --------------------------------------------------------------------------------------------
def terrainsense_video(stem: str) -> str:
    if match := re.match(r"^(.*?)_mp4-\d+_jpg\.rf\.[0-9a-f]+$", stem):
        return match.group(1).removesuffix("-copy")
    if match := re.match(r"^(clip\d+)_\d+$", stem):
        return match.group(1)
    return stem


def prepare_terrainsense(cfg: dict, classes: list[str], raw: Path, args) -> list[Sample]:
    cache = raw / "terrainsense"
    manifest_path = cache / "manifest.json"
    if not manifest_path.exists():
        if args.skip_download:
            raise SystemExit("TerrainSense manifest is not cached; run without --skip-download")
        cache.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(http_get(cfg["api"]))
    files = json.loads(manifest_path.read_text(encoding="utf-8"))["files"]
    images = {f["filename"].rsplit(".", 1)[0]: f for f in files if f["filename"].endswith(".jpg")}
    labels = {f["filename"].rsplit(".", 1)[0]: f for f in files if f["filename"].endswith(".txt")}
    test_groups, val_groups = set(cfg["split_groups"]["test"]), set(cfg["split_groups"]["val"])

    def split_of(group: str) -> str:
        return "test" if group in test_groups else "val" if group in val_groups else "train"

    # Consecutive video frames are near-duplicates: keep every n-th frame per video and split.
    by_video: dict[str, list[str]] = defaultdict(list)
    for stem in sorted(set(images) & set(labels)):
        by_video[terrainsense_video(stem)].append(stem)
    strides = cfg.get("frame_stride", {})
    stems = []
    for video, members in sorted(by_video.items()):
        members.sort(key=lambda s: int(m[1]) if (m := re.search(r"[_-](\d+)", s)) else 0)
        stems += members[:: max(1, strides.get(split_of(video), 1))]
    if args.limit:
        stems = stems[: args.limit]

    def download(stem: str) -> str:
        label_path = cache / "labels" / f"{stem}.txt"
        image_path = cache / "images" / f"{stem}.jpg"
        if not label_path.exists():
            label_path.parent.mkdir(parents=True, exist_ok=True)
            label_path.write_bytes(http_get(labels[stem]["content_details"]["download_url"]))
        if not image_path.exists():
            details = images[stem]["content_details"]
            data = http_get(details["download_url"])
            expected = details.get("sha256_hash")
            if expected and hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("sha256 mismatch")
            save_image(data, image_path, cfg.get("max_side"))
        return stem

    todo = [s for s in stems if not (cache / "images" / f"{s}.jpg").exists()]
    if todo and not args.skip_download:
        print(f"TerrainSense: downloading {len(todo)} image/label pairs...")
        run_parallel(todo, download, args.workers, "terrainsense")

    names = cfg["names"]
    mapping = {names.index(src): classes.index(dst) for src, dst in cfg["class_map"].items()}
    samples = []
    for stem in stems:
        image_path = cache / "images" / f"{stem}.jpg"
        label_path = cache / "labels" / f"{stem}.txt"
        if not (image_path.exists() and label_path.exists()):
            continue
        boxes = []
        for line in label_path.read_text(encoding="utf-8").splitlines():
            parts = line.split()
            if len(parts) != 5:
                continue
            source_class, *coords = int(parts[0]), *map(float, parts[1:])
            if source_class in mapping and all(0 <= value <= 1 for value in coords):
                boxes.append((mapping[source_class], *coords))
        group = terrainsense_video(stem)
        samples.append(Sample("terrainsense", stem, image_path, group, boxes, split_of(group)))
    return samples


# --------------------------------------------------------------------------------------------
# Local team photos
# --------------------------------------------------------------------------------------------
def prepare_local(cfg: dict, classes: list[str], args) -> list[Sample]:
    root = ML_DIR / cfg["path"]
    image_dir, label_dir = root / "images", root / "labels"
    if not image_dir.is_dir():
        print(f"local '{cfg['name']}': {image_dir} not found, skipped")
        return []
    paths = sorted(
        p for p in image_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )
    block = cfg.get("split", {}).get("block_size", 10)
    samples = []
    for index, path in enumerate(paths):
        boxes = []
        label = label_dir / f"{path.stem}.txt"
        if label.exists():
            for line in label.read_text(encoding="utf-8").splitlines():
                parts = line.split()
                if len(parts) == 5 and int(parts[0]) in range(len(classes)):
                    boxes.append((int(parts[0]), *map(float, parts[1:])))
        samples.append(Sample(cfg["name"], path.stem, path, f"{cfg['name']}-{index // block}"))
        samples[-1].boxes = boxes
    split_groups(samples, cfg.get("split", {}), args.seed)
    return samples


# --------------------------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------------------------
def write_dataset(samples: list[Sample], classes: list[str], out: Path, sources: dict) -> dict:
    if out.exists():
        if not (out / GENERATED_MARKER).exists():
            raise SystemExit(f"{out} exists and was not generated by this script; refusing to delete")
        shutil.rmtree(out)
    for split in SPLITS:
        (out / "images" / split).mkdir(parents=True)
        (out / "labels" / split).mkdir(parents=True)
    (out / GENERATED_MARKER).write_text("safe to delete; rebuilt by prepare_dataset.py\n")

    stats: dict = {split: defaultdict(Counter) for split in SPLITS}
    with open(out / "manifest.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["split", "file", "source", "group", *[f"n_{c}" for c in classes]])
        for sample in samples:
            name = f"{sample.source}__{sample.stem}"
            image_dst = out / "images" / sample.split / f"{name}{sample.image_path.suffix.lower()}"
            try:
                os.link(sample.image_path, image_dst)
            except OSError:
                shutil.copy2(sample.image_path, image_dst)
            lines = [f"{c} {x:.6f} {y:.6f} {w:.6f} {h:.6f}" for c, x, y, w, h in sample.boxes]
            label_dst = out / "labels" / sample.split / f"{name}.txt"
            label_dst.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            counts = Counter(classes[c] for c, *_ in sample.boxes)
            writer.writerow(
                [sample.split, image_dst.name, sample.source, sample.group]
                + [counts[c] for c in classes]
            )
            bucket = stats[sample.split][sample.source]
            bucket["images"] += 1
            bucket["background_images"] += 0 if sample.boxes else 1
            for class_name, count in counts.items():
                bucket[f"boxes_{class_name}"] += count

    dataset_yaml = {
        "path": str(out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(classes)),
    }
    (out / "dataset.yaml").write_text(yaml.safe_dump(dataset_yaml, sort_keys=False), "utf-8")
    summary = {
        "classes": classes,
        "splits": {split: {src: dict(c) for src, c in stats[split].items()} for split in SPLITS},
        "sources": sources,
    }
    (out / "stats.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def print_summary(summary: dict) -> None:
    classes = summary["classes"]
    header = f"{'split':<6} {'source':<22} {'images':>7} {'bg':>6}" + "".join(
        f" {c:>9}" for c in classes
    )
    print("\n" + header + "\n" + "-" * len(header))
    for split, sources in summary["splits"].items():
        for source, counts in sorted(sources.items()):
            row = f"{split:<6} {source:<22} {counts.get('images', 0):>7} "
            row += f"{counts.get('background_images', 0):>6}"
            row += "".join(f" {counts.get(f'boxes_{c}', 0):>9}" for c in classes)
            print(row)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", default=str(ML_DIR / "configs" / "sources.yaml"))
    parser.add_argument("--skip-download", action="store_true")
    parser.add_argument("--limit", type=int, default=0, help="max images per source (smoke test)")
    parser.add_argument("--workers", type=int, default=12)
    args = parser.parse_args()

    cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    args.seed = cfg.get("seed", 42)
    classes = cfg["classes"]
    raw = ML_DIR / cfg["raw_dir"]

    samples: list[Sample] = []
    sources: dict = {}
    if cfg.get("rdd2022", {}).get("enabled"):
        samples += prepare_rdd2022(cfg["rdd2022"], classes, raw, args)
        sources["rdd2022"] = {k: cfg["rdd2022"][k] for k in ("license", "citation")}
    if cfg.get("terrainsense", {}).get("enabled"):
        samples += prepare_terrainsense(cfg["terrainsense"], classes, raw, args)
        sources["terrainsense"] = {k: cfg["terrainsense"][k] for k in ("license", "citation")}
    for local in cfg.get("local") or []:
        if local.get("enabled"):
            samples += prepare_local(local, classes, args)
            sources[local["name"]] = {"license": local.get("license", "team-owned")}

    if not samples:
        raise SystemExit("no samples prepared; check configs/sources.yaml")
    summary = write_dataset(samples, classes, ML_DIR / cfg["output_dir"], sources)
    print_summary(summary)
    print(f"\nDataset ready: {ML_DIR / cfg['output_dir'] / 'dataset.yaml'}")


if __name__ == "__main__":
    main()
