# Security Policy

## Supported release

NPIAC 0.6.x is the currently supported public beta line. Security fixes will be documented in the changelog and release notes.

## Reporting a vulnerability

Use [GitHub Private Vulnerability Reporting](https://github.com/dRafaleD/NPIAC/security/advisories/new) to submit details privately. Do not disclose an unpatched vulnerability, secret, credential, or private key in a public issue.

Include the affected version, operating system, reproduction steps, impact, and any suggested mitigation. Do not include real credentials or third-party private data in the report.

## Security model

Deterministic mode is local and performs no network requests. Optional Ollama enrichment sends bounded deterministic context and safe selected-source excerpts only to the configured Ollama endpoint. NPIAC excludes known secret-like files, credentials, private keys, lockfile contents, ignored paths, binaries, generated output, and unsafe symlinks from AI input.

These protections reduce accidental disclosure but do not replace repository access controls or a dedicated secret scanner. Review generated context before sharing it outside your trust boundary.
