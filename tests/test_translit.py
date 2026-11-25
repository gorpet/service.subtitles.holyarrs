# -*- coding: utf-8 -*-
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'lib'))

from translit import has_cyrillic, is_serbian, subtitle_to_latin, to_latin  # noqa: E402

SRT = u'1\n00:00:01,000 --> 00:00:02,500\n<i>Љубав и ђак, ћуприја, шљива, џем, његов</i>\n\n'
SRT_LATIN = u'1\n00:00:01,000 --> 00:00:02,500\n<i>Ljubav i đak, ćuprija, šljiva, džem, njegov</i>\n\n'


class ToLatinTests(unittest.TestCase):
    def test_every_serbian_letter_maps(self):
        upper = u'АБВГДЂЕЖЗИЈКЛЉМНЊОПРСТЋУФХЦЧЏШ'
        # in an all-caps run the digraphs stay all caps (LJ, NJ, DŽ)
        self.assertEqual(to_latin(upper), u'ABVGDĐEŽZIJKLLJMNNJOPRSTĆUFHCČDŽŠ')
        self.assertEqual(to_latin(upper.lower()), u'abvgdđežzijklljmnnjoprstćufhcčdžš')

    def test_a_sentence(self):
        self.assertEqual(to_latin(u'Добро јутро, како сте?'), u'Dobro jutro, kako ste?')

    def test_digraphs_keep_the_case_of_the_word(self):
        self.assertEqual(to_latin(u'Љубав'), u'Ljubav')
        self.assertEqual(to_latin(u'ЉУБАВ'), u'LJUBAV')
        self.assertEqual(to_latin(u'Његов'), u'Njegov')
        self.assertEqual(to_latin(u'ЊЕГОВ'), u'NJEGOV')
        self.assertEqual(to_latin(u'ЏЕМ'), u'DŽEM')
        self.assertEqual(to_latin(u'Џем'), u'Džem')
        self.assertEqual(to_latin(u'љубав'), u'ljubav')

    def test_latin_text_markup_and_numbers_are_untouched(self):
        text = u'1\n00:00:01,000 --> 00:00:02,000\n{\\an8}<i>Hello, čćšžđ 42</i>\n'
        self.assertEqual(to_latin(text), text)

    def test_russian_only_letters_are_left_alone(self):
        self.assertEqual(to_latin(u'ы э ё'), u'ы э ё')

    def test_has_cyrillic(self):
        self.assertTrue(has_cyrillic(u'abc ж'))
        self.assertFalse(has_cyrillic(u'abc čćšžđ'))


class SubtitleBytesTests(unittest.TestCase):
    def test_utf8_cyrillic_becomes_utf8_latin(self):
        out, changed = subtitle_to_latin(SRT.encode('utf-8'))
        self.assertTrue(changed)
        self.assertEqual(out.decode('utf-8'), SRT_LATIN)

    def test_a_utf8_bom_is_accepted(self):
        out, changed = subtitle_to_latin(b'\xef\xbb\xbf' + SRT.encode('utf-8'))
        self.assertTrue(changed)
        self.assertEqual(out.decode('utf-8'), SRT_LATIN)

    def test_utf16_with_a_bom(self):
        out, changed = subtitle_to_latin(SRT.encode('utf-16'))
        self.assertTrue(changed)
        self.assertEqual(out.decode('utf-8'), SRT_LATIN)

    def test_windows_1251_cyrillic(self):
        out, changed = subtitle_to_latin(SRT.encode('cp1251'))
        self.assertTrue(changed)
        self.assertEqual(out.decode('utf-8'), SRT_LATIN)

    def test_a_latin_utf8_file_is_returned_unchanged(self):
        data = SRT_LATIN.encode('utf-8')
        self.assertEqual(subtitle_to_latin(data), (data, False))

    def test_a_latin_windows_1250_file_is_not_mangled(self):
        # Serbian/Croatian Latin files are often Windows-1250. Read as Windows-1251 they look like Cyrillic.
        data = SRT_LATIN.encode('cp1250')
        self.assertEqual(subtitle_to_latin(data), (data, False))
        longer = (u'1\n00:00:01,000 --> 00:00:02,000\nŠta radiš? Čekam te ćale đak žena ' * 20).encode('cp1250')
        self.assertEqual(subtitle_to_latin(longer), (longer, False))

    def test_empty_input(self):
        self.assertEqual(subtitle_to_latin(b''), (b'', False))

    def test_bytearray_input(self):
        out, changed = subtitle_to_latin(bytearray(SRT.encode('utf-8')))
        self.assertTrue(changed)
        self.assertEqual(out.decode('utf-8'), SRT_LATIN)


class LanguageTests(unittest.TestCase):
    def test_serbian_codes(self):
        for code in ('sr', 'SR', 'srp', 'sr-Cyrl', 'sr_RS'):
            self.assertTrue(is_serbian(code), code)

    def test_other_languages(self):
        for code in ('hr', 'bs', 'ru', 'mk', 'bg', 'sl', '', None):
            self.assertFalse(is_serbian(code), code)


if __name__ == '__main__':
    unittest.main()
