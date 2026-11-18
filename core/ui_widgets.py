import tkinter as tk
from tkinter import ttk


class PlaceholderEntry(ttk.Entry):
    """Paint a hint without putting it in the entry's value or clipboard."""
    def __init__(self, parent, *, textvariable, placeholder, **kwargs):
        super().__init__(parent, textvariable=textvariable, **kwargs)
        self.variable = textvariable
        self.focused = False
        background = ttk.Style(self).lookup("TEntry", "fieldbackground") or "white"
        self.hint = tk.Label(self, text=placeholder, foreground="#757575", background=background,
                             font="TkTextFont", borderwidth=0, padx=0, pady=0, cursor="xterm")
        self.hint.bind("<Button-1>", self.focus_entry)
        self.bind("<FocusIn>", lambda _event: self.set_focused(True), add="+")
        self.bind("<FocusOut>", lambda _event: self.set_focused(False), add="+")
        self.trace = self.variable.trace_add("write", self.update_hint)
        self.bind("<Destroy>", self.remove_trace, add="+")
        self.update_hint()

    def focus_entry(self, _event):
        if not self.instate(["disabled"]):
            self.focus_set()
            self.set_focused(True)

    def set_focused(self, focused):
        self.focused = focused
        self.update_hint()

    def update_hint(self, *_args):
        if not self.variable.get() and not self.focused:
            self.hint.place(x=4, rely=0.5, anchor="w")
        else:
            self.hint.place_forget()

    def remove_trace(self, event):
        if event.widget is self:
            self.variable.trace_remove("write", self.trace)


