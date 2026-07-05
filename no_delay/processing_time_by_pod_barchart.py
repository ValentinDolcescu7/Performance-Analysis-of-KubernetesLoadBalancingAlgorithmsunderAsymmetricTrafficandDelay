from pathlib import Path
import re
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

# ============================================================
# CONFIG
# ============================================================

DATA_DIR = Path(r"processing_time_by_pod")
ALGORITHM_ORDER = ["RR", "WRR", "LC", "SED", "NQ"]

OUT_DIR = DATA_DIR / "results"
OUT_DIR.mkdir(parents=True, exist_ok=True)

OUT_LONG_CSV = OUT_DIR / "processing_time_by_pod_long.csv"
OUT_WIDE_MINUTES_CSV = OUT_DIR / "processing_time_by_pod_wide_minutes.csv"
OUT_WIDE_PERCENT_CSV = OUT_DIR / "processing_time_by_pod_wide_percent.csv"

OUT_CHART_MINUTES = OUT_DIR / "processing_time_by_pod_all_algorithms_minutes.png"
OUT_CHART_PERCENT = OUT_DIR / "processing_time_by_pod_all_algorithms_percent.png"

TITLE_MINUTES = "Timp per pod"
TITLE_PERCENT = "Distribuție timp"

SHOW_VALUES_ON_BARS = True

# ============================================================
# FUNCȚII
# ============================================================

def find_total_csv(algorithm):
    """
    Caută automat fișierul CSV pentru un algoritm.
    Acceptă nume de forma:
      rr_Total.csv
      rr_Total processing time by pod-data-2026-06-13 12_52_17.csv
    """
    alg = algorithm.lower()
    candidates = []

    for file in DATA_DIR.glob("*.csv"):
        name = file.name.lower()
        if name.startswith(alg) and "total" in name:
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


def parse_time_to_seconds(value):
    """
    Convertește valori de forma:
      17.1 mins, 3.40 mins, 50 s, 400 ms, 100 µs
    în secunde.
    """
    if pd.isna(value):
        return np.nan

    if isinstance(value, (int, float, np.number)):
        return float(value)

    text = str(value).strip().replace(",", ".")
    if text == "":
        return np.nan

    match = re.match(r"^([-+]?\d+(?:\.\d+)?)\s*([a-zA-Zµμ]*)$", text)
    if not match:
        return np.nan

    number = float(match.group(1))
    unit = match.group(2).lower()

    if unit in ["", "s", "sec", "secs", "second", "seconds"]:
        return number
    if unit in ["m", "min", "mins", "minute", "minutes"]:
        return number * 60
    if unit in ["h", "hr", "hrs", "hour", "hours"]:
        return number * 3600
    if unit in ["ms", "millisecond", "milliseconds"]:
        return number / 1000
    if unit in ["us", "µs", "μs", "microsecond", "microseconds"]:
        return number / 1_000_000
    if unit in ["ns", "nanosecond", "nanoseconds"]:
        return number / 1_000_000_000

    return np.nan


def short_pod_name(pod_name):
    return str(pod_name).split("-")[-1]


def read_total_processing_csv(algorithm, csv_path):
    """
    Suportă două formate:
    1) long: Time,pod,Value
    2) wide: Time,pod1,pod2,pod3
    """
    print(f"{algorithm} -> {csv_path}")

    df = pd.read_csv(csv_path)
    df.columns = [str(c).strip() for c in df.columns]

    rows = []
    lower_cols = {c.lower(): c for c in df.columns}

    # format long
    if "pod" in lower_cols and "value" in lower_cols:
        pod_col = lower_cols["pod"]
        value_col = lower_cols["value"]

        df["value_seconds"] = df[value_col].apply(parse_time_to_seconds)
        grouped = df.groupby(pod_col, dropna=True)["value_seconds"].sum()

        for pod, total_seconds in grouped.items():
            rows.append({
                "algorithm": algorithm,
                "pod": pod,
                "pod_short": short_pod_name(pod),
                "total_seconds": total_seconds,
                "total_minutes": total_seconds / 60,
            })

        return rows

    # format wide
    ignored_columns = {"time", "timestamp"}
    pod_columns = [c for c in df.columns if c.lower() not in ignored_columns]

    for pod_col in pod_columns:
        values_seconds = df[pod_col].apply(parse_time_to_seconds)
        total_seconds = values_seconds.sum(skipna=True)

        rows.append({
            "algorithm": algorithm,
            "pod": pod_col,
            "pod_short": short_pod_name(pod_col),
            "total_seconds": total_seconds,
            "total_minutes": total_seconds / 60,
        })

    return rows


def make_grouped_bar_chart(wide_df, output_path, title, ylabel, value_mode):
    """
    value_mode:
      - 'minutes'
      - 'percent'
    """
    algorithms = wide_df.index.astype(str).tolist()
    pods = wide_df.columns.astype(str).tolist()

    palette = [
        "#1f77b4",  # albastru
        "#ff7f0e",  # portocaliu
        "#2ca02c",  # verde
        "#d62728",  # roșu
        "#9467bd",  # mov
        "#8c564b",  # maro
        "#e377c2",  # roz
        "#7f7f7f",  # gri
    ]

    pod_colors = {pod: palette[i % len(palette)] for i, pod in enumerate(pods)}

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
                    label = f"{value:.2f}"

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

    # legendă în dreapta jos
    ax.legend(
        title="Poduri",
        loc="upper right",
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
    csv_path = find_total_csv(algorithm)
    all_rows.extend(read_total_processing_csv(algorithm, csv_path))

long_df = pd.DataFrame(all_rows)

# total pe algoritm
long_df["algorithm_total_seconds"] = long_df.groupby("algorithm")["total_seconds"].transform("sum")
long_df["share_percent"] = long_df["total_seconds"] / long_df["algorithm_total_seconds"] * 100

# sortare
long_df["algorithm"] = pd.Categorical(
    long_df["algorithm"],
    categories=ALGORITHM_ORDER,
    ordered=True
)

long_df = long_df.sort_values(["algorithm", "pod_short"])

# wide pentru minute
wide_minutes_df = long_df.pivot_table(
    index="algorithm",
    columns="pod_short",
    values="total_minutes",
    aggfunc="sum",
    observed=False
).reindex(ALGORITHM_ORDER).fillna(0)

# wide pentru procente
wide_percent_df = long_df.pivot_table(
    index="algorithm",
    columns="pod_short",
    values="share_percent",
    aggfunc="sum",
    observed=False
).reindex(ALGORITHM_ORDER).fillna(0)

# salvare CSV
long_df.to_csv(OUT_LONG_CSV, index=False)
wide_minutes_df.to_csv(OUT_WIDE_MINUTES_CSV)
wide_percent_df.to_csv(OUT_WIDE_PERCENT_CSV)

# ============================================================
# GRAFICE
# ============================================================

make_grouped_bar_chart(
    wide_df=wide_minutes_df,
    output_path=OUT_CHART_MINUTES,
    title=TITLE_MINUTES,
    ylabel="Timp (minute)",
    value_mode="minutes"
)

make_grouped_bar_chart(
    wide_df=wide_percent_df,
    output_path=OUT_CHART_PERCENT,
    title=TITLE_PERCENT,
    ylabel="Timp (%)",
    value_mode="percent"
)

print("\nSalvat:")
print("CSV detaliat:", OUT_LONG_CSV)
print("CSV minute:", OUT_WIDE_MINUTES_CSV)
print("CSV procente:", OUT_WIDE_PERCENT_CSV)
print("Grafic minute:", OUT_CHART_MINUTES)
print("Grafic procente:", OUT_CHART_PERCENT)

print("\nDate minute:")
print(wide_minutes_df)

print("\nDate procente:")
print(wide_percent_df)