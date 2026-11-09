from __future__ import annotations

import re
import unittest

from tyranor.i18n import TRANSLATIONS, Translator, resolve_language


class I18nTest(unittest.TestCase):
    def test_all_languages_share_keys_and_placeholders(self) -> None:
        reference = set(TRANSLATIONS["zh_CN"])
        for language in ("en", "ja"):
            self.assertEqual(set(TRANSLATIONS[language]), reference)
            for key in reference:
                zh_fields = set(re.findall(r"\{([a-z_]+)\}", TRANSLATIONS["zh_CN"][key]))
                other_fields = set(re.findall(r"\{([a-z_]+)\}", TRANSLATIONS[language][key]))
                self.assertEqual(other_fields, zh_fields, f"{language}:{key}")

    def test_unknown_language_falls_back(self) -> None:
        translator = Translator("unknown")
        self.assertIn(translator.text("nav.home"), {"首页", "Home"})

    def test_system_language_resolves(self) -> None:
        self.assertIn(resolve_language("system"), {"zh_CN", "en", "ja"})
