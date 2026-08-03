# Fluxo de Caixa - Lads Beer

## Visão Geral

O módulo financeiro da Lads Beer trabalha com o conceito de **sessão de caixa**. Uma sessão define o início e o fim da contabilização do dia: o gerente ou caixa abre o caixa no início do expediente e o fecha ao final, gerando um relatório final consolidado.

> **Importante:** apenas usuários com perfil **gerente** ou **caixa** podem abrir, fechar e visualizar relatórios de caixa.

---

## Ciclo de Vida do Caixa

### 1. Abertura do Caixa

No início do expediente, o responsável deve abrir o caixa informando o valor em dinheiro disponível no momento.

- **Tela:** Financeiro > "Abrir Caixa"
- **Dado obrigatório:** `initial_cash` (dinheiro inicial)
- **Regra:** só é possível abrir um novo caixa se não houver outro com status `open`.
- **Registro:** a sessão fica vinculada ao usuário que abriu (`opened_by`) e ao horário de abertura (`opened_at`).

A partir da abertura, todas as vendas finalizadas passam a ser contabilizadas nesta sessão quando relatórios parciais ou finais forem gerados.

### 2. Relatório Parcial

Durante o expediente, o caixa/gerente pode consultar o andamento das vendas sem fechar o caixa.

- **Tela:** Financeiro > "Relatório Parcial"
- **Período:** `opened_at` até o momento atual.
- **Conteúdo:** vendas, taxas, despesas, lucro bruto/líquido, ranking de itens, fechamento de caixa parcial (sem diferença, pois o caixa ainda está aberto).

O relatório parcial é útil para conferências de meio de expediente e antecipação de valores.

### 3. Fechamento do Caixa

Ao final do expediente, o responsável fecha o caixa.

- **Tela:** Financeiro > "Fechar Caixa"
- **Dados obrigatórios:** `final_cash` (dinheiro contado no fechamento)
- **Dados opcionais:** observações sobre o fechamento
- **Regra:** o sistema bloqueia o fechamento se não houver caixa aberto.

Ao confirmar o fechamento:
1. A sessão é atualizada com `status=closed`, `closed_at` e `closed_by`.
2. O sistema gera automaticamente o **relatório final** do período.

### 4. Relatório Final

O relatório final considera o período completo da sessão: `opened_at` até `closed_at`.

- **Tela:** exibido automaticamente após o fechamento do caixa
- **Diferencial:** apresenta o **fechamento de caixa** com:
  - dinheiro inicial
  - entradas em dinheiro
  - sangria e suprimento
  - dinheiro esperado
  - dinheiro contado
  - diferença (sobra ou falta)

O relatório final pode ser baixado em PDF.

---

## Cálculos do Fechamento de Caixa

```
cash_inflows     = soma de todos os pagamentos (fechamento + parciais) com method = "dinheiro"
total_sangria    = soma das sangrias retiradas do caixa para o cofre
total_suprimento = soma dos suprimentos adicionados ao caixa
expected_cash    = initial_cash + cash_inflows - total_sangria + total_suprimento
discrepancy      = final_cash - expected_cash
```

- `discrepancy > 0`: sobra no caixa
- `discrepancy < 0`: falta no caixa
- `discrepancy = 0`: caixa conferido

> **Nota:** atualmente apenas pagamentos em dinheiro são considerados entradas de caixa físico. Pix e cartão não entram no cálculo de dinheiro esperado.
> **Nota:** despesas (diárias, fornecedores, perdas etc.) **não** entram no cálculo de dinheiro esperado, pois não representam necessariamente saída de dinheiro físico do caixa. Elas são computadas apenas no relatório financeiro (Lucro Líquido).

## Fuso Horário

Todos os relatórios financeiros e o dashboard usam o horário de Brasília (`America/Sao_Paulo`). Datas e horas são convertidas de/para UTC no banco de dados.

No relatório final/diário, os seguintes campos são exibidos no horário local:
- `period.start` / `period.end`
- `session.opened_at` / `session.closed_at`
- `movements[].created_at`
- `expenses[].expense_date` (incluindo perdas)

## Validações de Pagamentos

### Pagamento Parcial
- Só é permitido com caixa aberto.
- Valor deve ser maior que zero.
- Valor não pode exceder o restante da comanda.
- Forma de pagamento deve ser válida (`dinheiro`, `pix`, `cartao_debito`, `cartao_credito` ou `nao_informado`).

### Fechamento de Comanda
- Forma de pagamento deve ser válida.
- A lógica atual permite fechar a comanda sem caixa aberto (vendas à prazo, fiado etc.); nesses casos, o fechamento não altera o dinheiro esperado do caixa.

## Custo dos Produtos

O custo unitário é congelado no item da comanda (`order_items.unit_cost`) no momento da venda. Relatórios históricos usam esse valor; pedidos antigos sem `unit_cost` usam o custo atual do produto como fallback.

## Consignações (Fiado)

- Apenas as parcelas pagas entram como receita e nas formas de pagamento.
- O valor total das consignações, o valor pago e o saldo devedor são exibidos separadamente no relatório.
- Pagamentos de consignação em dinheiro entram no `cash_inflows` do caixa.
- Itens de consignações pagas no período também entram no `items_ranking`.

## Perdas de Estoque

Saídas manuais de estoque (registradas em `Estoque > Movimentação > Saída` sem vínculo a comanda) são computadas automaticamente nos relatórios financeiros como despesa na categoria `perdas`.

- O valor da perda é calculado como: `quantidade × preço de custo do produto`.
- As perdas são incluídas em `total_expenses`, `operating_expenses` e reduzem o `net_profit` / `net_total`.
- As perdas **não** entram no `cash_outflows` do fechamento de caixa, pois não representam saída de dinheiro físico.
- Exemplo de descrição no relatório: `Perda: Espetinho de Carne (2 un.)`.

---

## Formato dos Relatórios

### Formas de Pagamento

As formas de pagamento são agrupadas por método real (`dinheiro`, `pix`, `cartao_debito`, `cartao_credito`). Pagamentos parciais e o pagamento final são somados no mesmo método, sem linha separada de "Parcial".

### Por Hora

O gráfico `by_hour` usa o horário real de cada pagamento: horário do pagamento parcial (quando disponível) e horário de fechamento da comanda para o valor restante. Pagamentos de consignação também são incluídos no horário em que foram recebidos.

---

## Endpoints da API

### Caixa

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| GET    | `/api/caixa/ativo` | Retorna a sessão de caixa aberta, se houver. |
| GET    | `/api/caixa/sessoes` | Lista as últimas sessões de caixa. |
| POST   | `/api/caixa/abrir` | Abre uma nova sessão de caixa. |
| POST   | `/api/caixa/fechar` | Fecha a sessão de caixa atual. |

### Relatórios

| Método | Endpoint | Descrição |
|--------|----------|-----------|
| POST   | `/api/financeiro/relatorio-parcial` | Gera relatório parcial da sessão aberta. |
| GET    | `/api/financeiro/sessao/{id}/relatorio-final` | Gera relatório final de uma sessão fechada. |
| POST   | `/api/financeiro/fechamento-diario` | Relatório diário tradicional por data (mantido para consultas históricas). |
| POST   | `/api/financeiro/relatorio-pdf` | Gera PDF. Aceita `date` ou `session_id`. |

---

## Modelo de Dados

**Tabela:** `cash_register_sessions`

| Coluna | Tipo | Descrição |
|--------|------|-----------|
| `id` | integer | Identificador da sessão. |
| `opened_at` | datetime | Horário de abertura do caixa. |
| `closed_at` | datetime | Horário de fechamento (nulo enquanto aberto). |
| `opened_by_id` | integer | FK para o usuário que abriu. |
| `closed_by_id` | integer | FK para o usuário que fechou. |
| `initial_cash` | float | Valor em dinheiro no início. |
| `final_cash` | float | Valor em dinheiro contado no fechamento. |
| `status` | string | `open` ou `closed`. |
| `observations` | text | Observações do fechamento. |

---

## Experiência do Usuário

- O card de caixa na tela Financeiro mostra, em tempo real:
  - se o caixa está aberto ou fechado (indicador visual verde/vermelho)
  - horário e responsável pela abertura
  - valor inicial
  - botões contextuais disponíveis para cada estado
- Quando o caixa está fechado, o botão de "Relatório Parcial" fica oculto e só é exibido o botão "Abrir Caixa".
- Quando o caixa está aberto, o botão "Abrir Caixa" é oculto e aparecem os botões "Relatório Parcial" e "Fechar Caixa".
- O fechamento do caixa sempre gera o relatório final automaticamente, evitando que o operador esqueça de conferir o período.
- O relatório parcial exibe uma mensagem clara informando que o caixa ainda está aberto.

---

## Restrições de Permissão

| Perfil | Abrir Caixa | Fechar Caixa | Relatório Parcial | Relatório Final |
|--------|:-----------:|:------------:|:-----------------:|:---------------:|
| gerente | sim | sim | sim | sim |
| caixa | sim | sim | sim | sim |
| estoquista | não | não | não | não |
| garçom | não | não | não | não |

---

## Manutenção e Reset

Para testar o fluxo de caixa em ambiente de desenvolvimento, utilize:

```bash
bash scripts/full_reset.sh
```

Isso recria as tabelas, incluindo `cash_register_sessions`, e reinicia o servidor.
