# Changelog

Todas as mudanças relevantes deste projeto serão documentadas neste arquivo.

## [1.0.0] - 2026-07-24

### Added

- Comandos `scan`, `apply`, `doctor`, `audit`, `history` e `undo`.
- Configuração TOML validada para diretórios e extensões da biblioteca.
- Reconhecimento de filmes, episódios modernos, séries legadas e legendas.
- Conversão contextual conservadora de numeração absoluta de episódios.
- Associação contextual de legendas quando existe um único vídeo compatível.
- Preview e resumos Rich, com suporte a saída compacta e sem cores.
- Relatórios de auditoria em texto e TSV.
- Histórico JSON das operações realmente movidas.
- Undo com preview, confirmação, validação coletiva e registro de resultado.
- Lock exclusivo para impedir execuções simultâneas de `apply` e `undo`.
- Suíte com 396 testes automatizados.

### Security

- Proteção contra sobrescrita e criação exclusiva do destino.
- Validação de caminhos e rejeição de path traversal.
- Rejeição de arquivos e componentes simbólicos inseguros.
- Movimentação segura entre filesystems com cópia exclusiva e sincronização.
- Rollback por operação quando a movimentação não pode ser concluída.
- Escrita atômica e sincronizada dos registros de histórico.
- Releitura e revalidação definitiva do undo dentro do lock.
- Validação prévia all-or-nothing antes de iniciar o undo.
- Tratamento explícito dos estados `undone`, `partially_undone` e `undo_failed`.
