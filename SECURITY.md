# Security

Orbis V1 is intended for a trusted household server. Expose it only on a
private network or behind an HTTPS ingress whose authentication and access
controls you have reviewed. Viewer profiles are not separate login accounts.
The first owner sets an Admin password during setup; do not reuse it elsewhere.

Provider modules are trusted Python code executed by the backend. They are not
sandboxed. Install code only from sources you trust, keep provider secrets in
the private runtime configuration directory, and restrict Admin/provider-editor
access. Never publish `.env`, `data/`, `config/providers/`, logs or backups.

For a vulnerability report, use the repository's private security-advisory
channel once available. Until then, contact the repository owner privately;
do not include live credentials or stream URLs in a public issue. A public
contact address has not yet been selected.

Supported version: Orbis 1.0.0. Security fixes should be
tested against the current V1 branch. An arbitrary provider adapter has full
server-code privileges; its behavior is outside the Orbis core security
boundary.
