"""Generate synthetic DNA regions with and without a planted repeat array.

Positives carry one array of near-identical repeat units, either back to back
or separated by unique spacers. Negatives are random sequence of the same
length and GC content. Ground truth goes to a separate directory so it can
never end up in an agent's workspace.
"""
import argparse
import json
import random
from pathlib import Path

LINE_WIDTH = 70
FLANK_MIN = 200


def rand_seq(rng, n, gc):
    weights = [(1 - gc) / 2, gc / 2, gc / 2, (1 - gc) / 2]
    return "".join(rng.choices("ACGT", weights=weights, k=n))


def mutate(rng, seq, rate):
    return "".join(
        rng.choice([b for b in "ACGT" if b != base]) if rng.random() < rate else base
        for base in seq
    )


def make_positive(rng, length, gc):
    unit_len = rng.randint(20, 45)
    copies = rng.randint(4, 10)
    spaced = rng.random() < 0.5
    mutation_rate = rng.choice([0.0, 0.02, 0.05])
    unit = rand_seq(rng, unit_len, gc)

    parts = []
    for i in range(copies):
        parts.append(mutate(rng, unit, mutation_rate))
        if spaced and i < copies - 1:
            parts.append(rand_seq(rng, rng.randint(30, 60), gc))
    array = "".join(parts)

    start = rng.randint(FLANK_MIN, length - len(array) - FLANK_MIN)
    seq = rand_seq(rng, start, gc) + array
    seq += rand_seq(rng, length - len(seq), gc)
    truth = {
        "has_array": True,
        "start": start + 1,  # 1-based, inclusive
        "end": start + len(array),
        "unit": unit,
        "unit_len": unit_len,
        "copies": copies,
        "spaced": spaced,
        "mutation_rate": mutation_rate,
    }
    return seq, truth


def make_negative(rng, length, gc):
    return rand_seq(rng, length, gc), {"has_array": False}


def write_fasta(path, name, seq):
    lines = [seq[i : i + LINE_WIDTH] for i in range(0, len(seq), LINE_WIDTH)]
    path.write_text(f">{name}\n" + "\n".join(lines) + "\n")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--positives", type=int, default=5)
    p.add_argument("--negatives", type=int, default=5)
    p.add_argument("--length", type=int, default=3000)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--out", type=Path, default=Path("data/synthetic"))
    args = p.parse_args()

    rng = random.Random(args.seed)
    makers = [make_positive] * args.positives + [make_negative] * args.negatives
    rng.shuffle(makers)  # ids must not reveal the class

    loci_dir, truth_dir = args.out / "loci", args.out / "truth"
    loci_dir.mkdir(parents=True, exist_ok=True)
    truth_dir.mkdir(parents=True, exist_ok=True)
    for i, make in enumerate(makers, 1):
        name = f"locus_{i:03d}"
        seq, truth = make(rng, args.length, gc=rng.uniform(0.35, 0.55))
        truth["length"] = len(seq)
        write_fasta(loci_dir / f"{name}.fasta", name, seq)
        (truth_dir / f"{name}.json").write_text(json.dumps(truth, indent=2) + "\n")
    print(f"wrote {len(makers)} loci to {loci_dir} (truth in {truth_dir})")


if __name__ == "__main__":
    main()
