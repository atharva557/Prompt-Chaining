"""Tests for code extraction, language detection and filename suggestion."""

import unittest

from ui.code_output import (
    extract_code,
    extract_files,
    _resolve_filenames,
    detect_language,
    suggest_filename,
)


class TestExtractCode(unittest.TestCase):
    def test_single_fenced_block(self):
        raw = "Here is your code:\n```python\nprint('hi')\n```\nEnjoy!"
        code, lang = extract_code(raw)
        self.assertEqual(code, "print('hi')")
        self.assertEqual(lang, "python")

    def test_largest_block_wins(self):
        raw = (
            "```bash\npip install x\n```\n"
            "```python\nimport os\n\nfor i in range(10):\n    print(i)\n```"
        )
        code, lang = extract_code(raw)
        self.assertEqual(lang, "python")
        self.assertIn("for i in range(10):", code)

    def test_no_fence_returns_raw(self):
        raw = "print('no fences here')"
        code, lang = extract_code(raw)
        self.assertEqual(code, raw)
        self.assertEqual(lang, "")

    def test_fence_language_lowercased(self):
        code, lang = extract_code("```Python\nx = 1\n```")
        self.assertEqual(lang, "python")
        self.assertEqual(code, "x = 1")


class TestExtractFiles(unittest.TestCase):
    def test_no_fences_returns_empty(self):
        self.assertEqual(extract_files("just prose, no code"), [])

    def test_single_unnamed_block(self):
        files = extract_files("Here you go:\n```python\nx = 1\n```")
        self.assertEqual(len(files), 1)
        self.assertIsNone(files[0]["name"])
        self.assertEqual(files[0]["lang"], "python")
        self.assertEqual(files[0]["code"], "x = 1")

    def test_names_picked_up_from_preceding_lines(self):
        raw = (
            "**app.py**\n```python\nprint('hi')\n```\n\n"
            "### style.css\n```css\nbody { margin: 0; }\n```\n\n"
            "`index.html`\n```html\n<html></html>\n```"
        )
        files = extract_files(raw)
        self.assertEqual([f["name"] for f in files], ["app.py", "style.css", "index.html"])

    def test_prose_line_before_fence_gives_no_name(self):
        raw = "First install the deps like this:\n```bash\npip install x\n```"
        files = extract_files(raw)
        self.assertIsNone(files[0]["name"])

    def test_relative_path_kept_parent_segments_stripped(self):
        raw = "src/main.js\n```js\nlet a = 1\n```\n\n../evil.py\n```python\nx\n```"
        files = extract_files(raw)
        self.assertEqual(files[0]["name"], "src/main.js")
        self.assertEqual(files[1]["name"], "evil.py")

    def test_empty_blocks_skipped(self):
        raw = "```python\n\n```\n```js\nlet x = 1\n```"
        files = extract_files(raw)
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0]["lang"], "js")


class TestResolveFilenames(unittest.TestCase):
    def test_unnamed_blocks_get_detected_extension(self):
        files = [{"name": None, "lang": "python", "code": "x = 1"}]
        self.assertEqual(_resolve_filenames(files, ""), ["file_1.py"])

    def test_duplicate_names_deduplicated(self):
        files = [
            {"name": "main.py", "lang": "python", "code": "a"},
            {"name": "main.py", "lang": "python", "code": "b"},
        ]
        names = _resolve_filenames(files, "")
        self.assertEqual(len(set(names)), 2)
        self.assertEqual(names[0], "main.py")


class TestDetectLanguage(unittest.TestCase):
    def test_fence_tag_has_priority(self):
        # Task says python, fence says javascript — fence wins
        self.assertEqual(detect_language("a python script", "x", "javascript"), "js")

    def test_fence_tag_already_extension(self):
        self.assertEqual(detect_language("", "", "py"), "py")

    def test_task_keyword(self):
        self.assertEqual(detect_language("make a react calculator", ""), "jsx")

    def test_keyword_whole_word_only(self):
        # "go" must not fire inside "logo"
        self.assertNotEqual(detect_language("design a logo generator", "text"), "go")

    def test_python_import_heuristic(self):
        self.assertEqual(detect_language("", "import os\nprint(1)"), "py")

    def test_html_heuristic(self):
        self.assertEqual(detect_language("", "<!DOCTYPE html><html></html>"), "html")

    def test_default_fallback(self):
        self.assertEqual(detect_language("something vague", "plain text"), "py")


class TestSuggestFilename(unittest.TestCase):
    def test_filler_words_removed(self):
        self.assertEqual(
            suggest_filename("make a react calculator app", "jsx"),
            "react_calculator_app.jsx",
        )

    def test_max_four_words(self):
        name = suggest_filename(
            "python script monitors folder watches files uploads logs", "py"
        )
        base = name.rsplit(".", 1)[0]
        self.assertLessEqual(len(base.split("_")), 4)

    def test_empty_task_fallback(self):
        self.assertEqual(suggest_filename("", "py"), "generated_code.py")

    def test_special_chars_stripped(self):
        name = suggest_filename("c.s.v -> json converter!!", "py")
        self.assertNotIn("!", name)
        self.assertNotIn(">", name)


if __name__ == "__main__":
    unittest.main()
