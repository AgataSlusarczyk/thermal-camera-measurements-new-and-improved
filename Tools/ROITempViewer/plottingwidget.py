from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure


class PlotCanvas(FigureCanvasQTAgg):

    def __init__(self, parent=None):
        fig = Figure(figsize=(5, 4), dpi=100)
        self.ax = fig.add_subplot(111)
        super().__init__(fig)
        self.setParent(parent)

        self._marker_lines = []

    def plot_data(self, t_s, series_dict):

        self.ax.clear()
        self.ax.grid(True)

        if t_s is not None and series_dict:
            for label, (y_values, color) in series_dict.items():
                self.ax.plot(t_s, y_values, label=label, color=color)

            self.ax.set_xlabel("Czas [s]")
            self.ax.set_ylabel("Temperatura [°C]")
            self.ax.legend(loc="best")
        else:
            self.ax.set_xlabel("Czas [s]")
            self.ax.set_ylabel("Temperatura [°C]")

        self.ax.figure.tight_layout()

        self._marker_lines = []

        self.draw()

    # MARKERY 

    def add_marker(self, x_pos, color="black", linestyle="--"):
        line = self.ax.axvline(x_pos, color=color, linestyle=linestyle, linewidth=1.0)
        self._marker_lines.append(line)
        self.draw()
        return line

    def remove_marker(self, line):
        if line in self._marker_lines:
            line.remove()
            self._marker_lines.remove(line)
            self.draw()

    def clear_markers(self):
        for ln in self._marker_lines:
            try:
                ln.remove()
            except Exception:
                pass
        self._marker_lines = []
        self.draw()

    def save_png(self, filepath: str):
        self.ax.figure.savefig(filepath, dpi=150)
