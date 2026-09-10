# How to add a new project

This tool is designed to share a single core engine across many different
projects — each project only needs its own config file, no code changes
required.

## Steps

1. Copy the template file:
   ```bash
   cp configs/_template.yaml configs/<your_project_name>.yaml
   ```
   The file name (without `.yaml`) becomes the display name in the
   project dropdown on the UI.

2. Open the new file and fill in:
   - `project_name`: the full display name
   - `platform`: web / ios / android (multiple allowed)
   - `test_id_format`: the test case ID format matching your team's convention
   - `test_types_required`: the test case types to prioritize
   - `domain_rules`: **the most important field** — the more detailed,
     the more realistic the AI's generated cases will be, e.g.:
     - Input validation rules (phone number, email, password...)
     - Business limits (max quantity, timeout duration...)
     - System-specific behavior on error
   - `glossary`: definitions of terms specific to your system/domain, so
     the AI doesn't misread the context
   - `notes`: anything else you want the AI to keep in mind (e.g. which
     module to test most thoroughly)

3. Re-run the app (`streamlit run app.py`) — the new project will
   automatically show up in the dropdown, no code changes needed.

## Tips for effective configs

- Start with a simple config, try it against a few real requirements,
  see how accurate the AI's generated cases are, then gradually expand
  `domain_rules` based on where the AI misunderstood or missed something.
- If your team has modules with very different rules (e.g. a Payment
  module vs. a User Profile module), consider splitting into separate
  "sub-configs" or clearly noting in `domain_rules` which rule applies
  to which module.
- Periodically review the config based on feedback from testers using
  it in practice.

## If you want to change the shared generation logic (applies to all projects)

Edit `prompts/base_system_prompt.md`. This file contains the common
rules (required test case classification, JSON output format...) that
apply to every project. Project-specific information shouldn't go here
— put it in the corresponding YAML config file instead.
