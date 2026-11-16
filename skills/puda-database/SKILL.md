---
name: puda-database
description: Query the puda database using SQL and the puda CLI. Use when users need to inspect schema or run SQL commands
---

# Database Query

Query the puda database using the puda CLI with SQL.

## Purpose

This skill enables querying the puda database: understanding its schema and executing SQL statements via the puda CLI.

## When to Use

Load this skill when:
- Users want to query or inspect puda database data
- Users need to understand table and column structure before writing SQL
- Running ad-hoc SQL (e.g. filtering `command_log` by `command_name`)

## Required Resources

**IMPORTANT**: Before writing or running SQL, **consult the schema**:

1. **Schema**: Run `puda db schema` to see tables, columns, and types. Use this to write correct SQL and avoid invalid column/table names.

Do not assume table or column names; confirm them with `puda db schema` first.

**When getting data from biologic machine command**: data is always in `payload` at `payload["response"]["data"]`.

## Commands

- **`puda db schema`** – Print database schema (tables and columns). Use to understand structure before writing SQL.
- **`puda db exec "<SQL>"`** – Execute a single SQL statement. Pass the SQL as a quoted string.

## Example

```bash
puda db exec "SELECT * FROM command_log WHERE command_name='start'"
```

## Instructions

1. **Consult schema**: Run `puda db schema` to understand tables and columns before writing SQL.
2. **Execute SQL**: Use `puda db exec "<SQL>"` with the SQL in double quotes. Escape internal quotes as needed for your shell.
3. **Parse output**: Read command output to confirm success or to use result data in subsequent steps.
