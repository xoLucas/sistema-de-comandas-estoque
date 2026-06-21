Sistema local para gestão de comandas, estoque e financeiro da Lads Beer.

1. Objetivo
Desenvolver um sistema local multiplataforma com funcionamento em rede local (offline-first em relação à internet) para a Lads Beer, focado em otimizar o atendimento no modelo de espetinhos. A solução visa substituir as comandas manuais e controles isolados por planilhas, mitigando erros de somatória, garantindo que os pedidos cheguem corretamente à cozinha e centralizando a gestão operacional com rastreabilidade de dados financeiros e de estoque.
2. Escopo do Projeto
2.1. Módulo de Autenticação
Login obrigatório para todos os usuários do sistema.
Gestão de perfis e alteração de cargos: Garçom, Caixa, Estoquista e Gerente.
Nível de acesso de "Gerente" protegido por exigência de senha.
Usuário default configurado como Garçom "Sem nome", com exibição de pop-up obrigatório para registro nominal quando abrir o app (se ainda não tiver registrado).
2.2. Módulo de Atendimento (Garçom e Caixa)
Visualização geral através de um Mapa de Mesas com numerações (incluindo uma mesa chamada balcão) para registro de vendas.
Sinalização visual de status em tempo real: Mesa Vazia/Não atendida em cinza, Mesa atendida em amarelo e Mesa finalizada em verde.
Interface da mesa (aparece quando clicamos em uma mesa) contendo:
Exibição de conta parcial (valor atual dos itens da comanda).
Registro de pagamento parcial (se for feito um pagamento antes de fechar a mesa, fica registrado e esse valor pago é deduzido da conta final).
Botão de “adicionar item” que permite o garçom acessar a lista de itens (com o número em tempo real de itens no estoque) e registrar o pedido do cliente apenas clicando em um botão de "mais / menos" do lado de cada item da lista.
Botões de adição/remoção ("mais / menos") de itens diretamente na comanda, integrados ao estoque.
Checklist com as bebidas que o garçom deve preencher manualmente quando entrega ao cliente;
Visualização da quantidade disponível em estoque de cada item durante o pedido.
Opção de finalizar conta (com sugestão de acréscimo de 10%) e integrar o pagamento ao relatório financeiro.
2.3. Módulo de Estoque (Caixa, Garçom, Estoquista e Gerente)
Lista principal com todos os itens do estoque divididos por categorias (carnes, condimentos, bebidas, etc.).
Filtros e ordenação por ordem alfabética, quantidade absoluta e porcentagem em relação à quantidade mínima ideal.
Painel de status de risco:
"Em risco" (quantidade real <= quantidade mínima estipulada).
"Em conformidade".
“Em falta” (quantidade <= 2)
Funcionalidade de "Adicionar Carregamento" para entrada rápida de lotes com múltiplos itens.
2.4. Módulo Financeiro (Caixa e Gerente)
Histórico detalhado das vendas diárias contendo: registro da mesa, garçom responsável, valor gasto, repasse de 10% e comissão.
Opção de finalização diária com geração automática de relatório do dia.
Dashboard interativo consolidando dados mensais, semanais e anuais de entradas e saídas do caixa.
2.5. Módulo de Produção (Cozinha/Churrasqueira)
Roteamento inteligente de itens que exigem preparo diretamente para a cozinha.
Impressão automática de tickets de produção em impressora térmica.
Layout do ticket contendo: Número da Mesa, Nome do Cliente (opcional), Quantidade, Nome do Produto, Hora do pedido e Nome do Garçom.
Produtos de prateleira ou geladeira (ex: refrigerantes) são isolados e não geram impressão.


3. Arquitetura Recomendada
3.1. Arquitetura Principal (On-Premise / Rede Local) A aplicação não dependerá de hospedagem em nuvem, operando 100% dentro da infraestrutura física da distribuidora.
Servidor Local (Computador do Caixa): Todo o sistema será hospedado na máquina física estrategicamente alocada no terminal do caixa. O posicionamento fixo desta máquina otimiza a logística de cabos de rede e conectividade com as impressoras térmicas, sem comprometer o fluxo de passagem de clientes e atendentes.
Frontend Mobile/Web: Interfaces em HTML/CSS e JavaScript responsivo. Os celulares dos garçons acessam o sistema conectando-se ao Wi-Fi interno e apontando o navegador para o IP do servidor local.
Backend (Python + FastAPI): Irá gerenciar as regras de negócio, os cálculos de comanda e disparar os comandos via biblioteca python-escpos direto para a impressora térmica física ligada à rede.
Banco de Dados (PostgreSQL): Rodando localmente para armazenamento de estoque, histórico financeiro, transações e usuários de forma segura e rápida.
4. Stack Proposta
Frontend: HTML5, CSS3, JavaScript.
Backend: Python, FastAPI, biblioteca python-escpos (para impressão térmica).
Banco de dados: PostgreSQL.
Empacotamento: Docker (para conteinerizar o banco de dados e o backend, garantindo que o sistema rode de forma estável no Windows ou Linux da Lads Beer).
5. Como a operação local funcionará
Início de expediente: O roteador e o computador do caixa são ligados. O sistema (Docker) inicia automaticamente.
Durante o turno: Os garçons operam pelo celular na rede Wi-Fi local. Como não há dependência de servidores externos, a requisição entre apertar o botão no celular, descontar do estoque no caixa e imprimir o papel na churrasqueira ocorre em milissegundos.
Fim do expediente: O gerente finaliza o caixa do dia e o sistema dispara um script Python automatizado que realiza o backup do banco de dados (dump do PostgreSQL) e o envia para a nuvem (ex: Google Drive), garantindo a segurança dos dados contra falhas de hardware.

6. Regras de negócio principais
Ambiente Isolado: O sistema exige que o celular do dispositivo de atendimento esteja exclusivamente na rede Wi-Fi da operação.
Conflito de Pedidos: A centralização no servidor local impede concorrência de estoque e garante que o item seja debitado sequencialmente.
Redundância: Nenhuma informação crítica de estoque ou fechamento fica salva no navegador do celular do garçom; tudo vai instantaneamente para a máquina do caixa.
7. Entregáveis
Software web responsivo operando por IP local.
Backend em FastAPI embarcado em contêiner Docker.
Integração direta e formatação de tickets para a impressora térmica não-fiscal.
Banco de dados PostgreSQL configurado na máquina matriz.
Rotina automatizada de backup em nuvem do banco de dados ao final do dia.
Instalação do sistema.
8. Premissas
A Lads Beer providenciará um Roteador Wi-Fi dedicado exclusivamente à operação do sistema (separado do Wi-Fi de clientes) para evitar congestionamento de rede e lentidão.
A Lads Beer terá um computador (notebook ou desktop) funcional que operará como Servidor/Caixa durante todo o expediente.
A impressora térmica de comandas possuirá conexão compatível (USB direto no servidor, ou cabo de Rede/Ethernet conectada ao roteador).
9. Benefícios Esperados
Imunidade a quedas de internet: O bar nunca para de vender se o provedor de internet falhar.
Tempo de resposta instantâneo (latência mínima).
Redução de custos recorrentes (sem mensalidades de servidores na nuvem).
Operação silenciosa, organizada e rastreável na cozinha.
Redução dos erros por processos manuais com a automatização proposta pelo sistema.
Gestão alinhada a dados.
10. Custos Estimados
Infraestrutura em Nuvem: US$ 0,00 (Zero mensalidades de hospedagem e banco de dados).
Custos Fixos de Hardware (Cliente): Apenas os equipamentos físicos (Computador do caixa, Roteador dedicado de boa qualidade e Impressora térmica).
