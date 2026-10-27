import time
from collections.abc import Callable

from .config import ServerSyncConfig
from .models import FileRecord, RemoteInventory
from .ssh_client import SshSftpClient


class RemoteInventoryScanner:
    def scan(
        self,
        config: ServerSyncConfig,
        client: SshSftpClient,
        status_callback: Callable[[str], None] | None = None,
    ) -> RemoteInventory:
        files: list[FileRecord] = []
        partial_files: list[FileRecord] = []

        for index, folder in enumerate(config.folders, 1):
            def report_progress() -> None:
                if status_callback:
                    status_callback(
                        f"Consultando {index}/{len(config.folders)}: {folder} — "
                        f"{len(files) + len(partial_files)} arquivos encontrados..."
                    )

            report_progress()
            last_update = time.monotonic()
            folder_root = config.remote_raw_root / folder

            if not client.directory_exists(folder_root):
                continue

            for remote_path, size_bytes in client.iter_files(folder_root):
                if time.monotonic() - last_update >= 0.5:
                    report_progress()
                    last_update = time.monotonic()
                relative_path = remote_path.relative_to(folder_root)
                record = FileRecord(
                    folder=folder,
                    relative_path=relative_path,
                    size_bytes=size_bytes,
                    remote_path=remote_path,
                )

                if remote_path.name.endswith(".part"):
                    partial_files.append(record)
                else:
                    files.append(record)

        if status_callback:
            status_callback(f"Inventário remoto concluído: {len(files)} arquivos e {len(partial_files)} parciais.")

        return RemoteInventory(
            files=tuple(sorted(files, key=lambda record: record.key)),
            partial_files=tuple(
                sorted(partial_files, key=lambda record: record.key)
            ),
        )
