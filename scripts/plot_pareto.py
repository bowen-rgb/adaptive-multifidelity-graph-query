"""Optional plot of exported optimization candidates (requires matplotlib)."""
import argparse
import csv
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folder', type=Path)
    args = parser.parse_args()
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    with (args.folder / 'candidates.csv').open(newline='', encoding='utf-8') as file:
        rows = list(csv.DictReader(file))
    scenarios = sorted({int(r['reuse_requests']) for r in rows})
    columns = min(2, len(scenarios))
    fig, axes = plt.subplots((len(scenarios) + columns - 1) // columns, columns,
                             figsize=(10, 8), squeeze=False)
    for ax, requests in zip(axes.flat, scenarios):
        for pareto, color, label in ((True, '#16856b', 'Pareto'), (False, '#a1a1aa', 'Dominated')):
            selected = [r for r in rows if int(r['reuse_requests']) == requests
                        and (r['exhaustive_pareto'] == 'True') == pareto]
            ax.scatter([100 * float(r['edge_error_mean']) for r in selected],
                       [float(r['modeled_cost_ms']) for r in selected], color=color, label=label, s=65)
            for row in selected:
                ax.annotate(f"{100 * float(row['fidelity']):g}%",
                    (100 * float(row['edge_error_mean']), float(row['modeled_cost_ms'])),
                    xytext=(4, -15 if float(row['fidelity']) == 0.75 else 6),
                    textcoords='offset points', fontsize=9)
        ax.set_title(f'R = {requests} requests/sample' + (' (measured length)' if requests == 100 else ' (modeled)'))
        ax.set_xlabel('Mean edge error (%)')
        ax.set_ylabel('Modeled cost per COUNT pair (ms, log scale)')
        ax.set_yscale('log')
        ax.margins(x=0.13, y=0.22)
        ax.grid(alpha=0.2)
        ax.legend()
    for ax in list(axes.flat)[len(scenarios):]:
        ax.set_visible(False)
    fig.suptitle('Fronts use cost + node error + edge error; projection shown below')
    fig.tight_layout()
    fig.savefig(args.folder / 'pareto-scenarios.png', dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    main()
