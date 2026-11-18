# main.py

import tkinter as tk
from tkinter import messagebox, ttk

from api import ApiClient, AuthSession, OfflineSession
from auth.frontend import create_login_frame
from core.identification import IdentificationContext

from watch.frontend import create_watch_frame
from mobile.frontend import create_mobile_frame
from server_sync.frontend import create_server_sync_frame


def run_app() -> None:
    root = None
    heartbeat = None
    try:
        root = tk.Tk()
        report_error = root.report_callback_exception

        def report_callback_exception(exc_type, value, traceback):
            # Tk catches exceptions raised inside callbacks, including Ctrl+C.
            if issubclass(exc_type, KeyboardInterrupt):
                root.quit()
            else:
                report_error(exc_type, value, traceback)

        def poll_interrupts():
            nonlocal heartbeat
            # Periodically return to Python so SIGINT is handled while Tk is idle.
            heartbeat = root.after(100, poll_interrupts)

        root.report_callback_exception = report_callback_exception
        poll_interrupts()
        _run_application(root)
    except KeyboardInterrupt:
        # A user-requested interruption is a normal application exit.
        pass
    finally:
        if root is not None:
            try:
                if heartbeat is not None:
                    root.after_cancel(heartbeat)
                root.destroy()
            except tk.TclError:
                # The window may already have been destroyed by its close button.
                pass


def _run_application(root: tk.Tk) -> None:
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

        identification = IdentificationContext(root)
        watch_frame = create_watch_frame(notebook, api_client=client, identification=identification)
        mobile_frame = create_mobile_frame(notebook, api_client=client, identification=identification)

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
