"""Draw the README figures from the saved run records, in light and dark versions.

Writes plain SVG with no plotting library, so the figures can be rebuilt
from the repository root:  python src/make_figures.py
"""
import json
from pathlib import Path

from analyze import score, target_of
from ask_direct import QUESTIONS, covers

OUT = Path("docs/figures")
TRUTH = Path("data/ecoli/truth")
FONT = "-apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
THEMES = {
    "light": {"text": "#0b0b0b", "muted": "#52514e", "grid": "#e4e3df", "series": "#2a78d6",
              "ramp": ["#86b6ef", "#2a78d6", "#104281"]},
    "dark": {"text": "#ffffff", "muted": "#c3c2b7", "grid": "#3a3a37", "series": "#3987e5",
             "ramp": ["#184f95", "#3987e5", "#9ec5f4"]},
}
MODELS = {  # folder name -> display name, in the order shown
    "deepseek-v4.1-flash": "DeepSeek V4.1 Flash",
    "glm-5.3-flash": "GLM-5.3 Flash",
    "glm-5.2": "GLM-5.2",
    "hy3": "Hy3",
    "omen-alpha": "Omen Alpha",
    "longcat-2.5-preview-free": "LongCat 2.5 Preview",
    "space-bunny-free": "Space Bunny",
}
PILOT_DIRS = ("results/sandbox_pilot",)
TARGETS = {  # truth target type -> column label
    "repeat_array": "CRISPR array",
    "mobile_element": "Insertion sequence",
    "frameshift": "Frameshifted gene",
}


def truth_for(locus):
    return json.loads((TRUTH / f"{locus}.json").read_text())


def open_ended():
    """model -> target type -> [located, scored runs] for the open-ended task."""
    table = {}
    for folder in PILOT_DIRS:
        for path in sorted(Path(folder).glob("*/region_*.json")):
            record = json.loads(path.read_text())
            target = target_of(truth_for(record["locus"]))
            s = score(record, truth_for(record["locus"]))
            if target is None or s is None:
                continue
            cell = table.setdefault(path.parent.name, {}).setdefault(target["type"], [0, 0])
            cell[0] += s["localized"]
            cell[1] += 1
    return table


def direct(folder):
    """target type -> [answered yes and placed it on the feature, runs] on windows that hold the feature."""
    counts = {}
    for path in sorted(Path(folder).glob("*/*/*.json")):
        record = json.loads(path.read_text())
        target = target_of(truth_for(record["locus"]))
        kind = QUESTIONS[record["question"]][0]
        if target is None or target["type"] != kind:
            continue
        cell = counts.setdefault(kind, [0, 0])
        cell[0] += bool(record["answer"]) and covers(record["answer_span"], target)
        cell[1] += 1
    return counts


def text(x, y, s, fill, size=13, anchor="start", weight="normal"):
    return (f'<text x="{x}" y="{y}" fill="{fill}" font-size="{size}" text-anchor="{anchor}" '
            f'font-weight="{weight}">{s}</text>')


def svg(width, height, body):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" '
            f'height="{height}" font-family="{FONT}">\n' + "\n".join(body) + "\n</svg>\n")


def asked_figure(theme, series):
    """Grouped bars: how often each hard feature was found, by how the agent was asked."""
    c = THEMES[theme]
    width, height, left, right, top, bottom = 680, 330, 56, 664, 64, 264
    body = []
    for i, (label, _) in enumerate(series):  # legend row
        x = left + i * 196
        body.append(f'<rect x="{x}" y="14" width="12" height="12" rx="2" fill="{c["ramp"][i]}"/>')
        body.append(text(x + 18, 25, label, c["muted"], 12.5))
    for pct in (0, 25, 50, 75, 100):
        y = bottom - (bottom - top) * pct / 100
        body.append(f'<line x1="{left}" x2="{right}" y1="{y}" y2="{y}" stroke="{c["grid"]}" stroke-width="1"/>')
        body.append(text(left - 8, y + 4, f"{pct}%", c["muted"], 12, "end"))
    bar, gap = 24, 30
    for g, kind in enumerate(("mobile_element", "frameshift")):
        centre = left + (right - left) * (0.27 + 0.46 * g)
        for i, (_, counts) in enumerate(series):
            hit, n = counts[kind]
            x = centre + (i - 1) * (bar + gap) - bar / 2
            h = max((bottom - top) * hit / n, 2)  # a zero still gets a visible stub
            y = bottom - h
            r = min(4, h)
            body.append(f'<path d="M{x},{bottom} V{y + r} Q{x},{y} {x + r},{y} H{x + bar - r} '
                        f'Q{x + bar},{y} {x + bar},{y + r} V{bottom} Z" fill="{c["ramp"][i]}"/>')
            body.append(text(x + bar / 2, y - 7, f"{hit} of {n}", c["text"], 12.5, "middle", "600"))
        body.append(text(centre, bottom + 24, TARGETS[kind], c["text"], 13.5, "middle", "600"))
        body.append(text(centre, bottom + 42, "IS5" if kind == "mobile_element" else "prfB", c["muted"], 12, "middle"))
    body.append(text(left, 50, "runs that found the feature and placed it correctly", c["muted"], 12))
    return svg(width, height, body)


def grid_figure(theme, table):
    """Dot matrix: which model found which feature on the open-ended task."""
    c = THEMES[theme]
    columns = [330, 462, 594]
    row_height, top = 34, 58
    rows = [m for m in MODELS if m in table]
    width, height = 680, top + row_height * len(rows) + 40
    body = [text(x, 28, label, c["text"], 13.5, "middle", "600") for x, label in zip(columns, TARGETS.values())]
    body.append(f'<line x1="24" x2="{width - 24}" y1="40" y2="40" stroke="{c["grid"]}" stroke-width="1"/>')
    for i, model in enumerate(rows):
        y = top + i * row_height
        body.append(text(24, y + 4, MODELS[model], c["text"], 13.5))
        for x, kind in zip(columns, TARGETS):
            hit, n = table[model].get(kind, (0, 0))
            if n and hit == n:
                body.append(f'<circle cx="{x - 16}" cy="{y}" r="8" fill="{c["series"]}"/>')
            else:
                body.append(f'<circle cx="{x - 16}" cy="{y}" r="7" fill="none" stroke="{c["muted"]}" stroke-width="1.5"/>')
            body.append(text(x, y + 4, f"{hit} of {n}", c["muted"], 12.5))
    y = top + row_height * len(rows) + 12
    body.append(f'<circle cx="32" cy="{y - 4}" r="6" fill="{c["series"]}"/>')
    body.append(text(46, y, "found in every run", c["muted"], 12))
    body.append(f'<circle cx="190" cy="{y - 4}" r="5.5" fill="none" stroke="{c["muted"]}" stroke-width="1.5"/>')
    body.append(text(204, y, "never found", c["muted"], 12))
    return svg(width, height, body)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    table = open_ended()
    pooled = {kind: [sum(m.get(kind, (0, 0))[i] for m in table.values()) for i in (0, 1)] for kind in TARGETS}
    series = [
        ("Open-ended, all models", pooled),
        ("Asked directly, short run", direct("results/direct_questions/15_turns")),
        ("Asked directly, long run", direct("results/direct_questions/30_turns")),
    ]
    for theme in THEMES:
        (OUT / f"asked-{theme}.svg").write_text(asked_figure(theme, series))
        (OUT / f"models-{theme}.svg").write_text(grid_figure(theme, table))
    print("open-ended, all models:", pooled)
    for label, counts in series[1:]:
        print(f"{label}:", counts)
    print("models:", {MODELS[m]: table[m] for m in MODELS if m in table})


if __name__ == "__main__":
    main()
