# Backup e restauração

O botão **Baixar backup completo** gera um dump PostgreSQL em formato customizado.
Ele contém o esquema e todos os registros, inclusive pagamentos normalizados,
estornos, sessões e movimentos de caixa, consignados, custos congelados e histórico
de estoque. A antiga exportação CSV permanece disponível na API apenas como
exportação auxiliar e não deve ser usada para recuperação de desastre.

## Restaurar

1. Coloque o sistema em janela de manutenção e pare o container da aplicação. O
   PostgreSQL deve permanecer em execução.
2. Confirme que `DATABASE_URL` aponta para o banco que será substituído.
3. Execute:

   ```bash
   python scripts/restore_database.py caminho/backup_ladsbeer_completo.dump \
     --confirm-database ladsbeer
   ```

4. Inicie novamente a aplicação. As migrações idempotentes serão verificadas na
   inicialização.

O nome passado em `--confirm-database` precisa ser exatamente o banco configurado
em `DATABASE_URL`. A restauração valida o arquivo antes de substituir os objetos e
é feita em uma única transação; em caso de erro, o banco anterior é preservado.

Nunca restaure com a aplicação atendendo usuários. Consignados pendentes podem
permanecer no backup normalmente.
