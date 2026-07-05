from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt

# =========================
# CONFIG - modifici doar aici
# =========================

CSV_PATH = Path(r"delay_p99_graphs\delay_latency_avg99_aligned.csv")

OUT_IMAGE = Path(r"delay_p99_graphs\delay_p99_latency_bar_chart.png")
OUT_SUMMARY = Path(r"delay_p99_graphs\delay_p99_latency_summary_bar.csv")

TITLE = "Întârziere P99 (delay)"
Y_LABEL = "Întârzierea medie P99 (ms)"

# Dacă ai rânduri artificiale cu 0 la început, le scoate din medie
REMOVE_ZERO_ROWS = True

# Dacă vrei barele sortate crescător după întârziere
SORT_BARS = False


# =========================
# CITIRE CSV
# =========================

df = pd.read_csv(CSV_PATH)

# Coloane care NU sunt de întârziere
non_latency_columns = {"minute", "time", "elapsed_time", "elapsed_seconds"}

latency_columns = [
    col for col in df.columns
    if col.strip().lower() not in non_latency_columns
]

# Convertim toate coloanele de întârziere în numeric
for col in latency_columns:
    df[col] = pd.to_numeric(df[col], errors="coerce")

# Scoatem rândurile unde toate întârzierile sunt 0
# util dacă minutul 0 este artificial
if REMOVE_ZERO_ROWS:
    df = df[~df[latency_columns].fillna(0).eq(0).all(axis=1)]


# =========================
# CALCUL MEDII
# =========================

means = df[latency_columns].mean(skipna=True)

if SORT_BARS:
    means = means.sort_values()


# Salvăm și tabelul cu rezultate
summary = means.reset_index()
summary.columns = ["algorithm", "average_latency_ms"]
summary.to_csv(OUT_SUMMARY, index=False)


# =========================
# BAR CHART
# =========================

fig, ax = plt.subplots(figsize=(9, 5))

colors = {
    "RR": "#1f77b4",    # albastru
    "WRR": "#ff9900",   # portocaliu
    "LC": "#009e73",    # verde
    "SED": "#cc79a7",   # roz/mov
    "NQ": "#d55e00",    # roșu-portocaliu
}

bar_colors = [
    colors.get(str(algorithm), "#808080")
    for algorithm in means.index
]

bars = ax.bar(
    means.index,
    means.values,
    color=bar_colors,
    edgecolor="black",
    linewidth=0.8
)

ax.set_title(TITLE, fontsize=16, fontweight="bold")
ax.set_xlabel("Algoritm", fontsize=12, fontweight="bold")
ax.set_ylabel(Y_LABEL, fontsize=12, fontweight="bold")

ax.grid(axis="y", linestyle="--", alpha=0.4)
ax.set_axisbelow(True)

# Scrie valoarea deasupra fiecărui bar
for bar, value in zip(bars, means.values):
    ax.text(
        bar.get_x() + bar.get_width() / 2,
        bar.get_height(),
        f"{value:.2f} ms",
        ha="center",
        va="bottom",
        fontsize=10,
        fontweight="bold"
    )

# Lasă puțin spațiu sus pentru text
ax.set_ylim(0, means.max() * 1.18)

plt.tight_layout()

plt.savefig(OUT_IMAGE, dpi=300, bbox_inches="tight")
plt.show()