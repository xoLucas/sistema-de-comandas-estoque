# Guia de Configuração das Impressoras Térmicas - Lads Beer

Este guia explica como configurar as duas impressoras térmicas **80mm ESC/POS** no sistema Lads Beer, funcionando tanto em **Windows** quanto em **Linux**, sem depender de internet.

---

## 1. Especificações do hardware

| Especificação | Valor |
|---------------|-------|
| Modelo | Impressora térmica 80mm genérica ESC/POS (CNFujun ou similar) |
| Largura do papel | 80mm |
| Largura de impressão | 72mm |
| Comando | ESC/POS |
| Interfaces | USB / Ethernet RJ45 / Serial RS232 / Bluetooth / WiFi |
| Porta Ethernet | 9100 (raw socket) |
| Velocidade da rede | 10M/100M |
| IP padrão de fábrica | `192.168.1.100` |
| Corte | Parcial / total |

O sistema envia os tickets diretamente para o **IP da impressora na porta 9100**, usando comandos ESC/POS puros. Não é necessário instalar driver dentro do Docker: basta que o PC consiga acessar os IPs das impressoras na rede local.

---

## 2. Arquitetura de rede recomendada

```
                 ┌─────────────────┐
                 │   Roteador      │
                 │  192.168.1.1    │
                 │  Wi-Fi + 3 LAN  │
                 └────────┬────────┘
                          │
        ┌─────────────────┼─────────────────┐
        │                 │                 │
   [PC do caixa]   [Impressora 1]    [Impressora 2]
 192.168.1.10     192.168.1.101     192.168.1.102
        │                 │                 │
        │            cabo ethernet     cabo ethernet
        │                 │                 │
        └─────────────────┴─────────────────┘
                          │
                    [Celulares dos garçons]
                       via Wi-Fi
```

- O roteador **não precisa de internet**.
- PC, impressoras e celulares devem estar na mesma rede `192.168.1.x`.
- Recomendamos reservar IPs fixos no roteador para as impressoras.

---

## 3. Requisitos do PC (servidor)

| Sistema | Requisito |
|---------|-----------|
| Windows | Docker Desktop com WSL2 |
| Linux | Docker Engine |

O sistema roda dentro de um container Docker. As impressoras são acessadas pela rede local (LAN), não por USB direto no PC.

---

## 4. Configurando as impressoras pela primeira vez

**Importante:** configure uma impressora de cada vez. Ambas vêm com o mesmo IP de fábrica (`192.168.1.100`). Se ligar as duas ao mesmo tempo antes de mudar o IP, haverá conflito.

### 4.1 Descobrir o IP atual da impressora

1. Desligue a impressora.
2. Pressione e segure o botão **FEED** (alimentação de papel).
3. Ligue a impressora.
4. Aguarde o LED **ERROR** acender.
5. Solte o botão **FEED**.
6. A impressora imprimirá uma página de **self-test** com:
   - MAC Address
   - IP Address
   - Netmask
   - Gateway
   - DHCP status

### 4.2 Definir IP fixo em cada impressora

Sugestão de IPs:

| Impressora | IP sugerido | Função típica |
|------------|-------------|---------------|
| Impressora 1 | `192.168.1.101` | Cozinha |
| Impressora 2 | `192.168.1.102` | Bar |

Você pode configurar o IP de duas formas:

#### Opção A — pelo driver no Windows (mais visual)

1. Baixe o driver em: `http://www.cnfujun.com/d/33`
2. Instale o driver da impressora 80mm.
3. Nas propriedades da impressora, clique em **Ports** → **Add Port**.
4. Escolha **Standard TCP/IP Port**.
5. Digite o IP atual da impressora (ex: `192.168.1.100`).
6. Escolha **Generic Network Card**.
7. Após criar a porta, clique em **Configure Port** e altere o IP para o desejado (`192.168.1.101` ou `192.168.1.102`).
8. Imprima uma página de teste para confirmar.

#### Opção B — pela interface web (Windows ou Linux)

1. Conecte a impressora ao roteador.
2. No PC, abra o navegador e acesse o IP atual da impressora: `http://192.168.1.100`
3. Faça login (se necessário, consulte o manual).
4. Vá até as configurações de rede e altere para:
   - **IP**: `192.168.1.101` (ou `192.168.1.102`)
   - **Subnet Mask**: `255.255.255.0`
   - **Gateway**: `192.168.1.1`
   - **DHCP**: Disabled (IP estático)
5. Salve e reinicie a impressora.

### 4.3 Reservar IP no roteador (recomendado)

Mesmo configurando IP estático na impressora, recomendamos vincular o MAC Address de cada uma a um IP no roteador (reserva DHCP). Assim o IP nunca muda, mesmo após reset de fábrica.

---

## 5. Testando a conectividade

Antes de subir o sistema, verifique se o PC consegue falar com as impressoras.

### Windows (PowerShell)

```powershell
Test-NetConnection -ComputerName 192.168.1.101 -Port 9100
Test-NetConnection -ComputerName 192.168.1.102 -Port 9100
```

### Linux

```bash
nc -vz 192.168.1.101 9100
nc -vz 192.168.1.102 9100
```

Se a conexão for bem-sucedida, a impressora está pronta para receber tickets.

---

## 6. Testando a impressão (script standalone)

O projeto inclui um script para testar a impressora sem precisar subir o Docker.

```bash
# Linux
python3 scripts/test_printer.py --ip 192.168.1.101

# Windows
python scripts/test_printer.py --ip 192.168.1.101
```

Opções disponíveis:

```bash
python scripts/test_printer.py --ip 192.168.1.101 --port 9100 --width 48
python scripts/test_printer.py --ip 192.168.1.101 --no-cut
python scripts/test_printer.py --ip 192.168.1.101 --preview
```

| Parâmetro | Descrição |
|-----------|-----------|
| `--ip` | IP da impressora (obrigatório) |
| `--port` | Porta (padrão 9100) |
| `--width` | Largura do ticket em colunas (padrão 48 para papel 80mm) |
| `--no-cut` | Não envia comando de corte |
| `--preview` | Mostra preview no terminal sem imprimir |

---

## 7. Iniciando o sistema

### Windows

```cmd
start.bat
```

### Linux

```bash
bash start.sh
```

O sistema ficará disponível em:

```
http://IP-DO-PC:8000
```

Exemplo: se o PC do caixa tem IP `192.168.1.10`, os garçons acessam pelo celular:

```
http://192.168.1.10:8000
```

---

## 8. Configurando as impressoras no sistema

1. Acesse o sistema no PC do caixa: `http://localhost:8000`
2. Faça login com um usuário **gerente**.
3. Vá em **Configurações**.
4. Preencha as configurações de impressora:

| Configuração | Valor sugerido |
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
| `printer_nota` | `1` (ou `2`, conforme preferir) |

5. Salve as configurações.

---

## 9. Testando pelo sistema

O backend possui um endpoint para enviar um ticket de teste:

```bash
curl -X POST http://localhost:8000/api/impressoras/1/teste \
  -H "Authorization: Bearer SEU_TOKEN_AQUI"
```

Ou use a própria interface do sistema (quando disponível) para clicar em **Testar Impressora**.

---

## 10. Roteamento automático de pedidos

O sistema separa os itens automaticamente entre cozinha e bar, conforme a categoria do produto:

- Produtos da categoria **Cozinha** (espetinhos, acompanhamentos, porções) → Impressora 1
- Produtos da categoria **Bar** (bebidas, cervejas, refrigerantes) → Impressora 2

Você pode ajustar isso em:
- **Estoque > Categorias**: campo `printer`
- **Estoque > Produtos**: campo `printer` (sobrescreve a categoria)

---

## 11. Tipos de tickets impressos

O sistema imprime três tipos de tickets:

1. **Ticket de cozinha** → itens que precisam de preparo
2. **Ticket de bar** → bebidas
3. **Nota não fiscal / recibo** → conta finalizada do cliente

A nota não fiscal é impressa na impressora configurada em `printer_nota`.

---

## 12. Solução de problemas

### A impressora não imprime

1. Verifique se a impressora está ligada e com papel.
2. Verifique se o cabo de rede está bem conectado.
3. Imprima o **self-test** e confirme o IP atual.
4. Teste a conectividade com `ping` e `nc`/`Test-NetConnection`.
5. Rode o script `scripts/test_printer.py --ip IP_DA_IMPRESSORA`.
6. Verifique as configurações em **Configurações > Impressoras** no sistema.

### Conexão recusada na porta 9100

- A impressora pode estar offline.
- O IP pode estar errado.
- A impressora pode não estar na mesma sub-rede do PC.

### As duas impressoras têm o mesmo IP

- Desligue uma delas.
- Configure o IP de uma por vez.
- Reinicie as impressoras após mudar os IPs.

### O container Docker não acessa a impressora

- Certifique-se de que o PC host consegue pingar a impressora.
- O Docker usa a rede do host para acessar a LAN; se o host consegue, o container consegue.
- Verifique se não há firewall bloqueando a porta 9100.

### Ticket cortado no meio ou layout estranho

- Ajuste `printer_1_width` / `printer_2_width`:
  - Papel 58mm → `32`
  - Papel 80mm → `48`

---

## 13. Checklist de instalação

- [ ] Roteador ligado e Wi-Fi funcionando
- [ ] PC do caixa conectado ao roteador por cabo
- [ ] Impressora 1 conectada ao roteador por cabo
- [ ] Impressora 2 conectada ao roteador por cabo
- [ ] IP da impressora 1 alterado para `192.168.1.101`
- [ ] IP da impressora 2 alterado para `192.168.1.102`
- [ ] Reserva DHCP configurada no roteador (opcional, mas recomendado)
- [ ] `ping 192.168.1.101` e `ping 192.168.1.102` funcionam do PC
- [ ] `scripts/test_printer.py --ip 192.168.1.101` imprime ticket de teste
- [ ] `scripts/test_printer.py --ip 192.168.1.102` imprime ticket de teste
- [ ] Sistema iniciado via `start.bat` ou `start.sh`
- [ ] Configurações de impressora preenchidas no sistema
- [ ] Endpoint `/api/impressoras/1/teste` e `/api/impressoras/2/teste` respondem com sucesso
- [ ] Celular conectado ao Wi-Fi e acessando `http://IP-DO-PC:8000`

---

## 14. Resumo

| Componente | Configuração |
|------------|--------------|
| Impressoras | 2x 80mm ESC/POS Ethernet |
| IPs sugeridos | `192.168.1.101` e `192.168.1.102` |
| Porta | `9100` raw socket |
| Largura do ticket | `48` colunas (papel 80mm) |
| Função padrão | Impressora 1 = Cozinha, Impressora 2 = Bar |
| Sistema | Docker rodando em Windows ou Linux |
| Acesso dos garçons | Celular via Wi-Fi pelo IP do PC na porta 8000 |
| Internet | Não necessária |

Com essa configuração, o sistema fica 100% offline, rápido e confiável para a operação da Lads Beer.
