#!/usr/bin/env python3
"""Download the public Cameo sample models listed in samples/SOURCES.md.

The samples are third-party files, so they are gitignored; this script restores them
in a fresh clone. It uses only the standard library, so it runs before `uv sync`.

    python3 scripts/fetch_samples.py            # all samples (~105 MB)
    python3 scripts/fetch_samples.py --small    # only files under 5 MB (enough for the tests)
    python3 scripts/fetch_samples.py --strict   # fail if upstream content changed

Files already present with the expected sha256 are skipped. The URLs point at branch
heads, so upstream can change; a checksum mismatch is reported (and the new file kept
unless --strict), since sample drift should be noticed but need not block work.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import tempfile
import urllib.request
from pathlib import Path

SAMPLES_DIR = Path(__file__).resolve().parent.parent / "samples"
SMALL = 5_000_000

GH = "https://raw.githubusercontent.com"
SAF = "https://github.com/GfSE/SAF-Cameo-Profile"
# (path under samples/, url, sha256 at time of recording, size in bytes)
SAMPLES = [
    ("MDK_CSyncTest.mdzip", f"{GH}/Open-MBEE/exec-cameo-mdk/develop/src/test/resources/CSyncTest.mdzip",
     "5507ea7fad855400832bea44424a2080c00f2c15b59e18c3d5153b66fc8976a4", 211629),
    ("NIST_M-SysML.mdzip", f"{GH}/usnistgov/DiscreteEventLogisticsSystems/master/M-SysML.mdzip",
     "50ba80fdd51937ed46bcd991e2b7b12aaeeae4a70266cf56a0f99e22fab1485c", 2771926),
    ("GTRI_Import_Example_Base.mdzip",
     f"{GH}/gtri/rapid-modeling-tools/master/ingrid-quick-start/Import%20Example%20Base.mdzip",
     "1e333e7cee3bae0b7336a96400e25eaf6c09fa5100d66388f03a0ae419f08f16", 298600),
    ("EOSS.mdzip", f"{GH}/seakers/cameo-LLM-plugin/main/cameo/examples/EOSS.mdzip",
     "afa20ab834b2e6fc11900502b6aecb6169d6b05a4bbd84714f853eeec2620ca8", 256853),
    ("Package_Delivery_Drone.mdzip",
     f"{GH}/jmgogo/Package-Delivery-Drone/main/model/Package%20Delivery%20Drone.mdzip",
     "ecc43337599571483c8c7c854eada62a84fba4da1ec6485a8ac15d6da515bdc1", 282201),
    ("OpenSUT_MPS.mdzip",  # Git LFS object
     "https://media.githubusercontent.com/media/GaloisInc/VERSE-OpenSUT/main/models/SysMLv1/MPS.mdzip",
     "be282a3ca956f114ae369906ee995b96ad3a60dbc79eddcb72db3e43a42e45c8", 454252),
    ("OpenSUT_overview.mdzip", f"{GH}/GaloisInc/VERSE-OpenSUT/main/models/SysMLv1/OpenSUT_overview.mdzip",
     "214d88040aeffe0cd351fc81592702391a104ea1445247b2554050e881c8df4b", 349472),
    ("MDK_DocGen.mdzip", f"{GH}/Open-MBEE/exec-cameo-mdk/develop/src/main/dist/samples/MDK/DocGen.mdzip",
     "464d99a13228190c261d9b5e261b66cf93e2c8cc88c89bce37d639c88f3677b0", 2109761),
    ("TMT.mdzip", f"{GH}/Open-MBEE/TMT-SysML-Model/master/TMT.mdzip",
     "9ffd7a2c3b7f3fca8f64092949309012bb75cad5f86da2edfee140ab49d20581", 27137489),
    ("TMT-2024x.mdzip", f"{GH}/Open-MBEE/TMT-SysML-Model/master/TMT-2024x.mdzip",
     "c25c2dc0fb5e74c22c09fde5fb08645947bacd7c93159209115075c64ae6dd5b", 27193371),
    ("cusa26_hidden-in-plain-sight.mdzip",
     f"{GH}/EnolaTechnologies/cusa26/main/hidden-in-plain-sight/hidden-in-plain-sight.mdzip",
     "01e6b94a3cd0e8d55e9a50d8e504299e529b2de3fbcb6de0b1c42422fc6376c2", 1224118),
    ("SAF_Blank.mdzip", f"{GH}/GfSE/SAF-Cameo-Profile/main/SAF_Plugin/templates/SAF%20Blank/SAF%20Blank.mdzip",
     "cacc6d6b8e25136cf226b2e7a9e005ed04efb173f25aa7f46b7a176aa4fbc386", 153437),
    ("SAF_FFDS.mdzip", f"{GH}/GfSE/SAF-Cameo-Profile/main/SAF_Plugin/samples/SAF/SAF_FFDS.mdzip",
     "197f8381ad12f7d7e27001bf2a0828c8893211fbcb19b8f4bf25e6406d10d5b1", 11740062),
    ("SAF_Profile.mdzip", f"{GH}/GfSE/SAF-Cameo-Profile/main/SAF_Plugin/profiles/SAF_Profile.mdzip",
     "24fb896309b8d1064e77e1d6955fd381b0438bd6c6ae68cc40a8f20fabfb857e", 3094300),
    ("resource_bundles/SAF_DevPlugin_2026-09-16.zip",
     f"{SAF}/releases/download/vcameo2026x-2026-09-16/SAF_DevPlugin.zip",
     "0efaa914fd0adf1e1d187f8eddaf81cbbfea8576fcedec8bf9a0c3f5de680b27", 285597),
    ("resource_bundles/SAF_Plugin_2026-09-16.zip",
     f"{SAF}/releases/download/vcameo2026x-2026-09-16/SAF_Plugin.zip",
     "f8e81b6dc1af74037715cb76c19fbbacb584e30b42d389d5b9e86df897112f16", 31474147),
]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def download(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "cameo-ingest-fetch-samples"})
    with tempfile.NamedTemporaryFile(dir=dest.parent, delete=False, suffix=".part") as tmp:
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                while block := resp.read(1 << 20):
                    tmp.write(block)
            tmp.close()
            Path(tmp.name).replace(dest)
        except BaseException:
            Path(tmp.name).unlink(missing_ok=True)
            raise


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--small", action="store_true", help=f"only files under {SMALL // 1_000_000} MB")
    ap.add_argument("--strict", action="store_true", help="treat checksum mismatches as errors")
    ap.add_argument("--dest", type=Path, default=SAMPLES_DIR, help="target directory (default: samples/)")
    args = ap.parse_args()

    failures = mismatches = 0
    for rel, url, sha, size in SAMPLES:
        if args.small and size >= SMALL:
            continue
        dest = args.dest / rel
        if dest.exists() and sha256_file(dest) == sha:
            print(f"ok       {rel}")
            continue
        print(f"fetching {rel} ({size / 1e6:.1f} MB)", flush=True)
        try:
            download(url, dest)
        except Exception as e:
            print(f"FAILED   {rel}: {e}", file=sys.stderr)
            failures += 1
            continue
        got = sha256_file(dest)
        if got != sha:
            mismatches += 1
            print(f"CHANGED  {rel}: upstream content differs from the recorded sha256\n"
                  f"         expected {sha}\n         got      {got}", file=sys.stderr)
            if args.strict:
                dest.unlink()
    if failures or mismatches:
        print(f"{failures} failed, {mismatches} changed upstream", file=sys.stderr)
    return 1 if failures or (args.strict and mismatches) else 0


if __name__ == "__main__":
    sys.exit(main())
