"""Watch operator interface. Workers communicate through a main-thread queue."""
import queue
import threading
import tkinter as tk
from tkinter import simpledialog, ttk

from api import ApiClient
from core.scrollable_frame import create_scrollable_frame
from .backend import WatchBackend
from .kit_lookup import check_kit
from .watch_id import WatchIdParser

SOURCES = {"ecg_registration": "cadastro ECG", "watch_files": "arquivos do relógio",
           "manual_input": "informado manualmente", "form_input": "formulário"}

PLACEHOLDERS = {
    "kit": "Kit_00", "participant": "ABC-12-3456", "watch": "Watch_00",
    "code": "123456", "ip": "30.0.0.00", "pair_port": "12345", "connect_port": "12345",
}


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


class WatchView:
    def __init__(self, parent, api_client=None, backend=None):
        self.backend = backend if backend is not None else WatchBackend()
        self.client = api_client
        self.outer, self.frame = create_scrollable_frame(parent)
        self.events = queue.Queue()
        self.closed = threading.Event()
        self.busy = self.lookup_busy = self.network_busy = False
        self.lookup_generation = 0
        self.autofilled = {}
        self.devices = []
        self.devices_current = False
        self.paired = set()
        self.suggested_prefix = ""
        self.conflict = None
        self.registration_context = ""
        self.vars = {name: tk.StringVar(self.frame) for name in
                     ("kit", "participant", "watch", "context", "ip", "pair_port", "code", "connect_port")}
        for name in ("status", "kit_status", "participant_status", "network_status", "pair_status",
                     "connection_status", "device_status", "destination"):
            setattr(self, name, tk.StringVar(self.frame))
        self.status.set("Aguardando...")
        self.inputs = []
        self.build()
        for name, variable in self.vars.items():
            variable.trace_add("write", lambda *_args, key=name: self.changed(key))
        self.outer.bind("<Destroy>", self.destroyed, add="+")
        self.timer = self.frame.after(50, self.poll)
        self.update_controls()
        self.refresh_network()
        self.refresh_devices()

    def label(self, parent, variable, row, columns=1):
        label = ttk.Label(parent, textvariable=variable, wraplength=370, justify="left")
        label.grid(row=row, column=0, columnspan=columns, sticky="ew", padx=4, pady=4)
        parent.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width - 24)), add="+")
        return label

    def entry(self, parent, name, label, row):
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", padx=4, pady=3)
        widget = PlaceholderEntry(parent, textvariable=self.vars[name], placeholder=PLACEHOLDERS[name], width=12)
        widget.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
        self.inputs.append(widget)
        return widget

    def build(self):
        frame = self.frame
        style = ttk.Style(frame)
        style.configure("Watch.Found.TLabel", foreground="#167035", font=("Arial", 9, "bold"))
        style.configure("Watch.Missing.TLabel", foreground="#b42318", font=("Arial", 9, "bold"))
        action_width = 12
        for column in (0, 1):
            frame.columnconfigure(column, weight=1, uniform="columns")
        ttk.Label(frame, text="Extrair dados do relógio", font=("Arial", 16, "bold"),
                  anchor="center").grid(row=0, column=0, columnspan=2, sticky="ew", pady=8)
        instructions = ttk.Label(frame, anchor="center", justify="center", wraplength=800,
            text="Identifique o participante e conecte o relógio na mesma rede Wi-Fi.\n"
                 "As portas de pareamento e conexão são diferentes.")
        instructions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        frame.bind("<Configure>", lambda event: instructions.configure(wraplength=max(200, event.width - 24)), add="+")
        left, right = ttk.Frame(frame), ttk.Frame(frame)
        left.grid(row=2, column=0, sticky="nsew", padx=6, pady=6)
        right.grid(row=2, column=1, sticky="nsew", padx=6, pady=6)
        left.columnconfigure(0, weight=1)
        right.columnconfigure(0, weight=1)
        ident = ttk.LabelFrame(left, text="Identificação", padding=5)
        ident.grid(row=0, column=0, sticky="ew", pady=4)
        ident.columnconfigure(1, weight=1)
        self.entry(ident, "kit", "Kit *", 0)
        self.verify_button = ttk.Button(ident, text="Verificar", command=self.verify_kit, width=action_width)
        self.verify_button.grid(row=0, column=2, padx=4)
        self.entry(ident, "participant", "Participante *", 1)
        ttk.Label(ident, text="Watch (opcional)").grid(row=2, column=0, padx=4, sticky="w")
        self.entry(ident, "watch", "Watch", 2)
        ttk.Label(ident, text="Type").grid(row=3, column=0, sticky="w", padx=4)
        radios = ttk.Frame(ident)
        radios.grid(row=3, column=1, columnspan=2, sticky="w")
        for text, value in (("FreeLiving", "free_living"), ("In Clinic", "in_clinic")):
            radio = ttk.Radiobutton(radios, text=text, value=value, variable=self.vars["context"])
            radio.pack(side="left")
            self.inputs.append(radio)
        self.kit_status_label = self.label(ident, self.kit_status, 4, 3)
        self.participant_status_label = self.label(ident, self.participant_status, 5, 3)
        self.label(ident, self.destination, 6, 3)
        for variable in (self.kit_status, self.participant_status):
            variable.trace_add("write", self.update_status_styles)
        pair = ttk.LabelFrame(left, text="Pareamento", padding=5)
        pair.grid(row=1, column=0, sticky="ew", pady=4)
        pair.columnconfigure(0, weight=1)
        first = ttk.Frame(pair)
        first.grid(row=0, column=0, sticky="ew")
        first.columnconfigure(1, weight=1)
        self.entry(first, "code", "Código de\nPareamento", 0).configure(width=8)
        self.network_button = ttk.Button(first, text="Atualizar", command=self.refresh_network, width=action_width)
        self.network_button.grid(row=0, column=2, padx=2)
        self.pair_button = ttk.Button(first, text="Parear", command=self.pair, width=action_width)
        self.pair_button.grid(row=0, column=3, padx=2)
        second = ttk.Frame(pair)
        second.grid(row=1, column=0, sticky="ew")
        for col, name, text in ((0, "ip", "IP do Relógio *"), (1, "pair_port", "Porta de Pareamento *")):
            second.columnconfigure(col, weight=1)
            group = ttk.Frame(second)
            group.grid(row=0, column=col, sticky="ew", padx=4)
            ttk.Label(group, text=text).pack(anchor="w")
            entry = PlaceholderEntry(group, textvariable=self.vars[name], placeholder=PLACEHOLDERS[name], width=12)
            entry.pack(fill="x")
            self.inputs.append(entry)
        self.label(pair, self.network_status, 2)
        self.label(pair, self.pair_status, 3)
        connection = ttk.LabelFrame(left, text="Conexão", padding=5)
        connection.grid(row=2, column=0, sticky="ew", pady=4)
        connection.columnconfigure(1, weight=1)
        self.entry(connection, "connect_port", "Porta de Conexão *", 0)
        self.connect_button = ttk.Button(connection, text="Conectar", command=self.connect, width=action_width)
        self.connect_button.grid(row=0, column=2, padx=4)
        self.disconnect_button = ttk.Button(connection, text="Desconectar de Todos os Dispositivos", command=self.disconnect)
        self.disconnect_button.grid(row=1, column=0, columnspan=3, sticky="ew", padx=4, pady=5)
        self.label(connection, self.connection_status, 2, 3)
        devices = ttk.LabelFrame(right, text="Dispositivos", padding=5)
        devices.grid(row=0, column=0, sticky="ew", pady=4)
        devices.columnconfigure(0, weight=1)
        self.device_tree = ttk.Treeview(devices, columns=("device", "state", "paired"), show="headings", height=4)
        for key, title, width in (("device", "Dispositivo", 140), ("state", "Conexão", 90), ("paired", "Pareamento", 115)):
            self.device_tree.heading(key, text=title)
            self.device_tree.column(key, width=width, minwidth=50)
        self.device_tree.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(devices, orient="horizontal", command=self.device_tree.xview)
        scrollbar.grid(row=1, column=0, sticky="ew")
        self.device_tree.configure(xscrollcommand=scrollbar.set)
        self.label(devices, self.device_status, 2)
        self.devices_button = ttk.Button(devices, text="Atualizar dispositivos", command=self.refresh_devices)
        self.devices_button.grid(row=3, column=0, sticky="ew")
        actions = ttk.Frame(right)
        actions.grid(row=1, column=0, sticky="ew", pady=4)
        for column in (0, 1):
            actions.columnconfigure(column, weight=1, uniform="actions")
        self.inspect_button = ttk.Button(actions, text="Verificar arquivos", command=self.inspect, padding=(8, 12))
        self.inspect_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.extract_button = ttk.Button(actions, text="Extrair Dados", command=self.extract, padding=(8, 12))
        self.extract_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        content = ttk.Frame(right)
        content.grid(row=3, column=0, sticky="nsew", pady=4)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)
        self.results = tk.Text(content, width=1, height=16, wrap="word", state="disabled", font=("Consolas", 9))
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(content, command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        self.label(right, self.status, 4)

    def values(self):
        return {key: variable.get().strip() for key, variable in self.vars.items()}

    def update_status_styles(self, *_args):
        for variable, label, found, missing in (
            (self.kit_status, self.kit_status_label, "Kit encontrado", "Kit não cadastrado"),
            (self.participant_status, self.participant_status_label, "Participante encontrado", "Nenhum participante associado"),
        ):
            style = ("Watch.Found.TLabel" if variable.get() == found else
                     "Watch.Missing.TLabel" if variable.get() == missing else "TLabel")
            label.configure(style=style)

    def online(self):
        return bool(self.client is not None and self.client.offline_session is None and self.client.session is not None)

    def changed(self, key):
        if key == "kit":
            self.lookup_generation += 1
            old, self.autofilled = self.autofilled, {}
            for field, value in old.items():
                if self.vars[field].get() == value:
                    self.vars[field].set("")
            self.kit_status.set("")
            self.participant_status.set("")
        if key in {"ip", "connect_port", "participant"}:
            self.conflict = None
            self.registration_context = ""
        self.update_controls()

    def update_controls(self):
        values = self.values()
        manager = self.backend.connection_manager
        try:
            manager.validate_ip(values["ip"])
            ip_valid = True
        except RuntimeError:
            ip_valid = False
        def valid_port(key):
            try:
                manager.validate_port(values[key], key)
                return True
            except RuntimeError:
                return False
        address = f"{values['ip']}:{values['connect_port']}"
        connected = self.devices_current and any(d["device_id"] == address and d["state"] == "device" for d in self.devices)
        ready = not self.busy and not self.lookup_busy
        eligibility = {
            self.verify_button: ready and self.online() and bool(values["kit"]) and not self.lookup_busy,
            self.network_button: ready and not self.network_busy,
            self.pair_button: ready and ip_valid and valid_port("pair_port") and bool(values["code"]),
            self.connect_button: ready and ip_valid and valid_port("connect_port"),
            self.disconnect_button: ready, self.devices_button: ready,
            self.inspect_button: ready and connected and ip_valid and valid_port("connect_port"),
            self.extract_button: ready and not self.lookup_busy and connected and ip_valid and valid_port("connect_port")
                and bool(values["kit"]) and WatchIdParser.is_valid(values["participant"]) and not self.conflict,
        }
        for button, enabled in eligibility.items():
            button.configure(state="normal" if enabled else "disabled")
        for widget in self.inputs:
            widget.configure(state="disabled" if self.busy else "normal")
        if not self.online():
            offline = self.client is None or self.client.offline_session is not None
            self.kit_status.set("Modo offline — identificação manual" if offline else "Sessão expirada — identificação manual; reabra para entrar.")
        context = self.registration_context or values["context"]
        if context:
            text = f"Destino: {self.backend.config.get_output_root(context)}"
            if self.registration_context and values["context"] and values["context"] != self.registration_context:
                text = "Type difere do cadastro ECG; o cadastro define o destino.\n" + text
            self.destination.set(text)
        else:
            self.destination.set("Destino: cadastro ECG; sem cadastro, selecione Type antes de extrair.")

    def submit(self, work, success, failure):
        def worker():
            try:
                result = work()
            except Exception as error:
                self.events.put((failure, str(error)))
            else:
                self.events.put((success, result))
        threading.Thread(target=worker, daemon=True).start()

    def poll(self):
        if self.closed.is_set():
            return
        try:
            while True:
                callback, value = self.events.get_nowait()
                callback(value)
        except queue.Empty:
            pass
        self.timer = self.frame.after(50, self.poll)

    def destroyed(self, event):
        if event.widget is self.outer:
            self.closed.set()
            if self.timer:
                self.outer.after_cancel(self.timer)

    def worker_status(self, text):
        self.events.put((self.status.set, text))

    def prompt_id(self, reason, suggested):
        done, answer = threading.Event(), [None]
        def prompt(_):
            try:
                answer[0] = simpledialog.askstring("Informar participante", reason + "\nID: ABC-12-3456",
                                                  initialvalue=suggested or "", parent=self.frame)
            finally:
                done.set()
        self.events.put((prompt, None))
        while not done.wait(0.1):
            if self.closed.is_set():
                return None
        return answer[0]

    def run_adb(self, work, success, feedback=None, refresh=True):
        if self.busy:
            return
        self.busy = True
        self.update_controls()
        def finish():
            self.busy = False
            if refresh:
                self.refresh_devices()
            self.update_controls()
        def completed(result):
            try:
                success(result)
            finally:
                finish()
        def failed(message):
            self.status.set(message)
            if feedback is not None:
                feedback.set(message)
            if "Conflito de participante" in message:
                self.conflict = message
            finish()
        self.submit(work, completed, failed)

    def verify_kit(self):
        if self.lookup_busy or self.busy or not self.online() or not self.vars["kit"].get().strip():
            return
        kit, generation, before = self.vars["kit"].get().strip(), self.lookup_generation, self.values()
        self.lookup_busy = True
        self.kit_status.set("Verificando Kit...")
        self.participant_status.set("")
        self.update_controls()
        def finished(result):
            self.lookup_busy = False
            if generation == self.lookup_generation:
                self.kit_status.set("Kit encontrado" if result["exists"] else "Kit não cadastrado")
                self.participant_status.set("Participante encontrado" if result["participant"] else "Nenhum participante associado")
                watches = result["watches"]
                for key, value in {"participant": result["participant"], "context": result["context"],
                                   "watch": watches[0] if len(watches) == 1 else ""}.items():
                    if (self.vars[key].get().strip() == before[key]
                            and (value or key in self.autofilled)):
                        self.vars[key].set(value)
                        self.autofilled[key] = value
            self.update_controls()
        def failed(message):
            self.lookup_busy = False
            if generation == self.lookup_generation:
                self.kit_status.set(message + " Identificação manual disponível.")
            self.update_controls()
        self.submit(lambda: check_kit(self.client, kit), finished, failed)

    def refresh_network(self):
        if self.network_busy or self.busy:
            return
        self.network_busy = True
        self.network_status.set("Detectando a rede local...")
        self.update_controls()
        def complete(network):
            self.network_busy = False
            if network is None:
                self.network_status.set("Rede não identificada. Informe o IP completo do relógio.")
            else:
                octets = min(3, network.network.prefixlen // 8)
                prefix = ".".join(str(network.ip).split(".")[:octets]) + "." if octets else ""
                if not self.busy and self.vars["ip"].get() in {"", self.suggested_prefix}:
                    self.vars["ip"].set(prefix)
                self.suggested_prefix = prefix
                self.network_status.set(f"IP deste computador: {network.ip} | Rede: {network.network}. Complete o IP do relógio.")
            self.update_controls()
        self.submit(self.backend.connection_manager.get_local_network, complete, lambda _message: complete(None))

    def render_devices(self):
        self.device_tree.delete(*self.device_tree.get_children())
        states = {"device": "Conectado", "unauthorized": "Não autorizado", "offline": "Offline"}
        represented = set()
        for device in self.devices:
            address = device["device_id"]
            host = address.rsplit(":", 1)[0]
            represented.add(host)
            self.device_tree.insert("", "end", values=(address, states.get(device["state"], device["state"]),
                                                        "Nesta sessão (IP)" if host in self.paired else "Desconhecido"))
        for host in sorted(self.paired - represented):
            self.device_tree.insert("", "end", values=(host, "Não listado", "Nesta sessão (IP)"))

    def refresh_devices(self):
        if self.busy:
            return
        self.device_status.set("Verificando dispositivos...")
        self.devices_current = False
        def complete(devices):
            self.devices, self.devices_current = devices, True
            self.render_devices()
            self.device_status.set(f"{len(devices)} dispositivo(s) listado(s). Pareamento: confirmação nesta sessão por IP."
                                   if devices or self.paired else "Nenhum dispositivo listado.")
        def work():
            try:
                return self.backend.connection_manager.list_device_statuses()
            except Exception:
                self.events.put((self.device_status.set, "Status indisponível; listagem anterior desatualizada."))
                raise
        self.run_adb(work, complete, refresh=False)

    def pair(self):
        values = self.values()
        self.pair_status.set("Pareando...")
        def work():
            output = self.backend.pair_watch(values["ip"], values["pair_port"], values["code"])
            if "successfully paired" not in output.lower():
                raise RuntimeError(output or "Pareamento não confirmado pelo ADB.")
            try:
                port, warning = self.backend.get_connect_port(values["ip"]), ""
            except Exception as error:
                port, warning = "", str(error)
            return port, warning
        def complete(result):
            port, warning = result
            self.paired.add(values["ip"])
            self.vars["code"].set("")
            if port:
                self.vars["connect_port"].set(port)
            self.pair_status.set("Pareamento confirmado nesta sessão." + ("\n" + warning if warning else ""))
            self.status.set("Pareamento concluído.")
        self.run_adb(work, complete, self.pair_status)

    def connect(self):
        values = self.values()
        self.connection_status.set("Conectando...")
        def work():
            _output, address = self.backend.connect_watch(values["ip"], values["connect_port"])
            devices = self.backend.connection_manager.list_device_statuses()
            if not any(d["device_id"] == address and d["state"] == "device" for d in devices):
                self.backend.adb.target_device_id = None
                raise RuntimeError("Conexão não confirmada. Confira autorização, IP e porta no relógio.")
            return address
        def complete(address):
            self.connection_status.set(f"Conectado em {address}")
            self.status.set("Conexão confirmada. Use Verificar arquivos para inspecionar.")
        self.run_adb(work, complete, self.connection_status)

    def disconnect(self):
        def complete(_output):
            self.vars["code"].set("")
            self.vars["connect_port"].set("")
            self.connection_status.set("Desconexão solicitada; confira a lista atualizada. Pareamentos mantidos.")
            self.status.set("Comando de desconexão concluído.")
        self.run_adb(self.backend.disconnect_all_devices, complete, self.connection_status)

    def show_results(self, text):
        self.results.configure(state="normal")
        self.results.delete("1.0", tk.END)
        self.results.insert("1.0", text)
        self.results.configure(state="disabled")

    def ensure_target(self, values):
        address = self.backend.get_connect_address(values["ip"], values["connect_port"])
        if not any(d["device_id"] == address and d["state"] == "device"
                   for d in self.backend.connection_manager.list_device_statuses()):
            raise RuntimeError("O relógio informado não está conectado e autorizado. Atualize os dispositivos.")
        self.backend.adb.target_device_id = address

    def inspect(self):
        values = self.values()
        def work():
            self.ensure_target(values)
            return self.backend.inspect_watch_documents(values["ip"], values["connect_port"],
                status_callback=self.worker_status, watch_id_prompt=self.prompt_id,
                expected_participant_id=values["participant"] or None)
        def complete(result):
            self.registration_context = (result["id_metadata"].get("registration") or {}).get("collection_context", "")
            self.show_results(f"Dispositivo: {result['device_id']}\nParticipante: {result['selected_id']}\n"
                f"Origem: {SOURCES.get(result['id_resolution_source'], result['id_resolution_source'])}\n"
                f"Pastas: {result['folder_count']} | Arquivos: {result['file_count']}\n\n{result['tree_text']}")
            self.status.set("Varredura concluída.")
            self.conflict = None
        self.run_adb(work, complete)

    def extract(self):
        values = self.values()
        if not values["kit"] or not WatchIdParser.is_valid(values["participant"]):
            self.status.set("Informe Kit e Participante válido antes de extrair.")
            return
        def work():
            self.ensure_target(values)
            return self.backend.extract_documents(watch_number="", watch_name=values["watch"],
                ip=values["ip"], pairing_port=values["pair_port"], connect_port=values["connect_port"],
                collection_context=values["context"], expected_participant_id=values["participant"],
                status_callback=self.worker_status)
        def complete(result):
            self.registration_context = (result["id_metadata"].get("registration") or {}).get("collection_context", "")
            self.show_results(f"Kit: {values['kit']}\nWatch: {result['watch_name']}\n"
                f"Dispositivo: {result['device_id']}\nParticipante: {result['selected_id']}\n"
                f"Origem: {SOURCES.get(result['id_resolution_source'], result['id_resolution_source'])}\n"
                f"Contexto: {result['collection_context_label']}\n{result.get('context_warning') or ''}\n"
                f"ZIP: {result['output_archive']}\nMetadados: {result['metadata_file']}")
            self.status.set("Extração concluída.")
        self.run_adb(work, complete)


def create_watch_frame(parent: tk.Widget, api_client: ApiClient | None = None) -> tk.Frame:
    return WatchView(parent, api_client).outer
