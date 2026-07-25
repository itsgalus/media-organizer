# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-07-24

### Added

- `scan`, `apply`, `doctor`, `audit`, `history`, and `undo` commands.
- Validated TOML configuration for library directories and extensions.
- Recognition of movies, modern episodes, legacy series, and subtitles.
- Conservative contextual conversion of absolute episode numbering.
- Contextual subtitle association when exactly one compatible video exists.
- Rich previews and summaries, including compact and no-color output.
- Text and TSV audit reports.
- JSON history containing operations that were actually moved.
- Undo with preview, confirmation, collective validation, and result recording.
- Exclusive lock preventing simultaneous `apply` and `undo` executions.
- 428 automated tests.

### Security

- Overwrite protection and exclusive target creation.
- Path validation and path traversal rejection.
- Rejection of unsafe symbolic files and path components.
- Safe cross-filesystem movement with exclusive copying and synchronization.
- Per-operation rollback when a move cannot be completed.
- Atomic, synchronized history record writes.
- Definitive undo record reload and revalidation while holding the lock.
- All-or-nothing validation before undo begins.
- Explicit handling of `undone`, `partially_undone`, and `undo_failed` states.
