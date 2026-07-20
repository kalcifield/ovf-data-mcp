# Known limitations

`ovf-data-mcp` is an experimental proof of concept, not production-ready software.

- CLI output, MCP schemas, and commands may change without compatibility guarantees.
- Access depends on the official website's anonymous frontend-token flow. This is not
  a documented third-party authentication contract and may stop working without notice.
- Upstream availability and schema changes are outside this project's control.
- Operational observations may be preliminary or unchecked. Verify important results
  against the cited OVF source.
- Dataset discovery and entity resolution are incomplete, especially for vague English
  queries, settlements, catchments, counties, and VIZIG territories.
- Coverage results do not yet report sampling gaps, expected result sizes, or freshness
  consistently.
- Spatial feature queries return attributes only; geometry is never requested, so
  polygons and maps are not available. Series comparison is not implemented.
- There is no logging. Diagnostics go to stderr from the CLI only, so the MCP server —
  where stdout is the JSON-RPC channel and stderr is usually swallowed by the host — has
  no place to report upstream timeouts, retries, aggregate-window bisects, or cache
  behaviour. Fix with stdlib `logging` plus a `RotatingFileHandler`, off by default and
  enabled through an env var; keep tokens and response bodies out of the file.
