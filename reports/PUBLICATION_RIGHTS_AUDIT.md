# Publication rights audit

Result: **PASS for source publication**.

The local SmartVoyage reference directory and ZIP were inspected without modification. No `LICENSE`, `LICENCE`, `COPYING`, or `NOTICE` file was found. Because redistribution permission could not be established, the release excludes all SmartVoyage files, archives, data, logs, prompts, and assets.

An independent exact-content comparison covered 34 SmartVoyage code/configuration files and 134 ProcureFlow code/configuration files. It found:

- 0 identical non-empty files;
- 0 significant shared exact 24-token windows;
- 0 SmartVoyage files inside the ProcureFlow project tree.

ProcureFlow is a separate implementation with a procurement-specific schema, deterministic services and rules, four Agent contracts, LangGraph workflow, A2A transport, MCP tools, and assertion-based tests. General ideas such as environment configuration, parameterized database access, structured logging, MCP registration, and date serialization are common engineering patterns and were independently implemented.

The public repository intentionally has no project license because the owner did not select one. Public visibility alone does not grant reuse rights. Third-party Python packages and container images remain subject to their own licenses.

Machine-readable local evidence is stored in `reports/final_bugfix/rights-scan.json`. The SmartVoyage source and archive remain outside the repository and are excluded by publication checks.
