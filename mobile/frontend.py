"""Mobile extraction UI; preserve the single-device USB workflow."""
import queue
import threading
import tkinter as tk
from tkinter import ttk

from api import ApiClient
from api.kit import check_kit_devices
from core.identification import IdentificationContext
from core.scrollable_frame import create_scrollable_frame
from core.ui_widgets import PlaceholderEntry
from .backend import MobileBackend


SOURCES = {"ecg_registration": "cadastro ECG", "manual_input": "informado manualmente",
           "form_input": "formulário", "participants_summary_csv": "CSV de participantes",
           "raw_alphanumeric_id": "ID alfanumérico do celular"}


class MobileView:
    def __init__(self, parent, api_client=None, backend=None, identification=None):
        self.backend = backend if backend is not None else MobileBackend()
        self.client = api_client
        self.identification = identification or IdentificationContext(parent)
        self.outer, self.frame = create_scrollable_frame(parent)
        self.vars = dict(self.identification.values)
        self.vars["mobile"] = tk.StringVar(self.frame)
        self.kit_status = self.identification.kit_status
        self.participant_status = self.identification.participant_status
        self.status = tk.StringVar(self.frame, "Aguardando...")
        self.device_status = tk.StringVar(self.frame)
        self.destination = tk.StringVar(self.frame)
        self.busy = self.lookup_busy = self.progress_running = False
        self.devices_current = False
        self.devices = []
        self.registration_context = ""
        self.conflict = None
        self.generation = 0
        self.autofilled = {}
        self.events = queue.Queue()
        self.closed = False
        self.inputs = []
        self.traces = []
        self.build()
        for key, variable in self.vars.items():
            self.traces.append((variable, variable.trace_add("write", lambda *_args, name=key: self.changed(name))))
        for variable in (self.identification.busy, self.identification.lookup_busy):
            self.traces.append((variable, variable.trace_add("write", lambda *_: self.update_controls())))
        for variable in (self.kit_status, self.participant_status):
            self.traces.append((variable, variable.trace_add("write", self.update_status_styles)))
        self.outer.bind("<Destroy>", self.destroyed, add="+")
        self.timer = self.frame.after(50, self.poll)
        self.update_controls()
        self.update_status_styles()
        self.initial_refresh_pending = self.identification.busy.get()
        self.refresh_devices()

    def label(self, parent, variable, row, columns=1):
        label = ttk.Label(parent, textvariable=variable, wraplength=370, justify="left")
        label.grid(row=row, column=0, columnspan=columns, sticky="ew", padx=4, pady=4)
        parent.bind("<Configure>", lambda event: label.configure(wraplength=max(100, event.width - 24)), add="+")
        return label

    def build(self):
        style = ttk.Style(self.frame)
        style.configure("Mobile.Found.TLabel", foreground="#167035", font=("Arial", 9, "bold"))
        style.configure("Mobile.Missing.TLabel", foreground="#b42318", font=("Arial", 9, "bold"))
        for col in (0, 1):
            self.frame.columnconfigure(col, weight=1, uniform="columns")
        ttk.Label(self.frame, text="Extrair arquivos do celular", font=("Arial", 16, "bold"),
                  anchor="center").grid(row=0, column=0, columnspan=2, sticky="ew", pady=8)
        instructions = ttk.Label(self.frame, text="Conecte um celular via USB e autorize a depuração.\n"
                                 "Confira Kit e Participante antes de extrair; Mobile é opcional.",
                                 anchor="center", justify="center", wraplength=800)
        instructions.grid(row=1, column=0, columnspan=2, sticky="ew", padx=8, pady=6)
        self.frame.bind("<Configure>", lambda event: instructions.configure(wraplength=max(200, event.width - 24)), add="+")
        left, right = ttk.Frame(self.frame), ttk.Frame(self.frame)
        self.left, self.right = left, right
        for col, section in enumerate((left, right)):
            section.grid(row=2, column=col, sticky="nsew", padx=6, pady=6)
            section.columnconfigure(0, weight=1)
        ident = ttk.LabelFrame(left, text="Identificação", padding=5)
        ident.grid(row=0, column=0, sticky="ew", pady=4)
        ident.columnconfigure(1, weight=1)
        for row, key, title, placeholder in ((0, "kit", "Kit *", "Kit_00"),
                (1, "participant", "Participante *", "ABC-12-3456"),
                (2, "mobile", "Mobile (opcional)", "Mobile_00")):
            ttk.Label(ident, text=title).grid(row=row, column=0, sticky="w", padx=4, pady=3)
            entry = PlaceholderEntry(ident, textvariable=self.vars[key], placeholder=placeholder, width=12)
            entry.grid(row=row, column=1, sticky="ew", padx=4, pady=3)
            self.inputs.append(entry)
        self.verify_button = ttk.Button(ident, text="Verificar", width=12, command=self.verify_kit)
        self.verify_button.grid(row=0, column=2, padx=4)
        ttk.Label(ident, text="Type").grid(row=3, column=0, sticky="w", padx=4)
        radios = ttk.Frame(ident)
        radios.grid(row=3, column=1, columnspan=2, sticky="w")
        for title, value in (("FreeLiving", "free_living"), ("In Clinic", "in_clinic")):
            radio = ttk.Radiobutton(radios, text=title, value=value, variable=self.vars["context"])
            radio.pack(side="left")
            self.inputs.append(radio)
        self.kit_label = self.label(ident, self.kit_status, 4, 3)
        self.participant_label = self.label(ident, self.participant_status, 5, 3)
        self.label(ident, self.destination, 6, 3)
        devices = ttk.LabelFrame(left, text="Dispositivos", padding=5)
        devices.grid(row=1, column=0, sticky="ew", pady=4)
        devices.columnconfigure(0, weight=1)
        self.device_tree = ttk.Treeview(devices, columns=("device", "state"), show="headings", height=5)
        for key, title, width in (("device", "Dispositivo", 190), ("state", "Conexão", 140)):
            self.device_tree.heading(key, text=title)
            self.device_tree.column(key, width=width, minwidth=60)
        self.device_tree.grid(row=0, column=0, sticky="ew")
        scrollbar = ttk.Scrollbar(devices, orient="horizontal", command=self.device_tree.xview)
        scrollbar.grid(row=1, column=0, sticky="ew")
        self.device_tree.configure(xscrollcommand=scrollbar.set)
        self.label(devices, self.device_status, 2)
        self.devices_button = ttk.Button(devices, text="Atualizar dispositivos", command=self.refresh_devices)
        self.devices_button.grid(row=3, column=0, sticky="ew", pady=4)
        self.disconnect_button = ttk.Button(devices, text="Desconectar de todos os dispositivos", command=self.disconnect)
        self.disconnect_button.grid(row=4, column=0, sticky="ew", pady=4)
        ttk.Label(devices, text="Para desconectar aparelhos USB, retire o cabo.", wraplength=350,
                  justify="left").grid(row=5, column=0, sticky="ew", pady=4)
        actions = ttk.Frame(right)
        actions.grid(row=0, column=0, sticky="ew", pady=4)
        for col in (0, 1):
            actions.columnconfigure(col, weight=1, uniform="actions")
        self.inspect_button = ttk.Button(actions, text="Verificar", padding=(8, 12), command=self.inspect)
        self.inspect_button.grid(row=0, column=0, sticky="ew", padx=(0, 3))
        self.extract_button = ttk.Button(actions, text="Extrair Dados", padding=(8, 12), command=self.extract)
        self.extract_button.grid(row=0, column=1, sticky="ew", padx=(3, 0))
        content = ttk.Frame(right)
        content.grid(row=1, column=0, sticky="nsew", pady=4)
        right.rowconfigure(1, weight=1)
        content.columnconfigure(0, weight=1)
        content.rowconfigure(0, weight=1)
        self.results = tk.Text(content, width=1, height=20, wrap="word", state="disabled", font=("Consolas", 9))
        self.results.grid(row=0, column=0, sticky="nsew")
        scroll = ttk.Scrollbar(content, command=self.results.yview)
        scroll.grid(row=0, column=1, sticky="ns")
        self.results.configure(yscrollcommand=scroll.set)
        self.label(right, self.status, 2)
        self.progress_bar = ttk.Progressbar(right, mode="indeterminate")
        self.progress_bar.grid(row=3, column=0, sticky="ew", pady=4)

    def values(self):
        return {key: variable.get().strip() for key, variable in self.vars.items()}

    def online(self):
        return bool(self.client is not None and self.client.offline_session is None and self.client.session is not None)

    def changed(self, key):
        if key == "kit":
            self.generation += 1
            old, self.autofilled = self.autofilled, {}
            for field, value in old.items():
                if self.vars[field].get() == value:
                    self.vars[field].set("")
            self.kit_status.set("")
            self.participant_status.set("")
        if key in {"kit", "participant"}:
            self.conflict = None
            self.registration_context = ""
        self.update_controls()

    def update_status_styles(self, *_args):
        for variable, label, found, missing in (
            (self.kit_status, self.kit_label, "Kit encontrado", "Kit não cadastrado"),
            (self.participant_status, self.participant_label, "Participante encontrado", "Nenhum participante associado"),
        ):
            label.configure(style="Mobile.Found.TLabel" if variable.get() == found else
                            "Mobile.Missing.TLabel" if variable.get() == missing else "TLabel")

    def update_controls(self):
        if self.closed:
            return
        active = self.busy or self.lookup_busy
        if active != self.progress_running:
            self.progress_running = active
            self.progress_bar.start(10) if active else self.progress_bar.stop()
        values = self.values()
        ready = not self.identification.busy.get() and not self.identification.lookup_busy.get()
        connected = (self.devices_current and sum(d["state"] == "device" for d in self.devices) == 1
                     and not any(d["state"] in {"offline", "unauthorized"} for d in self.devices))
        try:
            MobileBackend._validate_manual_participant_id(values["participant"])
            valid = True
        except RuntimeError:
            valid = False
        for button, enabled in {
            self.verify_button: ready and self.online() and bool(values["kit"]),
            self.devices_button: ready, self.disconnect_button: ready,
            self.inspect_button: ready and connected,
            self.extract_button: ready and connected and valid and bool(values["kit"]) and not self.conflict,
        }.items():
            button.configure(state="normal" if enabled else "disabled")
        for entry in self.inputs:
            entry.configure(state="disabled" if self.identification.busy.get() else "normal")
        if not self.online():
            offline = self.client is None or self.client.offline_session is not None
            self.kit_status.set("Modo offline — identificação manual" if offline else
                                "Sessão expirada — identificação manual; reabra para entrar.")
        context = self.registration_context or values["context"]
        if context:
            text = f"Destino: {self.backend.get_output_root(context)}"
            if self.registration_context and values["context"] and self.registration_context != values["context"]:
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
        if self.closed:
            return
        if self.initial_refresh_pending and not self.identification.busy.get() and not self.identification.lookup_busy.get():
            self.initial_refresh_pending = False
            self.refresh_devices()
        try:
            while True:
                callback, result = self.events.get_nowait()
                callback(result)
        except queue.Empty:
            pass
        self.timer = self.frame.after(50, self.poll)

    def destroyed(self, event):
        if event.widget is self.outer:
            self.closed = True
            for variable, trace in self.traces:
                variable.trace_remove("write", trace)
            self.outer.after_cancel(self.timer)

    def worker_status(self, text):
        self.events.put((self.status.set, text))

    def run_task(self, work, success, *, refresh=True):
        if self.identification.busy.get() or self.identification.lookup_busy.get():
            return
        self.busy = True
        self.identification.busy.set(True)
        def finish():
            self.busy = False
            self.identification.busy.set(False)
            if refresh:
                self.refresh_devices()
            self.update_controls()
        def complete(result):
            try:
                success(result)
            finally:
                finish()
        def failed(message):
            self.status.set(message)
            if "Conflito de participante" in message:
                self.conflict = message
            finish()
        self.submit(work, complete, failed)

    def verify_kit(self):
        if (self.identification.busy.get() or self.identification.lookup_busy.get()
                or not self.online() or not self.vars["kit"].get().strip()):
            return
        before, generation = self.values(), self.generation
        self.lookup_busy = True
        self.identification.lookup_busy.set(True)
        self.kit_status.set("Verificando Kit...")
        self.participant_status.set("")
        def complete(result):
            self.lookup_busy = False
            self.identification.lookup_busy.set(False)
            if generation == self.generation:
                self.kit_status.set("Kit encontrado" if result["exists"] else "Kit não cadastrado")
                self.participant_status.set("Participante encontrado" if result["participant"] else "Nenhum participante associado")
                names = result["devices"]
                for key, value in {"participant": result["participant"], "context": result["context"],
                                   "mobile": names[0] if len(names) == 1 else ""}.items():
                    if self.vars[key].get().strip() == before[key] and (value or key in self.autofilled):
                        self.vars[key].set(value)
                        self.autofilled[key] = value
                if len(names) > 1:
                    self.status.set("Mais de um Mobile no Kit. Informe o nome do aparelho, se necessário.")
            self.update_controls()
        def failed(message):
            self.lookup_busy = False
            self.identification.lookup_busy.set(False)
            if generation == self.generation:
                self.kit_status.set(message + " Identificação manual disponível.")
            self.update_controls()
        self.submit(lambda: check_kit_devices(self.client, before["kit"], "mobile"), complete, failed)

    def refresh_devices(self):
        if self.identification.busy.get() or self.identification.lookup_busy.get():
            return
        self.devices_current = False
        self.device_status.set("Verificando dispositivos...")
        def work():
            try:
                return self.backend.list_device_statuses()
            except Exception:
                self.events.put((self.device_status.set, "Status indisponível; listagem anterior desatualizada."))
                raise
        def complete(devices):
            if [(d["device_id"], d["state"]) for d in devices] != [(d["device_id"], d["state"]) for d in self.devices]:
                self.registration_context = ""
                self.conflict = None
            self.devices, self.devices_current = devices, True
            self.device_tree.delete(*self.device_tree.get_children())
            labels = {"device": "Conectado", "unauthorized": "Não autorizado", "offline": "Offline"}
            for device in devices:
                self.device_tree.insert("", "end", values=(device["device_id"], labels.get(device["state"], device["state"])))
            self.device_status.set(f"{len(devices)} dispositivo(s) listado(s). Conecte apenas um celular por vez."
                                   if devices else "Nenhum dispositivo listado.")
        self.run_task(work, complete, refresh=False)

    def disconnect(self):
        self.run_task(self.backend.disconnect_all_devices,
                      lambda _result: self.status.set("Desconexão ADB solicitada. Para aparelhos USB, retire o cabo; confira a lista atualizada."))

    def show_results(self, text):
        self.results.configure(state="normal")
        self.results.delete("1.0", tk.END)
        self.results.insert("1.0", text)
        self.results.configure(state="disabled")

    def inspect(self):
        values = self.values()
        def work():
            return self.backend.inspect_phone_documents(status_callback=self.worker_status,
                expected_participant_id=values["participant"] or None)
        def complete(result):
            self.conflict = None
            self.registration_context = (result.get("registration") or {}).get("collection_context", "")
            lines = [f"Celular encontrado: {result['device_id']}",
                     f"Participante: {result['participant_id'] or 'Não encontrado'}",
                     f"Origem: {SOURCES.get(result.get('participant_lookup_source'), result.get('participant_lookup_source') or 'Não identificada')}", ""]
            if result.get("participant_raw_id"):
                lines.append(f"ID bruto no celular: {result['participant_raw_id']}")
            if result.get("participant_id_error"):
                lines.append(f"Aviso: {result['participant_id_error']}")
            if not result["sources"]:
                lines.append("Nenhuma pasta de coleta encontrada.")
            for source in result["sources"]:
                lines.append(f"\nOrigem: {source['path']} ({source['file_count']} arquivos)")
                for folder in source["folders"]:
                    lines.append(f"  {folder['folder_name']}/ → {folder['file_count']} arquivos")
                lines.extend(f"  {name} (arquivo)" for name in source["files"])
                if not source["folders"] and not source["files"]:
                    lines.append("  Pasta vazia.")
            self.show_results("\n".join(lines))
            self.status.set("Verificação concluída.")
        self.run_task(work, complete)

    def extract(self):
        values = self.values()
        try:
            MobileBackend._validate_manual_participant_id(values["participant"])
            if not values["kit"]:
                raise RuntimeError("Informe o Kit antes de extrair.")
        except RuntimeError as error:
            self.status.set(str(error))
            return
        def work():
            return self.backend.extract_documents(mobile_number="", mobile_name=values["mobile"],
                collection_context=values["context"], expected_participant_id=values["participant"],
                status_callback=self.worker_status)
        def complete(result):
            self.registration_context = (result.get("registration") or {}).get("collection_context", "")
            self.show_results(f"Kit: {values['kit']}\nMobile: {result['mobile_name']}\n"
                f"Dispositivo: {result['device_id']}\nParticipante: {result['participant_id']}\n"
                f"Origem: {SOURCES.get(result['participant_lookup_source'], result['participant_lookup_source'])}\n"
                f"Contexto: {result['collection_context_label']}\n{result.get('context_warning') or ''}\n"
                f"ZIP: {result['output_archive']}\nMetadados no ZIP: {result['metadata_file']}")
            self.status.set("Extração concluída.")
        self.run_task(work, complete)


def create_mobile_frame(parent: tk.Widget, api_client: ApiClient | None = None,
                        identification: IdentificationContext | None = None) -> tk.Frame:
    return MobileView(parent, api_client, identification=identification).outer
