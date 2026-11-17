import queue
import threading
import tkinter as tk
from tkinter import simpledialog, ttk
from typing import Callable

from api import ApiClient, ApiError, AuthSession, OfflineSession


def create_login_frame(parent: tk.Widget, client: ApiClient,
                       on_success: Callable[[AuthSession | OfflineSession], None]) -> ttk.Frame:
    frame = ttk.Frame(parent)
    frame.columnconfigure(0, weight=1)
    frame.rowconfigure(0, weight=1)
    style = ttk.Style(frame)
    style.configure("Login.TButton", font=("Arial", 13), padding=(16, 10))
    style.configure("LoginPrimary.TButton", font=("Arial", 14, "bold"), padding=(20, 12))

    panel = ttk.Frame(frame, padding=24)
    panel.grid(row=0, column=0, padx=24, pady=(24, 0))
    ttk.Label(panel, text="Entrar no ECG", font=("Arial", 26, "bold")).grid(
        row=0, column=0, columnspan=3, pady=(0, 32)
    )
    ttk.Label(panel, text="Usuário", font=("Arial", 14)).grid(
        row=1, column=0, sticky="e", padx=(0, 16), pady=10
    )
    username = ttk.Entry(panel, width=28, font=("Arial", 14))
    username.grid(row=1, column=1, sticky="ew", ipady=8, pady=10)
    ttk.Label(panel, text="Senha", font=("Arial", 14)).grid(
        row=2, column=0, sticky="e", padx=(0, 16), pady=10
    )
    password = ttk.Entry(panel, width=28, show="*", font=("Arial", 14))
    password.grid(row=2, column=1, sticky="ew", ipady=8, pady=10)
    password_visible = False

    def toggle_password() -> None:
        nonlocal password_visible
        if busy or closed:
            return
        password_visible = not password_visible
        password.configure(show="" if password_visible else "*")
        visibility_button.configure(
            text="Ocultar senha" if password_visible else "Mostrar senha"
        )

    visibility_button = ttk.Button(panel, text="Mostrar senha", command=toggle_password,
                                   style="Login.TButton", width=14)
    visibility_button.grid(row=2, column=2, padx=(16, 0), pady=10)
    status = tk.StringVar(value="")
    ttk.Label(panel, textvariable=status, wraplength=600, font=("Arial", 12),
              justify="center").grid(row=3, column=0, columnspan=3, pady=(12, 8))
    results: queue.Queue[AuthSession | str] = queue.Queue()
    busy = False
    closed = False
    poll_id: str | None = None

    def destroy(event: tk.Event) -> None:
        nonlocal closed
        if event.widget is frame:
            closed = True
            if poll_id is not None:
                frame.after_cancel(poll_id)

    frame.bind("<Destroy>", destroy, add="+")

    def poll() -> None:
        nonlocal busy, poll_id
        poll_id = None
        if closed:
            return
        try:
            result = results.get_nowait()
        except queue.Empty:
            poll_id = frame.after(100, poll)
            return
        busy = False
        for widget in (username, password, button, visibility_button, offline_button):
            widget.configure(state="normal")
        password.delete(0, tk.END)
        if isinstance(result, AuthSession):
            on_success(result)
        else:
            status.set(result)
            password.focus_set()

    def submit(_event: tk.Event | None = None) -> str:
        nonlocal busy, poll_id, password_visible
        if busy or closed:
            return "break"
        user_value, password_value = username.get(), password.get()
        if not user_value or not password_value:
            status.set("Informe o usuário e a senha.")
            return "break"
        busy = True
        password_visible = False
        password.configure(show="*")
        visibility_button.configure(text="Mostrar senha")
        status.set("Autenticando...")
        for widget in (username, password, button, visibility_button, offline_button):
            widget.configure(state="disabled")

        def worker() -> None:
            try:
                results.put(client.login(user_value, password_value))
            except ApiError as error:
                results.put(str(error))
            except Exception:
                results.put("Não foi possível concluir o login. Tente novamente.")

        threading.Thread(target=worker, daemon=True).start()
        poll_id = frame.after(100, poll)
        return "break"

    def enter_offline() -> None:
        if busy or closed:
            return
        name = simpledialog.askstring(
            "Modo offline", "Informe seu nome para identificar esta sessão local:", parent=frame
        )
        if name is None:
            return
        try:
            session = client.enter_offline(name)
        except ApiError as error:
            status.set(str(error))
            return
        password.delete(0, tk.END)
        on_success(session)

    offline_panel = ttk.Frame(frame, padding=(24, 0, 24, 28))
    offline_panel.grid(row=1, column=0, pady=(64, 0))
    offline_button = ttk.Button(
        offline_panel, text="Continuar sem login (modo offline)", command=enter_offline,
        style="Login.TButton"
    )
    offline_button.pack(pady=(0, 12))
    ttk.Label(offline_panel, text="Modo offline: acesso local sem autenticação na API.",
              wraplength=600, font=("Arial", 12), justify="center").pack()
    ttk.Label(panel, text=f"Servidor: {client.base_url}", wraplength=600,
              font=("Arial", 12)).grid(row=5, column=0, columnspan=3, pady=(16, 0))
    button = ttk.Button(panel, text="Entrar", command=submit, style="LoginPrimary.TButton")
    button.grid(row=4, column=1, sticky="ew", pady=8)
    for widget in (username, password, button):
        widget.bind("<Return>", submit)
    username.focus_set()
    return frame
