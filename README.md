# ecg-extraction

Aplicação Tkinter independente: Watch, Mobile e Enviar ao Servidor.
Requer Python 3.11 ou superior, Tkinter e Android Platform Tools (`adb` no PATH)
para operar os dispositivos.

Na raiz do projeto:

```powershell
pip install -r requirements.txt
python main.py
```

O `.env` de sincronização fica na raiz de ecg-extraction. Nenhum arquivo de
Reseting_mobiles é necessário. Os caminhos padrão são resolvidos a partir do
projeto irmão `../datalake`: Watch e Mobile usam `landing/raw` e o CSV de
participantes fica em
`serving/participants_summary/participants_summary.csv`. Os dados são externos
e não fazem parte deste repositório.


## Envio ao servidor

A aba **Enviar ao Servidor** compara e envia arquivos destas pastas em
`landing/raw`:

- `mobile_fl_data`
- `mobile_ic_data`
- `watch_fl_data`
- `watch_ic_data`
- `ecg_data`
- `holter_data`
- `looper_data`
- `eco_data`
- `redcap_data`
- `blood_test_data`
- `bio_data`

### Configuração

1. Instale as dependências:

   ```powershell
   pip install -r requirements.txt
   ```

2. Copie `.env.example` para `.env` e preencha os dados reais do servidor.

   Configure os dois destinos apresentados no seletor **Acesso** da aba:

   ```dotenv
   ECG_SYNC_DEFAULT_CONNECTION=external
   ECG_SYNC_EXTERNAL_HOST=servidor-externo.exemplo
   ECG_SYNC_EXTERNAL_PORT=22
   ECG_SYNC_LAB_HOST=servidor-laboratorio.exemplo
   ECG_SYNC_LAB_PORT=22
   ```

   - **Externo** usa `ECG_SYNC_EXTERNAL_HOST` e
     `ECG_SYNC_EXTERNAL_PORT`.
   - **Laboratório (rede local)** usa `ECG_SYNC_LAB_HOST` e
     `ECG_SYNC_LAB_PORT`.

   A troca de acesso invalida a comparação anterior. Clique em
   **Verificar servidor** novamente antes de enviar.

3. Cadastre e confira previamente as chaves públicas dos destinos externo e
   local no arquivo `known_hosts`. Conexões com identidade SSH desconhecida são
   rejeitadas.

O arquivo `.env` é ignorado pelo Git. Não coloque senhas, chaves privadas ou
credenciais no `.env.example`.

Para autenticação por senha, use:

```dotenv
ECG_SYNC_AUTH_METHOD=password
ECG_SYNC_PASSWORD=
```

Com a senha vazia, a interface abre uma janela mascarada ao verificar o
servidor. A senha permanece somente na memória durante a comparação e o upload.

O envio de arquivos abre uma conexão SSH/SFTP direta com o destino escolhido.
Túneis `ssh -L` para outros serviços não são necessários para esse upload.

### Segurança do upload

Somente arquivos classificados como novos podem ser selecionados. Cada envio
usa um nome temporário terminado em `.part`, valida o tamanho e tenta validar
SHA-256 antes da renomeação definitiva. Conflitos não são sobrescritos e nenhum
arquivo local ou remoto é apagado automaticamente.
