# Sprints - Sistema Lads Beer

# Sistema de gestão e operação para espetinho / distribuidora

**Status:** Em progresso
**Período:** 09/07/2026 até 06/01/2027
**Gerente do Projeto:** Lucas Dousseau Arantes

## **Objetivo Principal da Sprint**

Desenvolver o sistema de gerenciamento e operação para a Lads Beer e instalar o mesmo no estabelecimento.

**Visão Semanal**

**Sprint 1 (09/07/2026 - 16/07/2026)**
• **Foco da sprint:** Definir a base de produção do sistema e adicionar features. 
• **Tarefas Principais:**

- [x]  Docker
- [x]  Desenvolver o módulo Cliente
    - [x]  CRUD de clientes
    - [x]  Vincular mesas à clientes
    - [x]  Registro do consumo, frequência (com gráfico de dias da semana que mais vem) e faturamento com o cliente
- [X]  Vincular perdas por consumo, quebras, etc… no relatório financeiro
- [X]  Adicionar a tag promocional para um item registrado durante a promoção
- [X]  Adicionar a quantidade de itens em promoção no relatório
- [X]  Permitir configurar abertura e fechamento automático do caixa
- [X]  Construir envio automático do relatório para um email mutável sempre que fechar o caixa
- [X]  Adicionar botão para “mascarar” notas, ou seja, imprimir a nota ocultando itens e/ou adicionando novos itens
- [X]  Não deve alterar os dados, apenas imprimir uma nota mascarada para o cliente
- [X]  Criar função para selecionar a máquininha na hora do pagamento
- [X]  Permitir criar mais de uma comanda para mais de um cliente em uma mesa

**Sprint 2 (16/07/2026 - 23/07/2026) (pretendo viajar do dia 20 ao 27)**
• **Foco da sprint:** Adição de mais features ao projeto. 
• **Tarefas Principais:**

- [X]  Cadastrar todos os itens da Lads no estoque e criar categorização tanto pro estoque quanto pro registro de pedidos
- [X]  Criar engradados no estoque
- [X]  Função de busca dos produtos no estoque e no registro de pedidos
- [X]  Incrementar a lógica de pagamento para permitir dividir contas diferentes, pagar cada parcela com um método diferente, etc…
- [X]  Módulo de Consignados para fazer uma comanda que será paga fiado
    - [X]  Vinculado aos clientes (com busca pelo nome dos clientes)
    - [X]  Acompanhamento de dias pendentes
    - [X]  Classificação por Pendente, Pagos e Todos e ordenação por Dias pendentes, Valor total
    - [X]  Comanda usa as mesmas funções do módulo de mesas e só computa o pagamento quando paga um pedido
- [X]  Módulo Atacado para vendas de engradados ao comércio local (é o módulo de consignados para clientes PJ)
    - [X]  Pedidos vinculado aos clientes (no caso, empresas)
    - [X]  Acompanhamento de dias pendentes
    - [X]  Comanda usa as mesmas funções do módulo de mesas e permite pagamento fiado, onde computa o pagamento apenas quando o pedido é pago
    - [X]  Classificação por Pendente, Pagos e Todos e ordenação por Dias pendentes, Valor total
- [X]  Adicionar botão para “fiado” em uma comanda de Mesa
    - [X]  Exige vinculo com cliente
    - [X]  Cria comanda em consignados para clientes
- [X]  Criar função para imprimir comanda no caixa (para levar para o cliente)
- [X]  Ajustar o balcão como o do Kaw White

**Sprint 3 (23/07/2026 - 30/07/2026)**
• **Foco da sprint:** Dashboards, painel administrativo, UI e testes com a equipe.
• **Tarefas Principais:**

- [X]  Módulo de Dashboard
- [X]  CRUD’s adiministrativos para tudo em um painel adiministrativo básico
- [X]  Modificar IU para ser igual a da Kaw White no PC e manter +- a IU atual no Cell (mas branco)
- [ ]  Testes e reuniões com o Prodev para apresentar a solução

**Sprint 4 (30/08/2026 - 06/08/2026)**
• **Foco da sprint:** implementar e acompanhar em produção.
• **Tarefas Principais:**

- [ ]  Apresentação de validação na Segunda (02/08/2026)
- [ ]  Melhorias
- [ ]  Implementação
- [ ]  Acompanhamento

**Sprint 5 (06/07/2026 - 06/01/2027)**
• **Foco da sprint:** Abraço.
• **Tarefas Principais:**

- [ ]  Ajustes, acompanhamento e CS