# Radar IoT

Arduino Uno e dois HC-SR04, espaçados em 15 cm. O sketch que já funcionou continua na placa. Cada passagem gera uma linha JSON. O coletor Python abre a porta COM, ignora os logs iniciados por `#`, valida o evento e envia um POST HTTP. O FastAPI grava em SQLite e o navegador consulta a API a cada 2,5 s.

**Arduino → USB / COM3 → coletor Python → FastAPI / SQLite → dashboard**

## Preparação para a apresentação

1. [Implante a API no Render](https://render.com/deploy?repo=https%3A%2F%2Fgithub.com%2FGustavoBerengani%2FRadar-IoT). O Blueprint cria um serviço gratuito, configura a origem do painel e gera a chave de ingestão. Quando o serviço estiver ativo, copie a URL HTTPS e localize `RADAR_API_KEY` em **Environment**. O banco SQLite do plano gratuito pode ser descartado em reinícios e deploys.
2. Configure `RADAR_API_URL` como variável do repositório no GitHub e execute **Publicar painel** conforme a seção de GitHub Pages abaixo.
3. No notebook Windows, instale Python 3.10 ou superior, extraia o ZIP do repositório e conecte o Arduino. Abra o PowerShell na pasta extraída e rode:

   ```powershell
   powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\iniciar-radar.ps1
   ```

   O iniciador instala as dependências, lista as portas e pede a COM, a URL HTTPS e a chave. A chave é digitada sem aparecer na tela e não é gravada pelo iniciador.
4. Faça uma passagem real e confira **Enviado ao dashboard** no terminal e a leitura no histórico. Faça esse ensaio primeiro no notebook disponível.

## Primeiro teste com o Arduino no Windows

1. Extraia o ZIP. Abra PowerShell na pasta extraída, onde está este README.
2. Instale Python 3.10 ou superior, se necessário. Rode:

   ```powershell
   py -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   .\.venv\Scripts\python.exe -m uvicorn app:app
   ```

3. Abra http://127.0.0.1:8000 no navegador. O painel inicia vazio.
4. **Feche o Monitor Serial da Arduino IDE**, para liberar a porta COM3. Mantenha o USB conectado.
5. Abra um segundo PowerShell na mesma pasta e execute:

   ```powershell
   .\.venv\Scripts\python.exe coletor.py --porta COM3 --baud 115200
   ```

6. Aguarde “Serial aberta”, deixe a pista livre por um instante e passe o carrinho de S1 para S2. No terminal aparecem “Capturado” e “Enviado ao dashboard”. O novo registro entra no painel em até alguns segundos.
7. Para parar, pressione Ctrl+C no terminal do coletor. O histórico continua no banco.

A data do registro é o instante em que o coletor recebeu o JSON. O limite vem do firmware Arduino, atualmente 4 km/h. A indicação de Arduino conectado significa que o coletor abriu a porta serial. A passagem no histórico confirma o funcionamento dos sensores.


## Apresentar em outro aparelho da mesma rede

Inicie o servidor com `--host 0.0.0.0` e mantenha o coletor no computador ligado ao Arduino. No celular ou outro PC da mesma rede, abra `http://IP-DO-COMPUTADOR:8000`. Use `ipconfig` para encontrar o IPv4. Se precisar liberar a porta no firewall, use somente o perfil de rede privada. O modo local sem chave dá acesso de edição a quem alcançar o servidor.

## Publicar na internet

A aplicação pode ser executada em uma hospedagem de containers com HTTPS e volume persistente. O Dockerfile serve a interface e o FastAPI na mesma URL. A máquina com o Arduino continua rodando apenas o coletor, que faz conexões de saída. Aponte o coletor para essa URL após publicar.

- Monte um volume em `/data` para persistir o SQLite.
- Configure no servidor `RADAR_API_KEY` com uma chave longa e aleatória.
- O dashboard e suas consultas são legíveis por quem puder acessar a URL. Se a apresentação for restrita, use os controles de acesso da hospedagem de forma compatível com o coletor ou mantenha na rede local.
- No PowerShell do computador com o Arduino, configure a mesma chave de ingestão e inicie o coletor com a URL HTTPS do servidor:

  ```powershell
  $env:RADAR_API_KEY = "COLE_A_CHAVE_CONFIGURADA_NO_SERVIDOR"
  .\.venv\Scripts\python.exe coletor.py --porta COM3 --api https://seu-servidor
  ```

Antes de trocar entre servidor local e remoto, encerre o coletor e confira a fila pendente. Use `--fila fila_remota.sqlite3` se quiser filas independentes.

## Diagnóstico

| Sintoma | Ação |
|---|---|
| Acesso negado à COM3 | Feche o Monitor Serial e outros programas que estejam usando a porta. |
| Porta não encontrada | Confirme a COM atual na Arduino IDE e ajuste `--porta`. |
| Capturado, mas envio pendente | Verifique se a API está rodando, a URL e, se usada, a chave. A fila em SQLite mantém as passagens até o próximo envio. |
| Painel sem passagens | Confirme se o carrinho passou de S1 para S2. |
| HTTP 401 | Verifique se a chave do coletor é a mesma do servidor. |

API interativa em http://127.0.0.1:8000/docs.

## Publicar o painel pelo GitHub Pages

O repositório contém o coletor, a API e o painel. O GitHub Pages publica o painel. O Render ou outro host Docker executa a API Python e guarda o SQLite.

1. Crie um repositório no GitHub (sugestão: `radar-iot`) e envie o conteúdo desta pasta para a branch `main`, incluindo `.github/workflows/pages.yml`. Em uma conta GitHub Free, use um repositório público para disponibilizar o GitHub Pages.
2. No repositório, acesse **Settings → Pages → Build and deployment → Source → GitHub Actions**.
3. Crie o serviço Docker no Render usando o mesmo repositório. Em **Environment**, configure `RADAR_API_KEY` com uma chave aleatória e `RADAR_PAGES_ORIGIN` com `https://SEU-USUARIO.github.io` (sem `/radar-iot`). Se contratar disco persistente, monte-o em `/data`.
4. No GitHub, em **Settings → Secrets and variables → Actions → Variables**, crie a variável `RADAR_API_URL` com a URL HTTPS do serviço (sem `/api`). Essa URL é pública. Mantenha a chave fora do GitHub Pages e do repositório.
5. Em **Actions → Publicar painel → Run workflow**, execute o workflow em `main`. Quando concluir, abra a URL exibida em **Settings → Pages**.
6. No Windows, execute o coletor apontando para a **URL do Render**, conforme a seção anterior. Passe o carrinho de S1 para S2 e confira se o registro entra no histórico do GitHub Pages.

Se o painel abrir mas mostrar servidor sem resposta, confira se o serviço Docker está ativo, a variável `RADAR_API_URL` foi aplicada pelo workflow e a origem `RADAR_PAGES_ORIGIN` corresponde à origem do painel.
