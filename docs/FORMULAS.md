# Fórmulas do Sistema — Lads Beer

Este documento centraliza **todas as fórmulas/regras de cálculo** do sistema e **onde
elas estão no código**. Ele existe para garantir que qualquer alteração em uma fórmula
seja rastreada em **todas as suas incidências** — pois uma mesma regra costuma aparecer
em vários lugares (backend de venda, fechamento, relatório, dashboard, impressão e
frontend). Ajustar apenas um deles gera inconsistência e **prejuízo financeiro ao cliente**.

> ⚠️ **Regra de ouro (ver AGENTS.md):** antes de alterar qualquer fórmula, localize e
> revise **todas** as ocorrências dela no sistema. Sempre que possível, centralize a
> fórmula em um único helper reutilizado por todos os consumidores.

---

## 1. Preços e margem

Todos os valores monetários são persistidos com 2 casas decimais; custos e taxas,
com 4 casas. O arredondamento canônico é `ROUND_HALF_UP`, centralizado em
`app/services/money_service.py`.

| Fórmula | Código |
|---------|--------|
| Preço de venda a partir de custo + margem sobre venda: `selling_price = cost / (1 − margin_pct/100)` | `app/services/pricing_service.py` → `calculate_selling_price()` |
| Margem a partir de custo + preço: `margin_pct = ((selling_price − cost) / selling_price) × 100` | `app/services/pricing_service.py` → `calculate_margin_pct()` |
| Preço promocional: `discounted_price = price × (1 − best_discount/100)`, com `best_discount = max(discount_pct)` entre as promoções ativas do produto | `app/services/promotion_service.py` → `calculate_discounted_price()` / `get_discounted_price()` |
| Campo `discounted_price` do payload de produtos | `app/routers/products.py` |

**Onde `get_discounted_price()` é consumido (todas as incidências):**
- `app/routers/orders.py` — `create_pedido`, `add_order_item`, `add_pending_order_item`
- `app/routers/consignments.py` — `_consume_stock_for_items` (criação de consignado/atacado)
- `app/routers/products.py` — listagem de produtos

---

## 2. Estoque e engradados (packs)

| Fórmula | Código |
|---------|--------|
| É engradado: `is_pack = product.pack_unit_product_id IS NOT NULL` | `app/services/stock_service.py` → `is_pack()` |
| Estoque do engradado em unidades de venda: `pack_stock = unit.stock // pack_size` | `app/services/stock_service.py` → `pack_stock_for_product()` |
| Custo total do estoque físico: `Σ (unit.cost × unit.stock)` somente para produtos unitários; engradados são ignorados por refletirem o mesmo estoque | `app/services/stock_service.py` → `inventory_cost_for_product()` / `total_inventory_cost()`; `app/routers/dashboards.py` → `dashboard_estoque()` |
| Conversão física no consumo: `unit_quantity = requested_packs × pack_size` | `app/routers/orders.py` → `_resolve_pack_stock()` |
| Consumo de estoque: `stock -= unit_quantity` (checa insuficiência antes) | `app/routers/orders.py` → `_check_and_consume_stock()`; `app/routers/consignments.py` → `_check_and_consume_stock_consignment()`; `app/routers/stock.py` → `_apply_pack_stock_change()` |
| Status: pack `em_falta` se `pack_stock ≤ 0`; unitário `em_falta` se `stock ≤ 2`; ambos `em_risco` se `≤ min_stock` | `app/services/stock_service.py` → `stock_status()` |
| Custo (COGS) de item = `unit_cost` congelado no momento da venda (fallback: custo atual do produto) | `app/routers/orders.py` (criação do `OrderItem`) e `app/routers/financial.py` |
| Histórico de engradado grava `source_quantity` em engradados, `conversion_factor = pack_size`, `quantity` em unidades físicas e `unit_cost_snapshot` do produto físico | `app/routers/orders.py`, `app/routers/stock.py`, `app/services/refund_service.py` |

---

## 3. Comanda — total, pagamento parcial e fechamento

| Fórmula | Código |
|---------|--------|
| Total da comanda: `order.total = Σ (unit_price × quantity)` | `app/routers/orders.py` → `create_pedido`, `add_order_item` (recalculado por `SUM`) |
| **Pagamento parcial — modelo:** o operador informa o **valor a abater (produto)**; o **Total a pagar** é `abater + serviço/gorjeta` e é esse total que é enviado como `amount` | `static/app.js` → `updatePartialPaymentSummary()` / `submitPartialPayment()` |
| **Parcial com gorjeta fixa (custom):** `product_portion = total_a_pagar − custom`, `service_portion = custom` | `app/routers/orders.py` → `partial_payment` (bloco `custom`) |
| **Parcial com taxa %:** `product_portion = total_a_pagar / (1 + pct/100)`, `service_portion = total_a_pagar − product_portion` | `app/routers/orders.py` → `partial_payment` (bloco `apply_service_charge`) |
| **Parcial sem taxa:** `product_portion = total_a_pagar`, `service_portion = 0` | `app/routers/orders.py` → `partial_payment` |
| Acumuladores: `partial_payment += product_portion`; `partial_service_charge += service_portion` | `app/routers/orders.py` → `partial_payment` |
| Fechamento — restante de produto: `remaining_product = max(0, total − partial_payment)` | `app/routers/orders.py` → `close_order` |
| Fechamento — taxa: `service_charge_amount = remaining_product × (pct/100)` (ou gorjeta custom) | `app/routers/orders.py` → `close_order` |
| Fechamento — final: `final_total = remaining_product + remaining_service` | `app/routers/orders.py` → `close_order` |
| Taxa total persistida: `order.service_charge_amount = partial_service_charge + remaining_service` | `app/routers/orders.py` → `close_order` |

> **Atenção no pagamento parcial:** o `amount` enviado ao backend é o **Total a pagar**
> (abater + serviço/gorjeta), não o valor a abater isolado. O troco é calculado sobre
> esse total. No modo "Por Itens", o abater é o subtotal dos itens selecionados (produto).
> A taxa de serviço/gorjeta do parcial é **apenas do pagamento atual** (`partial_service_charge`)
> e **não aumenta o restante da conta** dos demais membros da mesa — o "Restante" exibido
> e a validação usam somente o produto (`order.total − order.partial_payment`). O "Já pago"
> do modal de pagamento parcial também mostra só o produto abatido (`order.partial_payment`);
> a gorjeta paga fica em `partial_service_charge` (registrada à parte, nunca no abatimento).

> **Atenção:** `order.service_charge_amount` (persistido) **inclui** o serviço já pago em
> parciais; já o `final_total` usa **apenas** o serviço do restante. Não confundir os dois.

---

## 4. Impressão da nota (Nota Não Fiscal)

| Fórmula | Código |
|---------|--------|
| **Mesa comum — sem taxa (`SUBTOTAL`):** `subtotal = max(0, total_da_nota − produto_já_pago)` | `app/routers/orders.py` → `_print_order_receipt()` |
| **Mesa comum — com taxa (`TOTAL`):** `total_com_taxa = subtotal + percentage_amount(subtotal, pct_configurado)`, exibido como `TAXA OPCIONAL (pct%)` | idem |
| Gorjeta já recebida em pagamentos parciais: exibida separadamente (`GORJETA JA PAGA`), nunca recalculada nem cobrada de novo | idem |
| **Balcão:** `pago_agora = (total − produto_pago_anteriormente) + (taxa_total − serviço_pago_anteriormente)` | idem e `app/services/printer_service.py` → `build_order_receipt()` |
| Balcão em dinheiro: `troco = valor_recebido − pago_agora` | `app/routers/orders.py` → `close_order()` |
| Reimpressão por falha | usa o snapshot completo da nota original, inclusive horário, valores recebidos e troco | `app/services/notification_service.py` / `app/routers/notifications.py` |

**Rótulos na nota de mesa (redesenhados):** `TOTAL PRODUTOS` → `PAGO ANTES
(PRODUTOS)` (se houver) → `SUBTOTAL` (valor sem taxa) → `TAXA OPCIONAL (pct%)` →
`TOTAL` (valor com taxa). Os antigos rótulos `A PAGAR SEM TAXA` /
`A PAGAR COM TAXA` foram substituídos por `SUBTOTAL` / `TOTAL`
(`app/services/printer_service.py` → branch `table_quote`).

**Tipos de nota:**

- **Mesa comum:** é uma cotação. Sempre mostra ambas as opções de pagamento, com e
  sem a taxa configurada, para decisão do cliente. A decisão é lançada depois pelo
  garçom no fechamento e não é persistida pela impressão.
- **Nota modificada:** os itens, cliente e identificação podem divergir da comanda
  apenas no papel, mas o backend recalcula subtotais e as duas opções de pagamento.
- **Balcão:** é um comprovante definitivo; mostra somente o valor efetivamente
  computado, a forma de pagamento, o valor recebido e o troco.
- **Estornada/cancelada:** recebe marca textual `NÃO COBRAR` e exibe apenas o valor
  original para referência histórica.

**Incidências de impressão da nota:** fechamento do balcão (`close_order`), botão
`/comanda/{id}/imprimir-nota` e reimpressão de notificação
(`app/routers/notifications.py` → `_rebuild_printer_data`). Todas passam por
`build_order_receipt` e usam o mesmo conteúdo textual no simulador de terminal.

> ⚠️ Para editar a lógica da nota, verifique **backend + frontend** juntos: o rascunho da
> nota no navegador (`static/app.js` → `buildPrintReceiptDraftFromOrder`,
> `recalculatePrintReceiptDraft`, `renderPrintReceiptView`, `confirmPrintReceipt`)
> recalcula os mesmos valores e envia ao backend.

---

## 5. Consignado / Fiado

| Fórmula | Código |
|---------|--------|
| Conversão mesa → fiado: `remaining_product = max(0, order.total − order.partial_payment)`; `remaining_service = 0` (se não opt-in) ou gorjeta fixa ou `remaining_product × pct/100` | `app/routers/consignments.py` → `convert_order_to_consignment()` |
| `product_total = order.total`; `service_total = partial_service_charge + remaining_service`; `total = product_total + service_total` | idem |
| `amount_paid = partial_payment + partial_service_charge` | idem |
| `balance = max(0, total − amount_paid)` | idem |
| Pagamento do consignado usa **principal primeiro**: `product_portion = min(amount, product_total − Σ product_portion pago)`; `service_portion = amount − product_portion` | `app/routers/consignments.py` → `add_payment()` |
| Após o pagamento: `amount_paid += amount`; `balance = max(0, total − amount_paid)`; `status = "pago"` quando `balance = 0` | idem |
| `_recalculate_totals`: criação direta → `total = Σ (unit_price × quantity)`; conversão → preserva `total`; sempre `balance = max(0, total − amount_paid)` | `app/routers/consignments.py` → `_recalculate_totals()` |

> **Nota de consistência:** a taxa de serviço no fiado é **opt-in** — só entra no `total`
> se o operador marcar. O `ConvertToFiadoRequest` carrega `apply_service_charge` e
> `service_charge_custom`. A gorjeta/taxa paga em pagamentos parciais anteriores é
> registrada nas `ConsignmentPayment` (faturamento e caixa recebem o valor cheio) e
> compõe `amount_paid`, preservando a invariante `amount_paid + balance = total`.
> O valor de produto continua separado em `product_portion`, para que faturamento e
> lucro nunca tratem gorjeta como receita de produto.
>
> **Garçom creditado no fiado:** quando um gerente escolhe um funcionário no
> fechamento, `ConsignmentOrder.credited_waiter_id` e o snapshot
> `credited_waiter_name` preservam essa escolha mesmo que o funcionário não possua
> login. A venda, a taxa reconhecida na quitação e eventuais estornos usam esse mesmo
> funcionário. Sem escolha manual, permanece o usuário que abriu a comanda. O gerente
> que executa a conversão fica registrado em `Order.closed_by_id`, mas não recebe o
> crédito automaticamente.

---

## 6. Caixa

| Fórmula | Código |
|---------|--------|
| `expected_cash = initial_cash + cash_inflows − total_sangria + total_suprimento` | `app/services/cash_service.py` → `compute_session_cash_summary()` |
| `discrepancy = final_cash − expected_cash` (sobra se > 0; falta se < 0) | `app/routers/financial.py` (resumo de fechamento) |
| `cash_inflows` = pagamentos em dinheiro da sessão (finais, parciais e consignados) − estornos em dinheiro registrados na sessão | `app/services/cash_service.py` → `compute_cash_inflows()` |
| Movimento automático `Fechamento de caixa` = `gross_total` (todos os métodos) — **incidência única** do movimento, reutilizada pelo fechamento manual e automático | `app/routers/financial.py` → `finalize_cash_session()` (chamado por `app/routers/cash_register.py` e `app/core/scheduler.py`) |
| Movimento `Taxa de cartão` = soma das taxas de cartão da sessão — mesma incidência única acima | idem |
| Posição de caixa = `Σ entradas − Σ saídas`; cada estorno novo cria uma saída automática no valor bruto devolvido | `app/routers/cash_register.py` e `app/services/refund_service.py` |
| Abrir caixa automático (scheduler): `initial_cash = final_cash` da última sessão fechada | `app/core/scheduler.py` → `auto_open_cash_register()` |
| **Fechamento automático (scheduler):** no minuto configurado (`auto_close_time`, tentativa única), se NÃO houver comandas abertas (`Order.status == "aberta"`, incluindo balcão) fecha de verdade com `final_cash = expected_cash` (discrepância 0 assumida, sem conferência humana); se houver comandas abertas, NÃO fecha — cria notificação com a contagem e envia relatório **parcial**. O fechamento efetivo usa exatamente os mesmos movimentos do fechamento manual (via `finalize_cash_session`) | `app/core/scheduler.py` → `auto_close_cash_register()` / `app/services/notification_service.py` → `create_cash_register_close_notification()` / `create_cash_register_auto_closed_notification()` |
| Relatório automático com caixa aberto: período = `session.opened_at` até o instante da geração, mesmo quando atravessa a meia-noite (parcial no bloqueio por comandas; final após fechar) | `app/core/scheduler.py` → `_send_auto_partial_report()` / `app/routers/financial.py` → `_build_session_report()` / `send_session_close_report_email()` |

---

## 7. Relatórios financeiros (diário / parcial / final)

| Fórmula | Código |
|---------|--------|
| `total_sales = Σ order.total` (pedidos não-fiado fechados no período) + `Σ ConsignmentPayment.product_portion` recebido no período − `Σ PaymentRefund.product_amount` estornado no período | `app/routers/financial.py` → `_build_daily_report()` / `_build_session_report()` |
| `total_cogs = Σ (unit_cost × quantity)` (itens de pedido) | idem |
| `gross_profit = total_sales − total_cogs` | idem |
| `total_card_fees = Σ card_fee_amount` congelado no pagamento; o estorno não devolve esse custo | idem + `app/services/payment_service.py` |
| `operating_expenses = total_card_fees + total_expenses + retained_service_loss` | idem |
| `net_profit = gross_profit − operating_expenses` | idem |
| `gross_total = Σ pagamentos diretos + Σ pagamentos de consignado − Σ estornos`, todos pela data da transação | idem |
| `net_total = gross_total − total_service_charge − total_card_fees − total_expenses` | idem |
| Taxa de cartão: `card_fee_amount = gross_amount × card_fee_rate/100`; taxa e custo ficam congelados no pagamento | `app/services/payment_service.py` → `card_fee_snapshot()` e `OrderPayment`/`ConsignmentPayment` |
| COGS de consignado: **integral na criação** = Σ (`unit_cost` congelado na venda × qty) dos consignados criados no período; um estorno financeiro reverte esse custo na data do estorno | `app/routers/financial.py` → `_consignment_cogs_in_period()` / `_apply_refunds_to_report()` |
| Lucro do dashboard de gestão (`compute_period_profit`) — mesma base + COGS de consignados | `app/routers/financial.py` → `compute_period_profit()` |

> **Consignado — prejuízo na venda, faturamento por pagamento, repasse na quitação:**
> - **COGS (custo)** é reconhecido **integralmente quando o consignado é criado**
>   (venda vira consignado), usando o `unit_cost` **congelado na venda**
>   (`_consignment_cogs_in_period`). Alterar o custo do produto depois não muda
>   o custo do que já foi vendido. Por isso o dia da conversão pode mostrar
>   Lucro Bruto negativo (prejuízo que se recupera conforme o cliente paga).
> - **Faturamento** (`total_sales`) entra **pelos pagamentos recebidos**:
>   `product_amount = amount − service_portion` por pagamento.
> - **Repasse ao garçom** (`total_service_charge` / `by_waiter`) é creditado
>   **apenas quando o consignado fica 100% pago** (`status = "pago"`), na data em
>   que isso acontece (`_consignment_tips_paid_in_period`).
> - Cada `ConsignmentPayment` guarda `service_portion` (gorjeta de parcial
>   convertido) e cada `ConsignmentOrderItem` guarda `unit_cost` (custo congelado).
> - O estorno guarda dois estados da taxa: `service_was_recognized` informa se ela
>   já havia sido reconhecida; `service_already_repassed` informa se o caixa da
>   quitação já havia fechado. Taxa reconhecida e ainda não repassada é revertida;
>   taxa já repassada permanece como `retained_service_loss`; taxa de fiado ainda
>   não reconhecida não é subtraída dos relatórios de repasse.
> - `sale_was_recognized` congela se produto/COGS/rankings já tinham sido
>   reconhecidos. Estorno de pagamento em comanda ainda aberta movimenta o caixa,
>   mas não subtrai receita ou custo que ainda não haviam entrado nos relatórios.

> **Atenção (`net_profit` vs `net_total`):** `net_profit` é sobre **vendas (produto)** e
> desconta taxas/despesas; `net_total` é sobre **`gross_total` (tudo que entrou)** e
> desconta serviço + taxas + despesas. São definições diferentes — não confundir.

**Incidências de pagamentos em relatórios (janela de período):**
`compute_session_close_metrics`, `compute_period_profit`, `_build_daily_report`,
`_build_session_report` e `compute_payment_breakdown`. Todos usam os registros
canônicos `OrderPayment`, `ConsignmentPayment` e `PaymentRefund`, filtrados por
`created_at`.

---

## 8. Vendas (módulo Financeiro → list_sales)

| Fórmula | Código |
|---------|--------|
| `total_sales` = vendas diretas fechadas + parcelas de **produto** dos consignados − produto estornado, pela data de cada evento | `app/routers/financial.py` → `list_sales()` / `_period_totals()` |
| `consignment_paid` = Σ `ConsignmentPayment.product_portion` recebida no período; o bruto pago permanece disponível separadamente nos detalhes | idem |
| Por forma de pagamento / hora = pagamentos canônicos no método/hora da transação − estornos no mesmo método/hora em que ocorreram | `app/services/cash_service.py` → `compute_payment_breakdown()` |

> **Card "Hoje/Semana/Mês" (Financeiro):** `total = Σ order.total (não-fiado) + Σ
> (ConsignmentPayment.amount − service_portion)` — a gorjeta de consignado convertido é
> **repasse** (`total_service_charge`), nunca faturamento de produto. Implementado em
> `app/routers/financial.py` → `_period_totals` (endpoint `/api/financeiro/dashboard`).

---

## 9. Perdas de estoque

| Fórmula | Código |
|---------|--------|
| Valor da perda: `amount = unit_cost_snapshot × quantity`; apenas registros antigos sem snapshot usam o custo atual como fallback | `app/routers/financial.py` → `_get_perdas()` |
| Critério de perda: movimentação `saida` manual sem `order_id` e sem `consignment_order_id` | idem |

---

## 10. Consumo do cliente (módulo Clientes)

| Fórmula | Código |
|---------|--------|
| `total_spent = Σ order.total` (pedidos finalizados não-fiado) + `Σ ConsignmentOrder.product_total` na criação − `Σ PaymentRefundItem.product_amount` | `app/routers/customers.py` → `customer_summary()` |
| Rankings de produto/cliente/garçom reconhecem o consignado na criação e revertem os itens na data do estorno | `app/routers/customers.py`, `app/routers/dashboards.py`, `app/routers/financial.py` |

---

## Checklist para alterar qualquer fórmula (obrigatório)

1. **Localize a fórmula** na lista acima e abra o(s) arquivo(s) citado(s).
2. **Busque todas as incidências** da mesma regra no código (`grep` por nomes de campos
   como `partial_payment`, `service_charge_amount`, `final_total`, `gross_total`,
   `expected_cash`, `unit_cost`, `balance`, `amount_paid`, etc.).
3. **Verifique backend E frontend** — o frontend recalcula valores idênticos e os envia
   ao backend (impressão de nota, fechamento, balcão, consignado).
4. **Confira os pontos de agregação** (relatórios, dashboards, caixa) que consomem o mesmo
   valor.
5. **Mantenha a invariante** sempre que aplicável: `TOTAL − Pago = Restante`,
   `Pago + Saldo = Total` (consignado), `expected_cash` vs `gross_total`.
6. **Rode a verificação** de sintaxe Python/JS dos arquivos alterados e, se possível,
   teste os fluxos afetados antes do deploy.
