# Container-Image: aw-sandbox:dev

Spezifikation des Sandbox-Image fuer Stufe-2-Agent-Knoten.

**Status: verifiziert 2026-06-27** (Smoke-Lauf 1/1 auf Hetzner capstone2 erfolgreich,
Claude CLI Version 2.1.191, gepinnt).

## Was das Image enthaelt

| Komponente | Wert | Begruendung |
|---|---|---|
| Base | `node:20-slim` | Node LTS, minimal (kein Build-Tools-Overhead) |
| System-Tools | `git`, `bash` | git fuer Worktree-Operationen; bash fuer `bash -lc` |
| Claude-Code-CLI | `@anthropic-ai/claude-code` | Agent-CLI; laeuft headless mit `-p` |
| Lokales LLM | -- | Nicht enthalten; Inferenz API-seitig (Anthropic) |
| GPU | -- | Hetzner-Box hat keine GPU; irrelevant |
| API-Key | -- | NICHT ins Image; immer Laufzeit-Injektion |

## Lokaler Build (Referenz-Version: 2.1.191)

```bash
# Empfohlen: Version pinnen (Referenz-Build war mit 2.1.191)
docker build --build-arg CLAUDE_CLI_VERSION=2.1.191 -t aw-sandbox:dev .

# Alternativ: @latest (beim naechsten Build aktuellste Version)
docker build -t aw-sandbox:dev .
```

Nach dem ersten erfolgreichen Build: Version aus `claude --version` ablesen
und als `CLAUDE_CLI_VERSION`-Wert im Build-Kommando pinnen (Reproduzierbarkeit).

## Smoke-Test nach dem Build

```bash
docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY aw-sandbox:dev claude --version
```

Erwartete Ausgabe: Versionsnummer, z.B. `2.1.191`.

## Laufzeit-Nutzung (run_in_sandbox)

```bash
docker run --rm \
  --memory 1.5g \
  --network bridge \
  -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY \
  -v /path/to/worktree:/work \
  -w /work \
  aw-sandbox:dev \
  bash -lc "claude -p 'prompt' --model sonnet --permission-mode bypassPermissions"
```

`run_in_sandbox()` baut dieses Kommando deterministisch aus den uebergebenen
Parametern. Die `-e ANTHROPIC_API_KEY`-Uebergabe erfolgt via
`env_passthrough=["ANTHROPIC_API_KEY"]` -- Docker liest den Wert aus der
Umgebung des Aufrufers. Der Key erscheint so nie in der Kommandozeile / Prozessliste.

## Non-Root-Betrieb (Pflicht)

Das Image laeuft als `USER node` (uid 1000). Die Claude CLI verweigert
`--permission-mode bypassPermissions` unter root.

**Voraussetzung:** der Host-User muss uid 1000 haben (pruefbar mit `id -u`),
damit der gemountete Worktree (`-v /path:/work`) vom Container beschreibbar ist.

## Key-Handling (Sicherheit)

- API-Key **niemals** ins Image backen (kein `ENV ANTHROPIC_API_KEY` im Dockerfile).
- Immer `-e ANTHROPIC_API_KEY` zur Laufzeit uebergeben.
- Auf Hetzner: Key in `~/.bashrc` oder via `export` in der SSH-Session setzen,
  dann per `-e ANTHROPIC_API_KEY` an den Container durchreichen.

## Bekannte CLI-Flags (verifiziert mit Version 2.1.191)

| Flag | Beschreibung |
|---|---|
| `-p <prompt>` / `--print` | Headless-Modus, Prompt als Argument |
| `--model <alias>` | Modell-Routing: `opus`, `sonnet` |
| `--permission-mode bypassPermissions` | Keine interaktiven Prompts (Pflicht fuer headless) |
| `--max-budget-usd <n>` | Kosten-Guard pro Knoten (optional, nur mit `--print`) |

## Status nach erstem Build (2026-06-27)

- [x] `CLAUDE_CLI_VERSION=2.1.191` im Build-Kommando gepinnt.
- [x] Smoke-Test auf Hetzner capstone2 erfolgreich (1/1).
- [x] Image laeuft non-root (USER node, uid 1000).
- [ ] Image-Groesse pruefen (`docker image inspect aw-sandbox:dev --format '{{.Size}}'`).
