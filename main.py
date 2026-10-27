# main.py

import tkinter as tk
from tkinter import ttk

from watch.frontend import create_watch_frame
from mobile.frontend import create_mobile_frame
from server_sync.frontend import create_server_sync_frame


def run_app() -> None:
    root = tk.Tk()
    root.title("Extração")

    root.state("zoomed")  # abre maximizado no Windows
    root.minsize(900, 650)
    root.resizable(True, True)

    notebook = ttk.Notebook(root)
    notebook.pack(fill="both", expand=True)

    watch_frame = create_watch_frame(notebook)
    mobile_frame = create_mobile_frame(notebook)
    server_sync_frame = create_server_sync_frame(notebook)

    notebook.add(watch_frame, text="Watch")
    notebook.add(mobile_frame, text="Mobile")
    notebook.add(server_sync_frame, text="Enviar ao Servidor")

    root.mainloop()


if __name__ == "__main__":
    run_app()
