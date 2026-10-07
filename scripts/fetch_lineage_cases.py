#!/usr/bin/env python3
"""Fetch public Cameo models with a known history, for measuring lineage (plan LN-03).

    uv run python scripts/fetch_lineage_cases.py DIR      # about 250 MB; best outside the repository

Each file is one commit of a public git repository (the survey of 2026-10-07), written to
DIR/<chain>/<date>_<commit>/<file name>, so that each keeps its own folder, as versions of a model
do. `TRUTH` says what each pair of them is, as their history tells it. Kept out of the default
samples: they are large, and they test one analysis.
"""

from __future__ import annotations

import argparse
import sys
import urllib.parse
import urllib.request
from pathlib import Path

RAW = "https://raw.githubusercontent.com"
LFS = "https://media.githubusercontent.com/media"

# (chain, date, repository, commit, path, LFS): a chain is one model's line of history.
FILES = [
    # SAF's sample model, 2021 to 2026 (Apache-2.0): moved to SAF_Plugin/samples/SAF/ in 2024.
    ("saf-ffds", "2021-11-11", "GfSE/SAF-Cameo-Profile", "7b32b66479fb61fc4ba217505dd589260a4302de", "SAF_FFDS.mdzip", False),
    ("saf-ffds", "2024-07-25", "GfSE/SAF-Cameo-Profile", "2aa2164348c83cfa8dc2ab2875ccde9333162761", "SAF_Plugin/samples/SAF/SAF_FFDS.mdzip", False),
    ("saf-ffds", "2024-11-16", "GfSE/SAF-Cameo-Profile", "d0b3387e0b4b2839ab541db2cf88e258315ef916", "SAF_Plugin/samples/SAF/SAF_FFDS.mdzip", False),
    ("saf-ffds", "2025-10-14", "GfSE/SAF-Cameo-Profile", "874776f8f3e0706d418a86b9026d501c9126a786", "SAF_Plugin/samples/SAF/SAF_FFDS.mdzip", False),
    ("saf-ffds", "2026-02-22", "GfSE/SAF-Cameo-Profile", "fc25ceab1fab00abc9fb5f1b7efb27e3bf5e0ef3", "SAF_Plugin/samples/SAF/SAF_FFDS.mdzip", False),
    ("saf-ffds", "2026-08-13", "GfSE/SAF-Cameo-Profile", "14e7aeeacca8fc48e68aa53089e53990be0532f7", "SAF_Plugin/samples/SAF/SAF_FFDS.mdzip", False),
    # OpenSUT's RTS and overview (BSD-3-Clause).
    ("opensut-rts", "2024-04-24", "GaloisInc/VERSE-OpenSUT", "be0d6d89d4769a752761ac2dee581deb98422b22", "models/SysMLv1/RTS.mdzip", False),
    ("opensut-rts", "2024-04-25a", "GaloisInc/VERSE-OpenSUT", "66d29eddb7221f7e77bb9e9174ee2d831b28250b", "models/SysMLv1/RTS.mdzip", False),
    ("opensut-rts", "2024-04-25b", "GaloisInc/VERSE-OpenSUT", "60dba06b4780ef3e858ed79f3a2ccf7ab9d8c2c0", "models/SysMLv1/RTS.mdzip", False),
    ("opensut-rts", "2024-05-03", "GaloisInc/VERSE-OpenSUT", "285a390c5f4a6086665a0940c2c4aeb0ae32b043", "models/SysMLv1/RTS.mdzip", False),
    ("opensut-overview", "2025-03-20", "GaloisInc/VERSE-OpenSUT", "bf2d8fb7ef0a61e2c8787b1929e598d7923d6bf0", "models/SysMLv1/OpenSUT_overview.mdzip", False),
    ("opensut-overview", "2025-03-26", "GaloisInc/VERSE-OpenSUT", "7d39c63b50342c16846738756a8654ce7eef7bef", "models/SysMLv1/OpenSUT_overview.mdzip", False),
    # NIST's flow network, renamed TokenFlowNetwork to CommodityFlowNetwork on 2019-04-01, then much rewritten in 2020.
    ("nist-flow", "2019-03-15", "usnistgov/DiscreteEventLogisticsSystems", "7d7225afb9302b31c256c21335321c0969143a62", "TokenFlowNetwork.mdzip", False),
    ("nist-flow", "2019-04-01", "usnistgov/DiscreteEventLogisticsSystems", "035274f6950aae6eb50bbb189c1c8078f9238eca", "CommodityFlowNetwork.mdzip", False),
    ("nist-flow", "2019-07-24", "usnistgov/DiscreteEventLogisticsSystems", "94b0ea4d48fad5315df3d985f5f4969d2cab32fd", "CommodityFlowNetwork.mdzip", False),
    ("nist-flow", "2020-03-27", "usnistgov/DiscreteEventLogisticsSystems", "55c0b40ee9f35513b62d807c864dfb3d5e354647", "CommodityFlowNetwork.mdzip", False),
    # TMT (Apache-2.0): master's 2019 model, then two branches from it, then master again.
    ("tmt", "2019-10-27", "Open-MBEE/TMT-SysML-Model", "b09442bcc9c6011d6d64c6258bdfb5aa7a47a882", "TMT.mdzip", False),
    ("tmt-omg-sst", "2023-04-27", "Open-MBEE/TMT-SysML-Model", "afdd377c43e071bef50ee5c36fde52efc56b9f72", "TMT.mdzip", False),
    ("tmt-aps", "2023-06-22", "Open-MBEE/TMT-SysML-Model", "d834a0d89854a3edf7e16736ba993c83da23f97d", "TMT_testing_aps_470.mdzip", False),
    ("tmt", "2023-11-02", "Open-MBEE/TMT-SysML-Model", "5b21c15ec3e46c4835db83633d7c270e238256f9", "TMT.mdzip", False),
]

# What pairs are, as history tells it, by (chain, date): consecutive members of a chain are
# versions (or copies). The TMT branches share master's 2019 model as their root, but omg-sst's file
# of 2023-04 is that root saved again (2 ids differ), so no pair is a true pair of branches.
TRUTH = [
    *[(("saf-ffds", a), ("saf-ffds", b), "version") for a, b in
      (("2021-11-11", "2024-07-25"), ("2024-07-25", "2024-11-16"), ("2024-11-16", "2025-10-14"),
       ("2025-10-14", "2026-02-22"), ("2026-02-22", "2026-08-13"))],
    *[(("opensut-rts", a), ("opensut-rts", b), "version") for a, b in
      (("2024-04-24", "2024-04-25a"), ("2024-04-25a", "2024-04-25b"), ("2024-04-25b", "2024-05-03"))],
    (("opensut-overview", "2025-03-20"), ("opensut-overview", "2025-03-26"), "version"),
    (("nist-flow", "2019-03-15"), ("nist-flow", "2019-04-01"), "copy"),
    (("nist-flow", "2019-04-01"), ("nist-flow", "2019-07-24"), "version"),
    (("nist-flow", "2019-07-24"), ("nist-flow", "2020-03-27"), "version"),
    (("tmt", "2019-10-27"), ("tmt-omg-sst", "2023-04-27"), "copy"),  # the branch's file: the root, saved again
    (("tmt", "2019-10-27"), ("tmt-aps", "2023-06-22"), "version"),
    (("tmt-omg-sst", "2023-04-27"), ("tmt-aps", "2023-06-22"), "version"),  # as the root is to the other branch
    (("tmt-aps", "2023-06-22"), ("tmt", "2023-11-02"), "version"),
]


def url(repo: str, commit: str, path: str, lfs: bool) -> str:
    return f"{LFS if lfs else RAW}/{repo}/{commit}/{urllib.parse.quote(path)}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("dir", type=Path)
    args = ap.parse_args()
    for chain, date, repo, commit, path, lfs in FILES:
        dest = args.dir / chain / f"{date}_{commit[:7]}" / Path(path).name
        if dest.is_file():
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        print(f"{chain} {date}: {repo} {path}", file=sys.stderr)
        with urllib.request.urlopen(url(repo, commit, path, lfs), timeout=300) as r:
            data = r.read()
        if data.startswith(b"version https://git-lfs"):
            print(f"  a Git LFS pointer, not the file: {path}", file=sys.stderr)
            return 1
        dest.write_bytes(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
