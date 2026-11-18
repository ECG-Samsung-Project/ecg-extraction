"""Session-only identification shared by extraction tabs (main Tk thread only)."""
import tkinter as tk


class IdentificationContext:
    def __init__(self, parent):
        self.values = {key: tk.StringVar(parent) for key in ("kit", "participant", "context")}
        self.kit_status = tk.StringVar(parent)
        self.participant_status = tk.StringVar(parent)
        self.busy = tk.BooleanVar(parent, False)
        self.lookup_busy = tk.BooleanVar(parent, False)
