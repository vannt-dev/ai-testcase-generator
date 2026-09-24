# Changelog

## Unreleased

- Keep uploaded review values literal. Values such as `-1`, `- Open the app` and `+84 ...` were
  previously stored with a leading `'`, corrupting the review prompt, editor and export. Excel
  export still writes every string as a literal text cell.

## 0.1.0 - 2026-09-22

- First versioned public Streamlit application release, with configurable project requirements,
  test generation, editable results, session history, coverage review and Excel export.
- Review uploaded CSV/XLSX files, confirm column mappings, generate missing cases, and merge results.
- Export all text as literal Excel cells, including formula-like text and summary questions.
- Bound upload bytes, rows, columns and field lengths; report CSV/lazy-XLSX parsing errors in the UI.
  Limits are 10 MiB per file, 500 data rows, 256 columns, and 131,072 characters per field.
- Include 106 regression and Streamlit-page tests. AI generation requires an Anthropic API key;
  deterministic tests do not validate the quality of live model responses.

Install with Python 3.10+ and `pip install -r requirements.txt`, then `streamlit run app.py`.
Use a fresh tagged checkout when upgrading and retain your project YAML files separately.
