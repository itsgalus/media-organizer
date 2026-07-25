# Media Organizer

A safe local media organizer for movies, TV series, and subtitles with planning, auditing, execution history, and undo support.

**Current version:** 1.0.0

Media Organizer works entirely locally with Plex libraries on Linux. It does not require network access, APIs, databases, or external services.

## Project status

Version **1.0.0** is the first stable release of the core engine.

The project has been validated through **396 automated tests** and controlled real-world library runs.

Always keep an independent backup before organizing valuable or irreplaceable media collections.

See [CHANGELOG.md](CHANGELOG.md) for detailed release history.

## Main features

- Read-only planning with `scan`
- Explicit execution with `apply`
- Movie recognition
- Modern TV episode recognition
- Legacy TV episode recognition
- Conservative contextual subtitle association
- `UNKNOWN` classification
- Conflict detection
- Filesystem diagnostics with `doctor`
- Audit reports in text and TSV formats
- Persistent execution history
- Safe undo
- Exclusive execution lock
- Rich terminal previews, progress, and summaries
- Safe same-filesystem and cross-filesystem moves

## Quick start

Clone the repository:

```bash
git clone git@github.com:itsgalus/media-organizer.git
cd media-organizer
```

Create a virtual environment:

```bash
python3 -m venv .venv
```

Install the project:

```bash
.venv/bin/python -m pip install -e .
```

Create the configuration file:

```bash
cp config.example.toml config.toml
```

Edit `config.toml` and set your media root and directory names.

Run diagnostics:

```bash
.venv/bin/python -m media_organizer --config config.toml doctor
```

Preview planned operations:

```bash
.venv/bin/python -m media_organizer --config config.toml scan
```

Generate an audit report:

```bash
.venv/bin/python -m media_organizer --config config.toml audit
```

Apply the approved plan:

```bash
.venv/bin/python -m media_organizer --config config.toml apply
```

Inspect execution history:

```bash
.venv/bin/python -m media_organizer --config config.toml history
```

Undo the latest eligible execution:

```bash
.venv/bin/python -m media_organizer --config config.toml undo
```

After installation, the `media-organizer` entry point provides the same commands.

## Commands

| Command | Description |
|---|---|
| `doctor` | Validate configuration and filesystem conditions |
| `scan` | Preview organization without modifying files |
| `apply` | Execute safe planned operations |
| `audit` | Generate reviewable audit reports |
| `history` | List recorded executions |
| `undo` | Revert the latest eligible execution |

## Recommended safe workflow

1. Keep an independent backup.
2. Run `doctor`.
3. Run `scan`.
4. Generate an `audit` report.
5. Review all `UNKNOWN` items and conflicts.
6. Run `apply`.
7. Inspect the result with `history`.
8. Use `undo` if restoration is required.

Execution history supports operational recovery, but it does not replace a backup.

## Safety model

Media Organizer is intentionally conservative.

- Destination files are never overwritten.
- Paths are validated before movement.
- Path traversal is rejected.
- Unsafe symbolic links are rejected.
- Destination creation is exclusive.
- Cross-filesystem moves use safe copying and synchronization.
- Failed operations are rolled back individually when possible.
- History records are written atomically.
- `apply` and `undo` use an exclusive lock.
- Undo is revalidated inside the lock immediately before execution.
- Ambiguous files remain `UNKNOWN` instead of being guessed.

## Configuration

The configuration file is TOML.

Example:

```toml
media_root = "/path/to/media"

incoming_dir = "incoming"
movies_dir = "movies"
series_dir = "series"
```

Configured directories must:

- be relative paths;
- not be empty;
- not contain `..`;
- not point to the media root itself;
- not overlap or be nested inside each other.

See `config.example.toml` for the complete example.

## Supported media

### Movies

Movies are recognized conservatively from filenames containing a title and year.

Example:

```text
Interstellar.2014.2160p.HDR.BluRay.REMUX.mkv
```

Planned destination:

```text
movies/Interstellar (2014)/Interstellar (2014).mkv
```

Technical tags may be recognized for planning and presentation, including resolution, HDR, codec, source, audio, and edition markers.

### TV series

Modern episode patterns include:

```text
Show.S01E01.mkv
Show.S01E01E02.mkv
Show.1x04.mkv
```

Legacy directory-based patterns are also supported when the season context is explicit:

```text
Show/Season 01/01 Episode Title.mkv
Show/Temporada 3/57 Episode Title.avi
```

Absolute legacy numbering is only rebased when the sequence is complete and unambiguous.

### Subtitles

Supported subtitle extensions include:

```text
.srt
.ass
.ssa
.vtt
.sub
```

Recognized language aliases currently include:

- Brazilian Portuguese: `pt-BR`
- English: `en`
- German: `de`

Recognized flags include:

- `forced`
- `sdh`
- `cc`

Generic subtitles inside folders such as `Subs`, `Subtitles`, or `Legendas` can be associated contextually when exactly one compatible video exists.

Ambiguous contextual subtitles remain `UNKNOWN`.

## Audit reports

The `audit` command creates a reviewable report without modifying media files.

Text report:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  audit
```

TSV report:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  audit \
  --format tsv \
  --output media-audit.tsv
```

Reports include:

- operation type;
- status;
- source;
- target;
- conflict reason;
- error details;
- recognition counters.

## History and undo

Successful `apply` executions are stored in:

```text
.media-organizer/history/
```

List recent executions:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  history
```

Limit the result:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  history \
  --limit 5
```

Undo the latest eligible execution:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  undo
```

Undo a specific execution:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  undo \
  --id EXECUTION_ID
```

Skip confirmation:

```bash
.venv/bin/python -m media_organizer \
  --config config.toml \
  undo \
  --yes
```

Undo performs all collective safety validation before the first restore.

If an operational failure occurs after some files have already been restored, the history records one of these states:

```text
undone
partially_undone
undo_failed
```

Manual review may be required after a partial undo.

## Known limitations

- No external metadata services are queried.
- No watch mode is available yet.
- The application does not currently run as a daemon or system service.
- Generic subtitles are not associated automatically when multiple video candidates exist.
- Ambiguous heuristics remain `UNKNOWN`.
- Undo does not promise global rollback after partial restoration.
- Execution history does not replace backup.
- Primary validation has been performed on Linux.

## Roadmap

Planned future work:

- watch mode;
- optional metadata integration;
- service execution;
- configuration assistant;
- packaging and distribution;
- web interface at a later stage.

## Tests

Run the full quality suite:

```bash
make check
```

It executes:

- Ruff lint checks;
- Ruff format verification;
- Pytest.

The project currently has **396 automated tests**.

Tests use temporary directories and do not depend on a real media library.

## License

MIT License.

