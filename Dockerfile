# aw-sandbox:dev -- schlankes Claude-Code-CLI-Image fuer Stufe-2-Agent-Knoten
#
# Kein GPU, kein lokales LLM. Inferenz laeuft API-seitig (Anthropic).
# API-Key NICHT ins Image backen -- zur Laufzeit via -e ANTHROPIC_API_KEY.
#
# Build:
#   docker build -t aw-sandbox:dev .
# Build mit gepinnter CLI-Version (empfohlen ab erstem erfolgreichen Build):
#   docker build --build-arg CLAUDE_CLI_VERSION=2.1.191 -t aw-sandbox:dev .
#
# Smoke-Test:
#   docker run --rm -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY aw-sandbox:dev claude --version

ARG CLAUDE_CLI_PACKAGE=@anthropic-ai/claude-code
ARG CLAUDE_CLI_VERSION=latest

FROM node:20-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends git bash \
    && rm -rf /var/lib/apt/lists/*

# CLI-Paket + Version als ARG, damit der Build reproduzierbar gepinnt werden kann.
ARG CLAUDE_CLI_PACKAGE
ARG CLAUDE_CLI_VERSION
RUN npm install -g ${CLAUDE_CLI_PACKAGE}@${CLAUDE_CLI_VERSION}

WORKDIR /work

# Claude CLI verweigert bypassPermissions als root -> Container non-root betreiben.
# node-User (uid 1000) matcht typische Host-uid, damit der gemountete worktree (/work) schreibbar bleibt.
USER node
