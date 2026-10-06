"""Cut test windows from the E. coli K-12 MG1655 genome (GenBank U00096.3).

Targets:
  - CRISPR repeat-spacer arrays. These are NOT in the GenBank annotation, so
    they are located here by a repeat search next to the annotated cas genes.
  - Insertion sequences, from the annotation's mobile_element features.
  - prfB, the gene the annotation marks as read through a ribosomal frameshift.
Controls are windows that hold only ordinary annotated genes.

Each window is placed at a random offset and on a random strand, so the target
is not centred and the sequence is not always in database orientation.
"""
import argparse
import json
import random
import re
import urllib.request
from collections import defaultdict
from pathlib import Path

from make_loci import write_fasta

ACCESSION = "U00096.3"
EFETCH = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=nuccore&id={acc}&retmode=text&rettype={rettype}"
CRISPR_SEARCH_FLANK = 60_000  # how far around cas2 to look for arrays
# Feature kinds a control window must not touch.
NOT_ORDINARY = {"mobile_element", "misc_feature", "rRNA", "tRNA", "ncRNA", "rep_origin"}


def download(raw_dir):
    raw_dir.mkdir(parents=True, exist_ok=True)
    paths = {}
    for rettype in ("fasta", "ft"):
        paths[rettype] = raw_dir / f"{ACCESSION}.{rettype}"
        if not paths[rettype].exists():
            urllib.request.urlretrieve(EFETCH.format(acc=ACCESSION, rettype=rettype), paths[rettype])
    return paths


def parse_feature_table(text):
    """NCBI feature-table format -> list of {key, start, end, strand, quals} (1-based, start <= end)."""
    features = []
    for line in text.splitlines():
        cols = line.split("\t")
        if line.startswith(">") or not line.strip():
            continue
        if cols[0]:  # a location line: new feature, or a further interval of the current one
            a, b = (int(re.sub(r"[<>^]", "", c)) for c in cols[:2])
            if len(cols) > 2 and cols[2]:
                features.append({"key": cols[2], "start": min(a, b), "end": max(a, b), "strand": "+" if a <= b else "-", "quals": {}})
            else:
                features[-1]["start"] = min(features[-1]["start"], a, b)
                features[-1]["end"] = max(features[-1]["end"], a, b)
        elif len(cols) > 3:
            features[-1]["quals"].setdefault(cols[3], cols[4] if len(cols) > 4 else "")
    return features


def find_spaced_arrays(seq, lo, hi, k=20, min_copies=4):
    """Regions of seq[lo:hi] where a k-mer recurs at a steady spacing. Returns 1-based (start, end, k-mer, copies, spacing)."""
    positions = defaultdict(list)
    for i in range(lo, hi - k):
        positions[seq[i : i + k]].append(i)
    arrays = []
    for kmer, where in positions.items():
        run = [where[0]]
        for p in where[1:] + [None]:
            if p is not None and 40 <= p - run[-1] <= 90:
                run.append(p)
                continue
            if len(run) >= min_copies:
                arrays.append((run[0] + 1, run[-1] + k, kmer, len(run), run[1] - run[0]))
            run = [p]
    # Many k-mers describe the same array: merge overlapping hits, keep the one with most copies.
    merged = []
    for hit in sorted(arrays):
        if merged and hit[0] <= merged[-1][1]:
            best = max(merged[-1], hit, key=lambda h: h[3])
            merged[-1] = (min(merged[-1][0], hit[0]), max(merged[-1][1], hit[1]), *best[2:])
        else:
            merged.append(hit)
    return merged


def revcomp(seq):
    return seq[::-1].translate(str.maketrans("ACGT", "TGCA"))


def overlaps(f, start, end):
    return f["start"] <= end and f["end"] >= start


def cut(seq, features, start, flip, target, rng_name):
    """Cut the window [start, start+length) (0-based) and express everything in window coordinates."""
    length = cut.length
    end = start + length
    window = seq[start:end]

    def local(a, b):  # genome 1-based inclusive -> window 1-based inclusive, clipped
        a, b = max(a, start + 1) - start, min(b, end) - start
        return (length - b + 1, length - a + 1) if flip else (a, b)

    annotated = []
    for f in features:
        if f["key"] in ("gene", "mobile_element") and overlaps(f, start + 1, end):
            a, b = local(f["start"], f["end"])
            name = f["quals"].get("gene") or f["quals"].get("mobile_element_type") or f["key"]
            annotated.append({"key": f["key"], "name": name, "start": a, "end": b, "pseudo": "pseudo" in f["quals"]})
    truth = {
        "length": length,
        "target": None,
        "annotated": sorted(annotated, key=lambda x: x["start"]),
        "source": {"accession": ACCESSION, "start": start + 1, "end": end, "strand": "-" if flip else "+"},
    }
    if target:
        a, b = local(target["start"], target["end"])
        truth["target"] = {**target, "start": a, "end": b}
    return (revcomp(window) if flip else window), truth


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("data/ecoli"))
    p.add_argument("--raw", type=Path, default=Path("data/raw"))
    p.add_argument("--length", type=int, default=3000)
    p.add_argument("--insertion-sequences", type=int, default=3)
    p.add_argument("--controls", type=int, default=6)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()
    cut.length = args.length
    rng = random.Random(args.seed)

    paths = download(args.raw)
    seq = "".join(l.strip() for l in paths["fasta"].read_text().splitlines() if not l.startswith(">")).upper()
    features = parse_feature_table(paths["ft"].read_text())
    mobile = [f for f in features if f["key"] == "mobile_element"]

    targets = []
    cas2 = next(f for f in features if f["key"] == "gene" and f["quals"].get("gene") == "cas2")
    for start, end, kmer, copies, spacing in find_spaced_arrays(
        seq, cas2["start"] - CRISPR_SEARCH_FLANK, cas2["end"] + CRISPR_SEARCH_FLANK
    ):
        targets.append(
            {
                "type": "repeat_array",
                "kind": "CRISPR repeat-spacer array",
                "name": f"array at {start}",
                "start": start,
                "end": end,
                "copies": copies,
                "period": spacing,
                "truth_source": "repeat search near annotated cas2; boundaries approximate; not in the GenBank annotation",
            }
        )

    # One complete insertion sequence from each of several families, away from other mobile elements.
    by_family = defaultdict(list)
    for f in mobile:
        kind = f["quals"].get("mobile_element_type", "")
        family = re.match(r"insertion sequence:(IS\d+)[A-Z]*$", kind)
        size = f["end"] - f["start"] + 1
        alone = not any(o is not f and overlaps(o, f["start"] - args.length, f["end"] + args.length) for o in mobile)
        if family and 700 <= size <= args.length - 600 and alone:
            by_family[family.group(1)].append(f)
    for family in rng.sample(sorted(by_family), args.insertion_sequences):
        f = rng.choice(by_family[family])
        targets.append(
            {
                "type": "mobile_element",
                "kind": "insertion sequence",
                "name": f["quals"]["mobile_element_type"].split(":")[1],
                "start": f["start"],
                "end": f["end"],
                "truth_source": "GenBank mobile_element feature",
            }
        )

    slipped = [f for f in features if f["key"] == "CDS" and "ribosomal_slippage" in f["quals"]]
    prfb = next(f for f in features if f["key"] == "gene" and f["quals"].get("gene") == "prfB")
    assert any(overlaps(s, prfb["start"], prfb["end"]) for s in slipped), "prfB is not annotated with ribosomal slippage"
    targets.append(
        {
            "type": "frameshift",
            "kind": "programmed ribosomal frameshift",
            "name": "prfB",
            "start": prfb["start"],
            "end": prfb["end"],
            "truth_source": "GenBank CDS with /ribosomal_slippage",
        }
    )

    windows = []
    for t in targets:
        slack = args.length - (t["end"] - t["start"] + 1)
        start = t["start"] - 1 - rng.randint(100, slack - 100)
        windows.append(cut(seq, features, start, rng.random() < 0.5, t, None))

    special = [f for f in features if f["key"] in NOT_ORDINARY or "pseudo" in f["quals"]]
    special += [{"start": t["start"], "end": t["end"]} for t in targets]
    taken = [w[1]["source"] for w in windows]
    while len(windows) < len(targets) + args.controls:
        start = rng.randrange(0, len(seq) - args.length)
        clear = not any(overlaps(f, start + 1 - 500, start + args.length + 500) for f in special)
        apart = not any(s["start"] <= start + args.length and s["end"] >= start + 1 for s in taken)
        if clear and apart:
            windows.append(cut(seq, features, start, rng.random() < 0.5, None, None))
            taken.append(windows[-1][1]["source"])

    rng.shuffle(windows)  # ids must not reveal the class
    loci_dir, truth_dir = args.out / "loci", args.out / "truth"
    loci_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    for i, (window, truth) in enumerate(windows, 1):
        name = f"region_{i:03d}"
        write_fasta(loci_dir / f"{name}.fasta", name, window)
        (truth_dir / f"{name}.json").write_text(json.dumps(truth, indent=2) + "\n")
        t = truth["target"]
        label = f"{t['kind']} {t['name']} at {t['start']}-{t['end']}" if t else "control"
        genes = ", ".join(a["name"] for a in truth["annotated"] if a["key"] == "gene")
        print(f"{name}  {truth['source']['start']}-{truth['source']['end']}{truth['source']['strand']}  {label}  [genes: {genes}]")


if __name__ == "__main__":
    main()
