# Media Organizer

Organizador local de filmes, séries e legendas com planejamento, auditoria,
execução segura, histórico e undo.

**Versão atual: 1.0.0**

O Media Organizer trabalha localmente com bibliotecas Plex no Linux. Ele não usa
rede, APIs, bancos de dados ou serviços externos.

## Status do projeto

A versão 1.0.0 é a primeira versão estável do núcleo funcional, validada por
testes automatizados e por uma biblioteca real controlada. Faça backup antes de
usar o programa em um acervo insubstituível.

Consulte [CHANGELOG.md](CHANGELOG.md) para as mudanças da versão.

## Recursos principais

- `scan` somente leitura e `apply` com confirmação explícita;
- organização de filmes, séries modernas e legadas e legendas;
- associação contextual conservadora de legendas;
- classificação de arquivos como `UNKNOWN` e detecção de conflitos;
- diagnóstico com `doctor` e relatórios `audit` em texto ou TSV;
- histórico persistente, `undo` seguro e lock de execução;
- preview, progresso e resumos no terminal com Rich.

## Início rápido

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e .
cp config.example.toml config.toml

.venv/bin/python -m media_organizer --config config.toml doctor
.venv/bin/python -m media_organizer --config config.toml scan
.venv/bin/python -m media_organizer --config config.toml audit
.venv/bin/python -m media_organizer --config config.toml apply
.venv/bin/python -m media_organizer --config config.toml history
.venv/bin/python -m media_organizer --config config.toml undo
```

Depois da instalação, o entry point `media-organizer` oferece os mesmos
comandos.

## Fluxo seguro recomendado

1. Mantenha um backup independente.
2. Verifique configuração e filesystem com `doctor`.
3. Examine o plano somente leitura com `scan`.
4. Gere uma evidência de revisão com `audit`.
5. Revise todos os itens `UNKNOWN` e conflitos.
6. Execute `apply` e confirme as operações.
7. Consulte o registro com `history`.
8. Use `undo` se precisar restaurar a execução.

O histórico auxilia a recuperação operacional, mas não substitui backup.

## Requisitos e instalação

- Python 3.12 ou superior
- Linux (uso principal validado; os exemplos funcionam no Linux Mint)

```bash
git clone <url-do-repositorio> media-organizer
cd media-organizer
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[dev]'
```

O pacote instala o comando `media-organizer`. Também é possível executar
`python -m media_organizer`.

## Interface Rich

A CLI usa Rich para oferecer saída colorida quando o terminal suporta, tabelas
de operações e diagnóstico, resumos visuais, progresso e métricas de tempo e
velocidade. A apresentação também funciona sem cores e quando a saída é
redirecionada:

```bash
media-organizer --config config.toml scan
media-organizer --config config.toml apply
media-organizer --config config.toml apply --yes
media-organizer --config config.toml audit
media-organizer --config config.toml --quiet scan
NO_COLOR=1 media-organizer --config config.toml scan
```

Durante scan e audit, o progresso é indeterminado porque o total ainda não é
conhecido. No apply, a barra usa o número real de operações planejadas.
`--quiet` remove banners, tabelas e animações, mantendo um resumo compacto e
estável. `--verbose` mantém logs INFO separados no stderr. A variável
`NO_COLOR` desativa cores sem remover informação.

Essa camada melhora apenas a apresentação; as regras de validação, conflitos e
movimentação segura permanecem as mesmas.

## Configuração

Copie o exemplo e ajuste somente caminhos pertencentes à biblioteca:

```bash
cp config.example.toml config.toml
```

```toml
media_root = "/mnt/media"
incoming_dir = "incoming"
movies_dir = "movies"
series_dir = "series"

video_extensions = [".mkv", ".mp4", ".avi", ".mov", ".m4v", ".divx"]
subtitle_extensions = [".srt", ".ass", ".ssa", ".vtt", ".sub"]

preserve_technical_tags_for_movies = true
preserve_technical_tags_for_series = false
```

Os diretórios configurados devem ser relativos a `media_root`; caminhos
absolutos e componentes `..` são rejeitados.

## Comandos

O comando seguro e padrão para inspeção é:

```bash
media-organizer --config config.toml scan
```

Ele não cria diretórios, move, renomeia ou remove arquivos.

A varredura percorre `incoming` recursivamente e considera somente as extensões
de vídeo e legenda configuradas. Arquivos e diretórios ocultos, além de links
simbólicos, são ignorados. Itens auxiliares como JPG, NFO, TXT e ZIP permanecem
intactos e não entram no pipeline.

Séries legadas também podem usar uma pasta de série seguida por `Temporada 1`,
`Season 01` ou `S01`, com arquivos numerados no início. Sequências locais
começando em 1 são mantidas. Numeração absoluta só é convertida quando todos os
vídeos numerados da temporada formam uma sequência contínua, sem duplicidades,
com pelo menos dois arquivos; sequências ambíguas permanecem `UNKNOWN`.

Legendas com nomes explícitos continuam tendo prioridade. Legendas genéricas em
pastas `Subs`, `Subtitles`, `Legendas` e equivalentes podem ser associadas pelo
contexto somente quando o contêiner de mídia possui exatamente um vídeo
reconhecido. Idiomas presentes em subpastas e flags como `forced`, `sdh` e `cc`
também são preservados; `german`, `ger`, `deu` e `de` são normalizados para
`de`. Contêineres com zero ou vários vídeos permanecem `UNKNOWN`. Revise sempre
o resultado com `scan` e `audit` antes de executar `apply`.

Para aplicar apenas as operações sem conflito:

```bash
media-organizer --config config.toml apply
media-organizer --config config.toml apply --yes
```

Sem `--yes`, é exigida confirmação interativa. Para diagnosticar diretórios,
permissões, espaço, filesystem e links suspeitos:

```bash
media-organizer --config config.toml doctor
```

Use `--verbose` antes do subcomando para logs adicionais.

## Uso real

Comece sempre com uma biblioteca de teste e revise o plano antes de mover
arquivos:

```bash
cp config.example.toml config.toml
media-organizer --config config.toml doctor
media-organizer --config config.toml scan
media-organizer --config config.toml apply
media-organizer --config config.toml apply --yes
media-organizer --config config.toml --quiet scan
media-organizer --config config.toml --verbose scan
```

`scan` apenas analisa e mostra o plano; `apply` realiza os movimentos seguros.
Use `--yes` para pular a confirmação interativa e `--quiet` para ocultar as
operações individuais. `--verbose` controla o detalhamento dos logs no stderr,
enquanto `--quiet` reduz somente a saída normal no stdout.

### Teste manual controlado

O exemplo abaixo cria uma biblioteca descartável em `/tmp` e executa somente
diagnóstico e scan:

```bash
rm -rf /tmp/media-organizer-demo
mkdir -p /tmp/media-organizer-demo/incoming

touch "/tmp/media-organizer-demo/incoming/Interstellar.2014.1080p.mkv"
touch "/tmp/media-organizer-demo/incoming/Show.S01E01.mkv"
touch "/tmp/media-organizer-demo/incoming/Show.S01E01.pt-BR.srt"

cat > /tmp/media-organizer-demo/config.toml <<'EOF'
media_root = "/tmp/media-organizer-demo"
incoming_dir = "incoming"
movies_dir = "movies"
series_dir = "series"
EOF

media-organizer --config /tmp/media-organizer-demo/config.toml doctor
media-organizer --config /tmp/media-organizer-demo/config.toml scan
```

Depois de revisar o plano, o apply pode ser executado separadamente:

```bash
media-organizer --config /tmp/media-organizer-demo/config.toml apply
```

## Audit de biblioteca

O audit executa scanner e planner, mas nunca move arquivos. Ele gera uma
evidência persistente para revisar itens `UNKNOWN`, conflitos e destinos antes
do primeiro apply real:

```bash
media-organizer --config config.toml audit
media-organizer --config config.toml audit --output audit-report.txt
media-organizer --config config.toml audit --format tsv --output audit-report.tsv
```

O formato text é voltado à leitura humana; TSV facilita filtros e planilhas.
Relatórios existentes não são sobrescritos. Arquivos JPG, NFO, TXT, ZIP e outras
extensões não configuradas são ignorados, enquanto `UNKNOWN` e `CONFLICT` devem
ser revisados. Guarde o relatório como evidência dessa revisão.

### Validação real controlada

Este fluxo cria arquivos vazios em uma biblioteca descartável e não executa
apply:

```bash
rm -rf /tmp/media-organizer-real-test
mkdir -p /tmp/media-organizer-real-test/incoming

touch "/tmp/media-organizer-real-test/incoming/Interstellar.2014.1080p.mkv"
touch "/tmp/media-organizer-real-test/incoming/Show.S01E01.mkv"
touch "/tmp/media-organizer-real-test/incoming/Show.S01E01.pt-BR.srt"
touch "/tmp/media-organizer-real-test/incoming/video-final-novo.mkv"
touch "/tmp/media-organizer-real-test/incoming/poster.jpg"

cat > /tmp/media-organizer-real-test/config.toml <<'EOF'
media_root = "/tmp/media-organizer-real-test"
incoming_dir = "incoming"
movies_dir = "movies"
series_dir = "series"
EOF

media-organizer --config /tmp/media-organizer-real-test/config.toml doctor
media-organizer --config /tmp/media-organizer-real-test/config.toml audit --output /tmp/media-organizer-real-test-audit.txt
cat /tmp/media-organizer-real-test-audit.txt
```

## Histórico e undo

Cada `apply` que mover pelo menos um arquivo grava um JSON UTF-8 em
`media_root/.media-organizer/history`. O registro contém somente operações
realmente movidas, com caminhos relativos, tipo de mídia, tamanho e timestamp
quando disponíveis.

```bash
media-organizer --config config.toml apply
media-organizer --config config.toml history
media-organizer --config config.toml history --limit 5
media-organizer --config config.toml undo
media-organizer --config config.toml undo --id EXECUTION_ID
media-organizer --config config.toml undo --yes
```

O `undo` mostra um preview e valida todas as operações antes de mover qualquer
arquivo: o destino atual precisa existir, a origem original deve estar livre e
todos os caminhos devem permanecer dentro da biblioteca, sem links simbólicos
intermediários. Nada é sobrescrito. Uma falha depois de parte do undo é
registrada como `partially_undone` e exige revisão manual. Execuções completas
usam `undone`; falhas antes da primeira restauração usam `undo_failed`.

Um lock exclusivo em `.media-organizer/lock` impede `apply` e `undo`
simultâneos. O histórico facilita recuperação operacional, mas não substitui
backup. Use `scan` e `audit` antes do primeiro `apply` real.

## Nomenclatura

Filmes são organizados como:

```text
movies/Interstellar (2014)/Interstellar (2014) [2160p HDR BluRay REMUX].mkv
```

O ano é obrigatório. Tags técnicas conhecidas são preservadas quando habilitado,
mas grupos de release, hashes, URLs e ruído não são propagados.

Episódios `S01E01`, `s01e01`, `1x01` e `S01E01E02` são aceitos:

```text
series/Show Name/Season 01/Show Name S01E01.mkv
series/Show Name/Season 01/Show Name S01E01-E02.mkv
```

Tags técnicas não entram no nome final dos episódios. Legendas compatíveis são
colocadas ao lado do vídeo. Português, português brasileiro, `pt` e `pt-BR`
viram `pt-BR`; inglês, `eng` e `en` viram `en`. Um idioma desconhecido não é
inventado.

## Segurança

- `scan` é somente leitura.
- A origem e o destino são validados dentro da raiz configurada.
- Links simbólicos de arquivo não são seguidos; links que escapam da raiz são
  reportados pelo `doctor`.
- Destinos existentes e destinos duplicados são conflitos e nunca são
  sobrescritos.
- O estado é revalidado imediatamente antes de cada movimento.
- No mesmo filesystem, o destino é criado por hard link exclusivo antes da
  remoção da origem. Entre filesystems, a cópia usa criação exclusiva,
  sincronização e só então remove a origem.
- Não há exclusão, substituição nem deduplicação destrutiva.
- Uma falha é registrada e as operações independentes podem continuar.

Mantenha backups: embora conservador, `apply` realiza movimentos reais.

## Limitações conhecidas

- Não consulta serviços externos de metadata.
- Não possui watch mode nem roda como daemon ou serviço.
- Não associa legendas genéricas quando existem vários vídeos candidatos.
- Heurísticas ambíguas permanecem `UNKNOWN`.
- O undo não promete rollback global se uma falha operacional ocorrer depois de
  restaurações parciais; o estado fica registrado para revisão.
- O histórico não substitui backup.
- O suporte principal foi validado em Linux.

## Roadmap

Itens planejados, ainda sem versão definida:

- watch mode;
- integração opcional com metadata;
- execução como serviço;
- assistente de configuração;
- distribuição e empacotamento;
- interface web em etapa posterior.

## Testes

```bash
make check
```

O projeto possui **396 testes automatizados**. `make check` executa lint,
verificação de formatação e testes. A suíte usa diretórios temporários e não
pressupõe a existência de `/mnt/media`.

## Desenvolvimento

Os comandos usuais de desenvolvimento são padronizados pelo `Makefile`:

```bash
make install
make lint
make format
make format-check
make test
make check
make clean
```

`make install` instala o projeto e suas dependências de desenvolvimento no
`.venv`. `make check` executa lint, verificação de formatação e testes. `make
clean` remove somente caches Python e artefatos locais de build, sem remover o
ambiente virtual ou a configuração local.

Diretórios `__pycache__`, `.pytest_cache` e `*.egg-info` podem existir
localmente durante o desenvolvimento, mas são ignorados pelo Git.
