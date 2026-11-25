# -*- coding: utf-8 -*-
"""Serbian Cyrillic -> Latin for subtitle files.

The Serbian alphabet maps letter for letter, so no dictionary is needed. The three digraph letters
(Lj, Nj, Dž) stay upper case inside an all-caps word: ЉУБАВ -> LJUBAV, but Љубав -> Ljubav.
Cyrillic letters that Serbian does not use (Russian ы, э, ё, ...) are left alone."""
import codecs

_PAIRS = (
    ('А', 'A'), ('Б', 'B'), ('В', 'V'), ('Г', 'G'), ('Д', 'D'), ('Ђ', 'Đ'), ('Е', 'E'), ('Ж', 'Ž'), ('З', 'Z'),
    ('И', 'I'), ('Ј', 'J'), ('К', 'K'), ('Л', 'L'), ('Љ', 'Lj'), ('М', 'M'), ('Н', 'N'), ('Њ', 'Nj'), ('О', 'O'),
    ('П', 'P'), ('Р', 'R'), ('С', 'S'), ('Т', 'T'), ('Ћ', 'Ć'), ('У', 'U'), ('Ф', 'F'), ('Х', 'H'), ('Ц', 'C'),
    ('Ч', 'Č'), ('Џ', 'Dž'), ('Ш', 'Š'),
)
_MAP = {}
for _cyr, _lat in _PAIRS:
    _MAP[_cyr] = _lat
    _MAP[_cyr.lower()] = _lat.lower()


def has_cyrillic(text):
    """True when the text has at least one letter this module converts."""
    return any(ch in _MAP for ch in text)


def to_latin(text):
    out = []
    for i, ch in enumerate(text):
        latin = _MAP.get(ch)
        if latin is None:
            out.append(ch)
            continue
        if len(latin) == 2 and ch.isupper():
            before = text[i - 1] if i else ''
            after = text[i + 1] if i + 1 < len(text) else ''
            if before.isupper() or after.isupper():
                latin = latin.upper()
        out.append(latin)
    return ''.join(out)


def _cyrillic_share(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for ch in letters if u'Ѐ' <= ch <= u'ӿ') / float(len(letters))


def _decode(data):
    """Subtitle bytes -> text, or None when the bytes are not Cyrillic text we can read with confidence.
    UTF-8 (with or without BOM) and UTF-16 with a BOM are tried first. Old Serbian files are often Windows-1251, but
    Windows-1251 decodes ANY byte, and a Latin file in Windows-1250 (č, š, ž, đ) would turn into Cyrillic nonsense,
    so that fallback is only trusted when most of the letters it gives are Cyrillic."""
    if data.startswith(codecs.BOM_UTF16_LE) or data.startswith(codecs.BOM_UTF16_BE):
        return data.decode('utf-16')
    try:
        return data.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = data.decode('cp1251')
        return text if _cyrillic_share(text) >= 0.5 else None


def is_serbian(language):
    """The language HolyArrs reports for a result ('sr', 'srp', 'sr-Cyrl'); nothing else is converted."""
    return str(language or '').lower()[:2] == 'sr'


def subtitle_to_latin(data):
    """Returns (bytes, converted). Subtitle bytes with Cyrillic letters come back as UTF-8 Latin text; bytes without
    any (already Latin) come back unchanged with converted False."""
    text = _decode(bytes(data))
    if text is None or not has_cyrillic(text):
        return bytes(data), False
    return to_latin(text).encode('utf-8'), True
