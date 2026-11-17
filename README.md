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


## Login na aplicação

Ao abrir o programa, informe seu usuário e senha da API ECG. Um login
bem-sucedido libera Watch, Mobile e Enviar ao Servidor. Usuário e senha são
enviados exatamente como digitados, incluindo espaços e caracteres especiais.

Como alternativa explícita, **Continuar sem login (modo offline)** solicita
o nome do operador e libera apenas Watch e Mobile. A aba Enviar ao Servidor
fica desabilitada. O nome identifica a sessão na tela; não é uma identidade
validada pela API nem é acrescentado aos metadados das extrações nesta versão.
O modo offline não cria tokens, não realiza chamadas autenticadas à API e
não é ativado automaticamente quando o login falha. Os dados extraídos continuam
nos destinos locais existentes; não há fila nova de sincronização automática.
Para entrar com login depois, feche e reabra o aplicativo.

O endereço padrão é `https://ecg.uea.edu.br`. Para alterá-lo, configure
`ECG_API_BASE_URL` no `.env` da raiz (somente HTTPS). Variáveis já definidas no
ambiente têm prioridade. O login envia JSON com `username` e `password` para
`POST /api/v1/auth/login`.

As requisições usam um User-Agent próprio (`ECGExtraction/1.0`) e os cabeçalhos
`Accept: */*` e `Content-Type: application/json`. Erros HTTP mostram o código e,
quando disponível, o detalhe JSON do servidor, com os valores enviados removidos.

Os tokens ficam somente em memória. Não há login persistente, renovação
automática de token ou restrição de abas por perfil nesta versão. A autenticação
SSH/SFTP do upload continua independente do login da aplicação.

Para futuras integrações, o cliente compartilhado `api.ApiClient` oferece
`request_json(method, path, payload=...)`, com autenticação Bearer. Os caminhos
devem ser relativos à API, começando com `/`, sem query ou fragmento. Uma resposta
401 limpa a sessão e gera `AuthenticationError`; a funcionalidade que consumir
a API deve tratar a necessidade de autenticar novamente.

Testes automatizados (sem credenciais reais ou chamadas ao servidor):

```powershell
python -m unittest discover -s tests -v
```

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
