# Plano de Execução - Instalação das Impressoras Térmicas na Lads Beer

Este documento é um **passo a passo operacional** para instalar e configurar as duas impressoras térmicas 80mm no dia da montagem do sistema. Siga na ordem indicada.

---

## 0. Material necessário

- [ ] PC do caixa com Windows ou Linux instalado
- [ ] Docker instalado no PC
  - Windows: Docker Desktop + WSL2
  - Linux: Docker Engine
- [ ] Roteador Wi-Fi com pelo menos 3 portas LAN
- [ ] 3 cabos de rede (PC + 2 impressoras)
- [ ] 2 impressoras térmicas 80mm com porta Ethernet
- [ ] Bobinas de papel térmico 80mm
- [ ] Celular para teste dos garçons
- [ ] Caneta e papel para anotar IPs e senhas

---

## 1. Preparação do ambiente

### 1.1 Posicione o equipamento

```
┌─────────────────────────────────────────────────────────────┐
│                         Balcão / Caixa                       │
│                                                              │
│   [PC do caixa]───────┐                                      │
│                       │                                      │
│   [Impressora 1]──────┼──────[Roteador]──────Wi-Fi──────────┤
│   (Cozinha)           │      (192.168.1.1)                   │
│                       │                                      │
│   [Impressora 2]──────┘                                      │
│   (Bar)                                                      │
└─────────────────────────────────────────────────────────────┘
```

- Coloque o roteador próximo ao PC do caixa.
- A impressora 1 deve ficar na **cozinha** (imprime pedidos de comida).
- A impressora 2 deve ficar no **bar** (imprime pedidos de bebida).
- O PC do caixa fica no balcão/caixa.

### 1.2 Ligue o roteador

1. Ligue o roteador na energia.
2. Conecte **apenas o PC do caixa** no roteador por cabo de rede (LAN 1).
3. Confirme que o PC recebeu um IP na rede `192.168.1.x`.

**No Windows:**
```powershell
ipconfig
```

**No Linux:**
```bash
ip addr show
```

Você deve ver algo como:
```
IPv4 Address: 192.168.1.10
```

> **Atenção:** ainda **não ligue as impressoras** no roteador.

---

## 2. Configure o roteador

### 2.1 Acesse o painel do roteador

No navegador do PC, acesse:

```
http://192.168.1.1
```

> O IP pode variar conforme o roteador. Consulte a etiqueta do roteador se `192.168.1.1` não funcionar.

### 2.2 Altere a faixa de IPs do DHCP (se necessário)

Garanta que o roteador distribua IPs na faixa `192.168.1.x`.

Sugestão de configuração:

| Dispositivo | IP | Descrição |
|-------------|-----|-----------|
| Roteador | `192.168.1.1` | Gateway |
| PC do caixa | `192.168.1.10` | Fixo ou DHCP |
| Impressora 1 | `192.168.1.101` | Reservado |
| Impressora 2 | `192.168.1.102` | Reservado |

### 2.3 Faça reserva DHCP pelos MAC addresses

1. No painel do roteador, procure por **DHCP Reservation**, **Reserva de Endereço** ou **IP Binding**.
2. Mais tarde, quando ligar cada impressora, anote o MAC address do self-test e vincule ao IP correspondente.

> Se o roteador não tiver reserva DHCP, configure IP estático diretamente na impressora.

---

## 3. Configure a Impressora 1 (Cozinha)

**Importante:** configure uma impressora de cada vez. Ambas vêm com IP `192.168.1.100` de fábrica.

### 3.1 Conecte e ligue

1. Coloque o papel na impressora.
2. Conecte o cabo de rede da impressora 1 no roteador (LAN 2).
3. Ligue a impressora 1 na energia.
4. Aguarde cerca de 30 segundos para ela inicializar.

### 3.2 Descubra o IP atual

1. Desligue a impressora 1.
2. Pressione e segure o botão **FEED**.
3. Ligue a impressora 1.
4. Aguarde o LED **ERROR** acender.
5. Solte o botão **FEED**.
6. A impressora imprimirá uma página com informações de rede.

Anote:
- **MAC Address**: `_________________________`
- **IP Address**: `_________________________`
- **DHCP**: `_________________________`

### 3.3 Defina o IP fixo

A impressora provavelmente recebeu um IP via DHCP (ex: `192.168.1.100`).

#### Opção A - pela interface web (recomendada)

1. No PC do caixa, abra o navegador.
2. Acesse o IP atual da impressora:
   ```
   http://192.168.1.100
   ```
3. Faça login (consulte o manual se pedir usuário/senha).
4. Vá em **Network Settings** ou **Configuração de Rede**.
5. Altere para:
   - **IP Address**: `192.168.1.101`
   - **Subnet Mask**: `255.255.255.0`
   - **Gateway**: `192.168.1.1`
   - **DHCP**: `Disabled`
6. Salve e reinicie a impressora.

#### Opção B - pelo driver no Windows

1. Baixe o driver em: `http://www.cnfujun.com/d/33`
2. Instale o driver da impressora 80mm.
3. Vá em **Impressoras e scanners** → propriedades da impressora.
4. Clique em **Ports** → **Add Port**.
5. Escolha **Standard TCP/IP Port**.
6. Digite o IP atual (`192.168.1.100`).
7. Escolha **Generic Network Card**.
8. Configure a porta para o IP `192.168.1.101`.
9. Imprima uma página de teste.

### 3.4 Faça a reserva DHCP no roteador

1. No painel do roteador, procure o MAC address da impressora 1.
2. Vincule o MAC ao IP `192.168.1.101`.

### 3.5 Teste a conectividade

**No Windows:**
```powershell
ping 192.168.1.101
Test-NetConnection -ComputerName 192.168.1.101 -Port 9100
```

**No Linux:**
```bash
ping -c 4 192.168.1.101
nc -vz 192.168.1.101 9100
```

Se ambos funcionarem, a impressora 1 está pronta.

---

## 4. Configure a Impressora 2 (Bar)

Repita o mesmo processo da impressora 1, mas usando o IP `192.168.1.102`.

### 4.1 Conecte e ligue

1. Desconecte a impressora 1 do roteador (opcional, mas evita confusão).
2. Conecte a impressora 2 no roteador (LAN 3).
3. Ligue a impressora 2.

### 4.2 Descubra o IP atual

Use o mesmo procedimento do self-test (FEED + POWER).

Anote:
- **MAC Address**: `_________________________`
- **IP Address**: `_________________________`

### 4.3 Defina o IP fixo

Configure para:
- **IP Address**: `192.168.1.102`
- **Subnet Mask**: `255.255.255.0`
- **Gateway**: `192.168.1.1`
- **DHCP**: `Disabled`

### 4.4 Faça a reserva DHCP no roteador

Vincule o MAC da impressora 2 ao IP `192.168.1.102`.

### 4.5 Teste a conectividade

**No Windows:**
```powershell
ping 192.168.1.102
Test-NetConnection -ComputerName 192.168.1.102 -Port 9100
```

**No Linux:**
```bash
ping -c 4 192.168.1.102
nc -vz 192.168.1.102 9100
```

### 4.6 Reconecte a impressora 1

Se desconectou a impressora 1, reconecte-a ao roteador.

---

## 5. Teste de impressão direto no PC

Antes de subir o sistema Lads Beer, teste se o PC consegue imprimir nas duas impressoras.

### 5.1 Baixe o projeto no PC do caixa

Se ainda não tiver o projeto no PC:

```bash
git clone <URL_DO_REPOSITORIO> ladsbeer
cd ladsbeer
```

### 5.2 Rode o script de teste

```bash
# Linux
python3 scripts/test_printer.py --ip 192.168.1.101
python3 scripts/test_printer.py --ip 192.168.1.102

# Windows
python scripts/test_printer.py --ip 192.168.1.101
python scripts/test_printer.py --ip 192.168.1.102
```

Se tudo estiver certo, cada impressora imprimirá um ticket de teste.

> Se não quiser gastar papel, use `--preview` para ver como ficaria sem imprimir.

---

## 6. Inicie o sistema Lads Beer

### 6.1 Windows

Abra o terminal na pasta do projeto e execute:

```cmd
start.bat
```

### 6.2 Linux

Abra o terminal na pasta do projeto e execute:

```bash
bash start.sh
```

### 6.3 Aguarde a inicialização

O Docker vai:
1. Subir o banco de dados PostgreSQL.
2. Subir o backend FastAPI.
3. Executar o seed com as configurações padrão.

Aguarde cerca de 20 a 30 segundos.

### 6.4 Verifique se o sistema está no ar

No PC do caixa, abra o navegador:

```
http://localhost:8000
```

A tela de login deve aparecer.

---

## 7. Configure as impressoras dentro do sistema

1. Acesse `http://localhost:8000`.
2. Faça login com o usuário **gerente**:
   - Usuário: `gerente`
   - Senha: `admin123`
3. Vá em **Configurações**.
4. Verifique se os valores estão assim:

| Configuração | Valor esperado |
|--------------|----------------|
| `printer_1_name` | Impressora Cozinha |
| `printer_1_ip` | `192.168.1.101` |
| `printer_1_port` | `9100` |
| `printer_1_width` | `48` |
| `printer_2_name` | Impressora Bar |
| `printer_2_ip` | `192.168.1.102` |
| `printer_2_port` | `9100` |
| `printer_2_width` | `48` |
| `printer_cozinha` | `1` |
| `printer_bar` | `2` |
| `printer_nota` | `1` ou `2` |

5. Se algum valor estiver diferente, corrija.

---

## 8. Teste a impressão pelo sistema

### 8.1 Teste via endpoint

No PC do caixa, abra o terminal e faça login para obter o token:

```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"gerente","password":"admin123"}'
```

Copie o valor de `access_token` e use nos comandos abaixo:

```bash
curl -X POST http://localhost:8000/api/impressoras/1/teste \
  -H "Authorization: Bearer SEU_TOKEN_AQUI"

curl -X POST http://localhost:8000/api/impressoras/2/teste \
  -H "Authorization: Bearer SEU_TOKEN_AQUI"
```

Cada comando deve fazer a impressora correspondente imprimir um ticket de teste.

### 8.2 Teste via operação real

1. Crie uma mesa de teste.
2. Adicione um item de comida (ex: Espetinho de Carne).
3. Verifique se a **Impressora 1 (Cozinha)** imprimiu o ticket.
4. Adicione um item de bebida (ex: Cerveja Lata).
5. Verifique se a **Impressora 2 (Bar)** imprimiu o ticket.

---

## 9. Teste o acesso pelo celular

1. Conecte um celular ao Wi-Fi do roteador da Lads Beer.
2. Abra o navegador do celular.
3. Acesse:
   ```
   http://192.168.1.10:8000
   ```
   > Substitua `192.168.1.10` pelo IP real do PC do caixa.
4. A tela de login deve aparecer.
5. Faça login com um usuário garçom e teste registrar um pedido.

---

## 10. Verificação final

- [ ] PC do caixa ligado e conectado ao roteador por cabo.
- [ ] Roteador ligado e Wi-Fi funcionando.
- [ ] Impressora 1 ligada e conectada ao roteador.
- [ ] Impressora 2 ligada e conectada ao roteador.
- [ ] Impressora 1 responde ao `ping 192.168.1.101`.
- [ ] Impressora 2 responde ao `ping 192.168.1.102`.
- [ ] `scripts/test_printer.py` imprime na impressora 1.
- [ ] `scripts/test_printer.py` imprime na impressora 2.
- [ ] Sistema Lads Beer iniciado via `start.bat` ou `start.sh`.
- [ ] Acesso `http://localhost:8000` funciona no PC.
- [ ] Configurações de impressora estão corretas no sistema.
- [ ] Endpoint `/api/impressoras/1/teste` imprime ticket.
- [ ] Endpoint `/api/impressoras/2/teste` imprime ticket.
- [ ] Pedido de comida imprime na impressora 1.
- [ ] Pedido de bebida imprime na impressora 2.
- [ ] Celular conectado ao Wi-Fi acessa o sistema.
- [ ] Sistema funciona sem internet.

---

## 11. Troubleshooting rápido

| Problema | Solução |
|----------|---------|
| Não consegue acessar `192.168.1.100` | A impressora pode ter recebido outro IP via DHCP. Imprima o self-test novamente. |
| `ping` funciona, mas não imprime | Verifique se a porta 9100 está aberta (`nc -vz IP 9100`). |
| As duas impressoras têm o mesmo IP | Configure uma de cada vez. Desligue uma enquanto configura a outra. |
| O sistema não encontra a impressora | Confira os IPs e portas em **Configurações**. |
| Ticket com corte no meio | Ajuste `printer_width` para `48` (papel 80mm). |
| Celular não acessa o sistema | Verifique se o celular está no mesmo Wi-Fi do roteador da Lads Beer. |
| Sistema não sobe no Docker | Execute `docker compose logs app` para ver o erro. |

---

## 12. Contatos e referências

- Manual da impressora: `80MM Printer Instruction Manual.pdf`
- Manual do programador: `80MM Printer Programmer Manual.pdf`
- Configuração WiFi: `WIFI Printer Configuration Methods.pdf`
- Drivers: `http://www.cnfujun.com/d/33`
- Documentação técnica do sistema: `docs/IMPRESSORAS.md`

---

**Pronto!** Com este plano, a instalação das impressoras na Lads Beer deve ser feita de forma organizada e sem erros.
