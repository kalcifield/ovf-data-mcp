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
- Spatial feature queries and series comparison are not implemented.
