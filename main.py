# main.py

import tkinter as tk
from tkinter import messagebox, ttk

from api import ApiClient, AuthSession, OfflineSession
from auth.frontend import create_login_frame

from watch.frontend import create_watch_frame
from mobile.frontend import create_mobile_frame
from server_sync.frontend import create_server_sync_frame


def run_app() -> None:
    root = tk.Tk()
    root.title("Extração")

    root.state("zoomed")
    root.minsize(900, 650)
    root.resizable(True, True)

    try:
        client = ApiClient()
    except ValueError as error:
        messagebox.showerror("Configuração da API", str(error), parent=root)
        root.destroy()
        return

    notebook = None

    def show_application(session: AuthSession | OfflineSession) -> None:
        nonlocal notebook
        offline = isinstance(session, OfflineSession)
        if notebook is not None:
            return
        if offline and client.offline_session is not session:
            return
        if not offline and client.session is None:
            return
        login_frame.destroy()
        if offline:
            ttk.Label(root, text=f"Modo offline — Operador: {session.operator_name} — "
                      "Reabra o aplicativo para entrar com login.", padding=8).pack(fill="x")
        else:
            user = session.user
            ttk.Label(root, text=f"Usuário autenticado — {user.full_name} "
                      f"({user.username}) — Perfil: {user.role}", padding=8).pack(fill="x")
        notebook = ttk.Notebook(root)
        notebook.pack(fill="both", expand=True)

        watch_frame = create_watch_frame(notebook)
        mobile_frame = create_mobile_frame(notebook)

        notebook.add(watch_frame, text="Watch")
        notebook.add(mobile_frame, text="Mobile")
        if offline:
            server_sync_frame = ttk.Frame(notebook)
            notebook.add(server_sync_frame, text="Enviar ao Servidor", state="disabled")
        else:
            server_sync_frame = create_server_sync_frame(notebook)
            notebook.add(server_sync_frame, text="Enviar ao Servidor")

    login_frame = create_login_frame(root, client, show_application)
    login_frame.pack(fill="both", expand=True)

    root.mainloop()


if __name__ == "__main__":
    run_app()
