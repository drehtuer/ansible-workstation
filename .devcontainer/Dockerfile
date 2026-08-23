# Authoring and test environment only.
#
# A container cannot provision the WSL host it runs in.  This image exists for
# the tooling that is NOT pip-installable -- asciidoctor (Ruby), Node.js for
# the Antora site build (a devcontainer feature) and the GitHub CLI -- plus a
# docker socket for the containerised converge tests.
FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Two Ruby tools.  asciidoctor renders a single .adoc for a quick look and
# backs the VS Code preview; the published site is built by Antora
# (`invoke site`), not by this gem.  kramdoc (kramdown-asciidoc) converts
# Markdown pages during that site build.  Both pinned so output does not
# drift.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ruby-full \
    && gem install --no-document asciidoctor -v 2.0.23 \
    && gem install --no-document kramdown-asciidoc -v 2.1.1 \
    && rm -rf /var/lib/apt/lists/*

# GitHub CLI from the official apt repository.
RUN mkdir -p -m 755 /etc/apt/keyrings \
    && curl -fsSL \
        https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        -o /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && arch="$(dpkg --print-architecture)" \
    && key=/etc/apt/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$arch signed-by=$key]" \
            "https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

# uv comes from the same script the host uses, so both environments install it
# the same way.  As root here, so it lands in /usr/local/bin for every user.
COPY scripts/install-uv.sh /tmp/install-uv.sh
RUN UV_INSTALL_DIR=/usr/local/bin /tmp/install-uv.sh && rm /tmp/install-uv.sh

USER vscode
ENV UV_LINK_MODE=copy
