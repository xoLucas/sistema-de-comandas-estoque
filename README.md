# Lads Beer - Sistema de Comandas

Sistema local para gestão de comandas, estoque e financeiro da Lads Beer.

## Requisitos

- Docker Engine 24.0+ ou Docker Desktop 4.20+
- Docker Compose 2.20+

## Inicialização rápida

### Windows

1. Certifique-se de que o Docker Desktop está instalado e em execução.
2. Abra o arquivo `start.bat` (clique duplo) ou execute no terminal:

```cmd
start.bat
```

3. Acesse no navegador:

```
http://localhost:8000
```

### Linux / macOS

1. Certifique-se de que o Docker está instalado e em execução.
2. Execute no terminal:

```bash
./start.sh
```

3. Acesse no navegador:

```
http://localhost:8000
```

## Usuários padrão

| Usuário | Senha | Perfil |
|---------|-------|--------|
| gerente | admin123 | Gerente |
| caixa | caixa123 | Caixa |
| estoquista | estoque123 | Estoquista |
| sem_nome | 123456 | Garçom |

## Comandos úteis

```bash
# Iniciar em segundo plano
docker compose up -d

# Ver logs
docker compose logs -f

# Parar
docker compose down

# Parar e remover volumes (apaga dados do banco)
docker compose down -v

# Reconstruir imagem após alterações no backend
docker compose up -d --build
```

## Inicialização automática no boot

### Windows

1. Clique com o botão direito em `start.bat` e selecione **Criar atalho**.
2. Pressione `Win + R`, digite `shell:startup` e pressione Enter.
3. Cole o atalho na pasta que abrir.
4. No Docker Desktop, vá em **Settings > General** e marque **Start Docker Desktop when you sign in to your computer**.

### Linux (systemd)

Crie o arquivo `~/.config/systemd/user/ladsbeer.service`:

```ini
[Unit]
Description=Lads Beer
After=docker.service
Requires=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
WorkingDirectory=%h/ladsbeer
ExecStart=/usr/bin/docker compose up -d
ExecStop=/usr/bin/docker compose down

[Install]
WantedBy=default.target
```

Ajuste o caminho de `WorkingDirectory` para a pasta onde o projeto está.

Habilite e inicie:

```bash
systemctl --user daemon-reload
systemctl --user enable ladsbeer.service
systemctl --user start ladsbeer.service
```

## Configuração

As variáveis de ambiente ficam no arquivo `.env`. Um exemplo está disponível em `.env.example`.

Para Docker, o banco de dados é acessível pelo serviço `db`, então a `DATABASE_URL` deve usar `db` como host:

```env
DATABASE_URL=postgresql+asyncpg://postgres:123456@db:5432/ladsbeer
```

As credenciais do PostgreSQL também podem ser ajustadas via `POSTGRES_USER`, `POSTGRES_PASSWORD` e `POSTGRES_DB` no `.env`.

## Estrutura dos containers

- `ladsbeer-db`: PostgreSQL 17 com volume persistente `postgres_data`.
- `ladsbeer-app`: Backend FastAPI + frontend estático.

## Atualização

Para atualizar o sistema após alterações no código-fonte:

```bash
docker compose up -d --build
```

Se apenas arquivos estáticos (`static/` ou `templates/`) foram alterados, basta recarregar a página no navegador.

## Solução de problemas

### Porta 8000 já está em uso

Edite o `.env` e altere `APP_PORT` para outro valor, por exemplo:

```env
APP_PORT=8080
```

### Banco não inicia

Verifique os logs:

```bash
docker compose logs db
```

### Dados sumiram

Os dados do PostgreSQL são persistidos no volume `postgres_data`. Se você executou `docker compose down -v`, o volume foi removido e os dados apagados.

## Testes

O projeto inclui um teste de regressão end-to-end (`scripts/simulate_usage.py`) que cria caixas, pedidos, pagamentos, despesas, perdas e consignações e gera os relatórios.

```bash
# Instale também as dependências de desenvolvimento
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt

# Com o Docker em execução, resete o banco e rode a simulação
python3 scripts/reset_db.py --force
python3 scripts/simulate_usage.py
```
