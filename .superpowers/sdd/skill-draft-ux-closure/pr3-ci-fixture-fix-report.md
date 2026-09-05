# PR3 CI Fixture Fix Report

## Status

Fixture compatibility update completed. Production code and unrelated files were not modified.

## Change

Updated all three mock LLM `when_to_use` values in `backend/tests/integration/test_review_queue_integration.py` from the 12-character value `When testing` to the concrete English string:

`Use this skill whenever repeated testing steps need consistent validation`

## Verification

- Focused integration test command: `/home/fz/anaconda3/envs/sage-backend/bin/python -m pytest backend/tests/integration/test_review_queue_integration.py -q`
- Result: failed, `6 failed, 2 passed`
- Remaining failure cause: the existing mock `content` value (`# Test Skill\n\nTest content`) does not contain the newly required `## 步骤`, `## 触发条件`, and `## 示例` sections. This change removes the reported `when_to_use` length failure only.
- Ruff command: `conda run -n sage-backend ruff check backend/tests/integration/test_review_queue_integration.py`
- Ruff result: passed

## Commit

`fix(test): update review queue fixture for schema validation`
