from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path(r"processing_reqs_by_pod")
ALGORITHM_ORDER = ["RR", "WRR", "LC", "SED", "NQ"]

OUT_DIR = DATA_DIR / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_LONG_CSV = OUT_DIR / "total_requests_by_pod_long.csv"
OUT_WIDE_COUNT_CSV = OUT_DIR / "total_requests_by_pod_wide_count_raw.csv"
OUT_WIDE_NORMALIZED_CSV = OUT_DIR / "total_requests_by_pod_wide_count_normalized.csv"
OUT_WIDE_PERCENT_CSV = OUT_DIR / "total_requests_by_pod_wide_percent.csv"

OUT_CHART_COUNT_RAW = OUT_DIR / "total_requests_by_pod_raw_count.png"
OUT_CHART_COUNT_NORMALIZED = OUT_DIR / "total_requests_by_pod_normalized_count.png"
OUT_CHART_PERCENT = OUT_DIR / "total_requests_by_pod_percent.png"

TITLE_COUNT_RAW = "Cereri per pod"
TITLE_COUNT_NORMALIZED = "Cereri normalizate"
TITLE_PERCENT = "Distribuție cereri"

SHOW_VALUES_ON_BARS = True

# Dacă vrei să forțezi manual 318000, pui:
# TARGET_TOTAL_REQUESTS = 318000
# Dacă lași None, scriptul ia automat cel mai mic total din CSV-uri.
TARGET_TOTAL_REQUESTS = None


# ============================================================
# FUNCȚII
# ============================================================

def find_requests_csv(algorithm):
    alg = algorithm.lower()
    candidates = []

    for file in DATA_DIR.glob("*.csv"):
        name = file.name.lower()

        if name.startswith(alg) and ("request" in name or "total" in name):
            candidates.append(file)

    if not candidates:
        found = [f.name for f in DATA_DIR.glob("*.csv")]
        raise FileNotFoundError(
            f"Nu am găsit CSV pentru {algorithm} în {DATA_DIR.resolve()}\n"
            f"Fișiere găsite: {found}"
        )

    if len(candidates) > 1:
        print(f"Atenție: mai multe CSV-uri pentru {algorithm}, îl folosesc pe primul:")
        for c in candidates:
            print(" -", c.name)

    return candidates[0]


def parse_number(value):
    """
    Convertește valori Grafana în numere:
      12400
      12,400
      12.4k
      1.2M
      200 req
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.number)):
        return float(value)

    text = str(value).strip().replace(",", "")

    if text == "":
        return np.nan

    match = re.match(
        r"^([-+]?\d+(?:\.\d+)?)\s*([kKmMbB]?)(?:\s*[a-zA-Z/]+)?$",
        text
    )

    if not match:
        return np.nan

    number = float(match.group(1))
    suffix = match.group(2).lower()

    if suffix == "k":
        return number * 1_000
    if suffix == "m":
        return number * 1_000_000
    if suffix == "b":
        return number * 1_000_000_000

    return number


def short_pod_name(pod_name):
    """
    podinfo-5bfbdcc5f9-84sd6 -> 84sd6
    """
    return str(pod_name).split("-")[-1]


def format_k(value, _):
    """
    Formatare axă Y:
      318000 -> 318k
    """
    if abs(value) >= 1_000_000:
        return f"{value / 1_000_000:.1f}M"

    if abs(value) >= 1_000:
        return f"{value / 1_000:.0f}k"

    return f"{value:.0f}"


def read_total_requests_csv(algorithm, csv_path):
    print(f"{algorithm} -> {csv_path}")

    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    lower_cols = {c.lower(): c for c in df.columns}

    # Format long: Time,pod,Value
    if "pod" in lower_cols and "value" in lower_cols:
        pod_col = lower_cols["pod"]
        value_col = lower_cols["value"]

        df["value_number"] = df[value_col].apply(parse_number)
        grouped = df.groupby(pod_col, dropna=True)["value_number"].sum()

        for pod, total_requests in grouped.items():
            rows.append({
                "algorithm": algorithm,
                "pod": pod,
                "pod_short": short_pod_name(pod),
                "total_requests": total_requests,
            })

        return rows

    # Format wide: Time,pod1,pod2,pod3
    ignored_columns = {"time", "timestamp"}
    pod_columns = [c for c in df.columns if c.lower() not in ignored_columns]

    for pod_col in pod_columns:
        values = df[pod_col].apply(parse_number)
        total_requests = values.sum(skipna=True)

        rows.append({
            "algorithm": algorithm,
            "pod": pod_col,
            "pod_short": short_pod_name(pod_col),
            "total_requests": total_requests,
        })

    return rows


def make_grouped_bar_chart(wide_df, output_path, title, ylabel, value_mode):
    algorithms = wide_df.index.astype(str).tolist()
    pods = wide_df.columns.astype(str).tolist()

    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
    ]

    pod_colors = {
        pod: palette[i % len(palette)]
        for i, pod in enumerate(pods)
    }

    x = np.arange(len(algorithms))
    number_of_pods = len(pods)
    bar_width = min(0.22, 0.80 / max(number_of_pods, 1))

    fig, ax = plt.subplots(figsize=(14, 7))

    for i, pod in enumerate(pods):
        offset = (i - (number_of_pods - 1) / 2) * bar_width
        values = wide_df[pod].values

        bars = ax.bar(
            x + offset,
            values,
            width=bar_width,
            label=f"pod {pod}",
            color=pod_colors[pod],
            edgecolor="black",
            linewidth=0.8,
        )

        if SHOW_VALUES_ON_BARS:
            for bar, value in zip(bars, values):
                if value <= 0:
                    continue

                if value_mode == "percent":
                    label = f"{value:.1f}%"
                else:
                    label = f"{value / 1000:.1f}k"

                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height(),
                    label,
                    ha="center",
                    va="bottom",
                    fontsize=9,
                    fontweight="bold",
                )

    ax.set_title(title, fontsize=17, fontweight="bold", pad=16)
    ax.set_xlabel("Planificator", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")

    ax.set_xticks(x)
    ax.set_xticklabels(algorithms, fontsize=12, fontweight="bold")

    ax.grid(axis="y", linestyle="--", alpha=0.4)
    ax.set_axisbelow(True)

    if value_mode != "percent":
        ax.yaxis.set_major_formatter(FuncFormatter(format_k))

    ax.legend(
        title="Poduri",
        loc="upper left",
        frameon=True
    )

    max_value = wide_df.to_numpy().max()
    ax.set_ylim(0, max_value * 1.22 if max_value > 0 else 1)

    plt.tight_layout()
    plt.savefig(output_path, dpi=300, bbox_inches="tight")
    plt.show()


# ============================================================
# CITIRE CSV + PRELUCRARE
# ============================================================

all_rows = []

for algorithm in ALGORITHM_ORDER:
    csv_path = find_requests_csv(algorithm)
    all_rows.extend(read_total_requests_csv(algorithm, csv_path))

long_df = pd.DataFrame(all_rows)

if long_df.empty:
    raise ValueError("Nu s-au citit date. Verifică fișierele CSV și folderul DATA_DIR.")

# total request-uri per algoritm
long_df["algorithm_total_requests"] = (
    long_df.groupby("algorithm")["total_requests"].transform("sum")
)

# procent pe pod din totalul algoritmului
long_df["share_percent"] = (
    long_df["total_requests"] / long_df["algorithm_total_requests"] * 100
)

# totalurile reale per algoritm
algorithm_totals = long_df.groupby("algorithm")["total_requests"].sum()

# target de normalizare: cel mai mic total real sau valoarea setată manual
if TARGET_TOTAL_REQUESTS is None:
    target_total_requests = algorithm_totals.min()
else:
    target_total_requests = float(TARGET_TOTAL_REQUESTS)

# factor de scalare pentru fiecare algoritm
scale_factor_by_algorithm = target_total_requests / algorithm_totals

long_df["scale_factor"] = long_df["algorithm"].map(scale_factor_by_algorithm)

# request-uri normalizate la cel mai mic total
long_df["normalized_requests"] = (
    long_df["total_requests"] * long_df["scale_factor"]
)

# sortare
long_df["algorithm"] = pd.Categorical(
    long_df["algorithm"],
    categories=ALGORITHM_ORDER,
    ordered=True
)

long_df = long_df.sort_values(["algorithm", "pod_short"])

# wide raw count
wide_count_df = long_df.pivot_table(
    index="algorithm",
    columns="pod_short",
    values="total_requests",
    aggfunc="sum",
    observed=False
).reindex(ALGORITHM_ORDER).fillna(0)

# wide normalized count
wide_normalized_df = long_df.pivot_table(
    index="algorithm",
    columns="pod_short",
    values="normalized_requests",
    aggfunc="sum",
    observed=False
).reindex(ALGORITHM_ORDER).fillna(0)

# wide percent
wide_percent_df = long_df.pivot_table(
    index="algorithm",
    columns="pod_short",
    values="share_percent",
    aggfunc="sum",
    observed=False
).reindex(ALGORITHM_ORDER).fillna(0)

# salvare CSV
long_df.to_csv(OUT_LONG_CSV, index=False)
wide_count_df.to_csv(OUT_WIDE_COUNT_CSV)
wide_normalized_df.to_csv(OUT_WIDE_NORMALIZED_CSV)
wide_percent_df.to_csv(OUT_WIDE_PERCENT_CSV)


# ============================================================
# GRAFICE
# ============================================================

make_grouped_bar_chart(
    wide_df=wide_count_df,
    output_path=OUT_CHART_COUNT_RAW,
    title=TITLE_COUNT_RAW,
    ylabel="Cereri",
    value_mode="count"
)

make_grouped_bar_chart(
    wide_df=wide_normalized_df,
    output_path=OUT_CHART_COUNT_NORMALIZED,
    title=TITLE_COUNT_NORMALIZED,
    # ylabel=f"Cereri normalizate, scalate la {target_total_requests / 1000:.1f}k cereri totale",
    ylabel=f"Cereri",
    value_mode="count"
)

make_grouped_bar_chart(
    wide_df=wide_percent_df,
    output_path=OUT_CHART_PERCENT,
    title=TITLE_PERCENT,
    ylabel="Cereri (%)",
    value_mode="percent"
)


# ============================================================
# PRINT OUTPUT
# ============================================================

print("\nTotal cereri reale per planificator:")
print(algorithm_totals)

print(f"\nTarget normalizare: {target_total_requests:,.0f} cereri")

print("\nFactori de scalare:")
print(scale_factor_by_algorithm)

print("\nSalvat:")
print("CSV detaliat:", OUT_LONG_CSV)
print("CSV număr brut:", OUT_WIDE_COUNT_CSV)
print("CSV număr normalizat:", OUT_WIDE_NORMALIZED_CSV)
print("CSV procente:", OUT_WIDE_PERCENT_CSV)
print("Grafic număr brut:", OUT_CHART_COUNT_RAW)
print("Grafic număr normalizat:", OUT_CHART_COUNT_NORMALIZED)
print("Grafic procente:", OUT_CHART_PERCENT)

print("\nDate număr brut:")
print(wide_count_df)

print("\nDate număr normalizat:")
print(wide_normalized_df)

print("\nDate procente:")
print(wide_percent_df)