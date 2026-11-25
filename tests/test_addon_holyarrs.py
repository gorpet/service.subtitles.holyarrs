# -*- coding: utf-8 -*-
"""Runs the add-on's real search/download code with Kodi stubbed."""
import importlib
import json
import os
import sys
import unittest
from unittest import mock

from kodistubs import ROOT, install

S = install()
sys.path.insert(0, ROOT)
addon = importlib.import_module('addon')


class FakeClient(object):
    def __init__(self, results=None, found=None, saved='Nobody (2021)/Nobody (2021).hr.srt', fail=None):
        self.results, self.saved, self.fail = results or [], saved, fail
        self.found = found if found is not None else {'file_id': 11, 'item_id': 11, 'title_id': 4, 'relative_path': 'Nobody (2021)/Nobody (2021).mkv',
                                                      'wish': [{'language': 'hr', 'hearing_impaired': 'normal', 'forced': False}]}
        self.calls = []
        self.on_saved = None  # called when choose succeeds, to make the new file appear
        self.conflicts = 0  # how many times choose answers 'a subtitle HolyArrs did not save is there' (HTTP 409)
        self.added = None  # what ensure_languages answers; None = work out from the wish like the real client

    def find_file(self, video_path, media_type='movie', title=None, tvshow_title=None):
        self.calls.append(('find_file', video_path, media_type, title, tvshow_title))
        if self.fail == 'notfound':
            raise addon.HolyArrsItemNotFound('nope')
        if self.fail == 'down':
            raise RuntimeError('connection refused')
        return self.found

    def ensure_languages(self, found, wanted):
        have = [w['language'] for w in found.get('wish', [])]
        added = [l for l in wanted if l not in have] if self.added is None else self.added
        self.calls.append(('ensure', tuple(wanted), tuple(added)))
        return added

    def clear_wish(self, title_id, item_id):
        self.calls.append(('clear_wish', title_id, item_id))

    def list_subtitles(self, file_id):
        self.calls.append(('list', file_id))
        return self.results

    def choose(self, file_id, result):
        self.calls.append(('choose', file_id, result['subtitle']))
        if self.fail == 'choose':
            raise RuntimeError('boom')
        if self.conflicts > 0:
            self.conflicts -= 1
            raise addon.HolyArrsHTTPError(409, 'a subtitle file HolyArrs did not save is at that name; it is left alone')
        if self.on_saved:
            self.on_saved()
        return self.saved


def result(lang='hr', site='Titlovi', key='2', score=72, rel='Rel.A'):
    return {'language': lang, 'forced': False, 'hearing_impaired': False, 'provider': site, 'score': score,
            'release_info': rel, 'subtitle': {'site': site, 'key': key}}


def handler(query, client):
    h = addon.ActionHandler(['plugin://service.subtitles.holyarrs/', '1', query])
    h.client = client
    return h


class SearchTests(unittest.TestCase):
    def setUp(self):
        S.reset()

    def test_the_client_is_a_holyarrs_client(self):
        self.assertEqual(type(addon.ActionHandler(['p', '1', '?action=search']).client).__name__, 'HolyArrsClient')

    def test_missing_holyarrs_settings_notify_and_stop(self):
        S.settings['holyarrs_apikey'] = ''
        h = addon.ActionHandler(['p', '1', '?action=search'])
        self.assertIsNone(h.client)
        self.assertIn('str32005', S.notifications[-1])
        h.do()
        self.assertEqual(S.items, [])

    def test_search_lists_wanted_languages_only(self):
        c = FakeClient([result('hr', key='2', score=72), result('sr', key='9', score=60), result('en', key='5', score=90)])
        handler('?action=search&languages=Croatian,Serbian', c).do()
        self.assertEqual(c.calls[0], ('find_file', '/media/movies/Nobody (2021)/Nobody (2021).mkv', 'movie', 'Nobody', None))
        self.assertEqual(c.calls[1], ('ensure', ('hr', 'sr'), ('sr',)))  # Serbian is not in this file's wish, so it is added for this file
        self.assertEqual(c.calls[2], ('list', 11))
        self.assertEqual([i[1] for i in S.items], ['Croatian', 'Serbian'])  # English filtered out, label is a plain language name
        self.assertIn('Titlovi', S.items[0][2])
        url = S.items[0][0]
        self.assertIn('action=download', url)
        self.assertIn('%22file_id%22%3A+11', url)  # context carries the file to save for

    def test_episode_search_passes_show_and_path(self):
        S.playing = {'type': 'episode', 'file': '/m/series/Krypton/Season 02/Krypton 02x09 - Blood Moon.mkv'}
        S.infolabels = {'VideoPlayer.Season': '2', 'VideoPlayer.Episode': '9', 'VideoPlayer.TVShowTitle': 'Krypton'}
        c = FakeClient([result()])
        handler('?action=search&languages=Croatian', c).do()
        self.assertEqual(c.calls[0], ('find_file', '/m/series/Krypton/Season 02/Krypton 02x09 - Blood Moon.mkv', 'episode', None, 'Krypton'))
        self.assertEqual(len(S.items), 1)

    def test_a_language_outside_the_wish_is_added_for_this_file_and_kept_for_the_pick(self):
        c = FakeClient([result('bs', key='7', score=55)])
        handler('?action=search&languages=Bosnian', c).do()
        self.assertEqual(c.calls[1], ('ensure', ('bs',), ('bs',)))
        self.assertEqual(c.calls[2], ('list', 11))
        self.assertNotIn('clear_wish', [x[0] for x in c.calls])  # still needed when the pick is saved
        ctx = S.items[0][0]
        self.assertIn('%22temp_wish%22%3A+true', ctx)
        self.assertIn('%22item_id%22%3A+11', ctx)

    def test_a_wished_language_adds_nothing(self):
        c = FakeClient([result('hr')])
        handler('?action=search&languages=Croatian', c).do()
        self.assertEqual(c.calls[1], ('ensure', ('hr',), ()))
        self.assertIn('%22temp_wish%22%3A+false', S.items[0][0])

    def test_nothing_found_drops_the_temporary_wish_at_once(self):
        c = FakeClient([])
        handler('?action=search&languages=Bosnian', c).do()
        self.assertIn(('clear_wish', 4, 11), c.calls)
        self.assertIn('str32008', S.notifications[-1])

    def test_nothing_to_offer_says_so(self):
        handler('?action=search&languages=Croatian', FakeClient([])).do()
        self.assertEqual(S.items, [])
        self.assertIn('str32008', S.notifications[-1])

    def test_not_found_and_unreachable_notify(self):
        handler('?action=search&languages=Croatian', FakeClient(fail='notfound')).do()
        self.assertIn('str32006', S.notifications[-1])
        handler('?action=search&languages=Croatian', FakeClient(fail='down')).do()
        self.assertIn('str32007', S.notifications[-1])
        self.assertEqual(S.items, [])


class DownloadTests(unittest.TestCase):
    def setUp(self):
        S.reset()

    def query(self, res=None, kind='holyarrs'):
        ctx = json.dumps({'kind': kind, 'file_id': 11})
        from urllib.parse import quote_plus
        return '?action=download&context=%s&result=%s&filepath=%s' % (
            quote_plus(ctx), quote_plus(json.dumps(res or result())), quote_plus('/media/movies/Nobody (2021)/Nobody (2021).mkv'))

    def test_download_drops_the_temporary_wish_after_the_save(self):
        S.existing = {'/media/movies/Nobody (2021)/Nobody (2021).hr.srt'}
        c = FakeClient()
        ctx = json.dumps({'kind': 'holyarrs', 'file_id': 11, 'title_id': 4, 'item_id': 11, 'temp_wish': True})
        from urllib.parse import quote_plus
        q = '?action=download&context=%s&result=%s&filepath=%s' % (quote_plus(ctx), quote_plus(json.dumps(result('bs'))),
                                                                    quote_plus('/media/movies/Nobody (2021)/Nobody (2021).mkv'))
        handler(q, c).do()
        self.assertEqual(c.calls, [('choose', 11, {'site': 'Titlovi', 'key': '2'}), ('clear_wish', 4, 11)])

    def test_download_chooses_and_hands_kodi_the_saved_file(self):
        S.existing = {'/media/movies/Nobody (2021)/Nobody (2021).hr.srt'}
        c = FakeClient()
        handler(self.query(), c).do()
        self.assertEqual(c.calls, [('choose', 11, {'site': 'Titlovi', 'key': '2'})])
        # Kodi is handed a local copy, not the share path (its own copy from some NFS shares fails)
        self.assertEqual(S.items[-1][0], 'special://temp/service.subtitles.holyarrs/Nobody (2021).hr.srt')
        self.assertEqual(S.contents['special://temp/service.subtitles.holyarrs/Nobody (2021).hr.srt'], b'old subtitle')

    def test_if_the_share_file_cannot_be_read_kodi_gets_the_share_path_and_the_log_says_why(self):
        S.existing = {'/media/movies/Nobody (2021)/Nobody (2021).hr.srt'}
        S.unreadable = {'/media/movies/Nobody (2021)/Nobody (2021).hr.srt'}
        with mock.patch.object(addon.time, 'sleep'):
            handler(self.query(), FakeClient()).do()
        self.assertEqual(S.items[-1][0], '/media/movies/Nobody (2021)/Nobody (2021).hr.srt')
        self.assertTrue(any('failed (attempt' in m and 'read failed' in m for m in S.log))   # why, per attempt
        self.assertTrue(any('Could not copy' in m for m in S.log))

    def test_a_stale_stat_size_does_not_stop_the_chunked_read(self):
        share = '/media/movies/Nobody (2021)/Nobody (2021).hr.srt'
        S.existing = {share}
        S.stale = {share}
        S.contents = {share: b'1\n00:00:01,000 --> 00:00:02,000\nHi\n'}
        with mock.patch.object(addon.time, 'sleep'):
            handler(self.query(), FakeClient()).do()
        local = 'special://temp/service.subtitles.holyarrs/Nobody (2021).hr.srt'
        self.assertEqual(S.items[-1][0], local)
        self.assertEqual(S.contents[local], S.contents[share])

    SR_SHARE = '/media/movies/Nobody (2021)/Nobody (2021).sr.srt'
    SR_LOCAL = 'special://temp/service.subtitles.holyarrs/Nobody (2021).sr.srt'
    CYRILLIC = u'1\n00:00:01,000 --> 00:00:02,000\nЉубав и ђак\n'.encode('utf-8')

    def download_sr(self, lang='sr', content=None):
        S.existing = {self.SR_SHARE}
        S.contents = {self.SR_SHARE: self.CYRILLIC if content is None else content}
        handler(self.query(result(lang)), FakeClient(saved='Nobody (2021)/Nobody (2021).sr.srt')).do()

    def test_a_cyrillic_serbian_subtitle_reaches_kodi_in_latin_and_the_saved_file_is_left_alone(self):
        self.download_sr()
        self.assertEqual(S.items[-1][0], self.SR_LOCAL)
        self.assertEqual(S.contents[self.SR_LOCAL].decode('utf-8'), u'1\n00:00:01,000 --> 00:00:02,000\nLjubav i đak\n')
        self.assertEqual(S.contents[self.SR_SHARE], self.CYRILLIC)          # HolyArrs' own file is untouched
        self.assertNotIn(self.SR_SHARE, S.written)

    def test_the_setting_turns_it_off(self):
        S.settings['serbian_to_latin'] = 'false'
        self.download_sr()
        self.assertEqual(S.contents[self.SR_LOCAL], self.CYRILLIC)

    def test_other_languages_are_never_converted(self):
        self.download_sr(lang='ru')
        self.assertEqual(S.contents[self.SR_LOCAL], self.CYRILLIC)

    def test_a_serbian_subtitle_that_is_already_latin_is_passed_through(self):
        latin = u'1\n00:00:01,000 --> 00:00:02,000\nLjubav i đak\n'.encode('cp1250')
        self.download_sr(content=latin)
        self.assertEqual(S.contents[self.SR_LOCAL], latin)

    def test_a_conversion_failure_still_hands_kodi_the_subtitle(self):
        with mock.patch.object(addon, 'subtitle_to_latin', side_effect=ValueError('boom')):
            self.download_sr()
        self.assertEqual(S.items[-1][0], self.SR_LOCAL)
        self.assertEqual(S.contents[self.SR_LOCAL], self.CYRILLIC)
        self.assertTrue(any('Could not convert' in m for m in S.log))

    def test_download_waits_for_the_share_then_gives_up(self):
        c = FakeClient()
        with mock.patch.object(addon.time, 'sleep'):
            handler(self.query(), c).do()
        self.assertEqual(S.items[-1][0], '')           # empty item = nothing for Kodi to load
        self.assertIn('str32003', S.notifications[-1])

    def test_download_failure_notifies(self):
        handler(self.query(), FakeClient(fail='choose')).do()
        self.assertEqual(S.items[-1][0], '')
        self.assertIn('str32007', S.notifications[-1])

    DIR = '/media/movies/Nobody (2021)/'

    def replace_setup(self, conflicts=1, answer=True, fail_after=False):
        S.files = {self.DIR.rstrip('/'): ['Nobody (2021).mkv', 'Nobody (2021).hr.srt', 'Nobody (2021).en.srt', 'Other (2020).hr.srt']}
        S.existing = {self.DIR + 'Nobody (2021).hr.srt'}
        c = FakeClient()
        c.conflicts = conflicts
        c.on_saved = lambda: S.existing.add(self.DIR + 'Nobody (2021).hr.srt')
        dialog = mock.Mock()
        dialog.yesno.return_value = answer
        return c, dialog

    def test_an_old_subtitle_is_replaced_after_asking_and_the_pick_is_saved(self):
        c, dialog = self.replace_setup()
        S.contents = {self.DIR + 'Nobody (2021).hr.srt': b'OLD'}
        with mock.patch.object(addon, '__dialog__', dialog), \
                mock.patch.object(addon, 'get_local_str', lambda i: 'replace: {0}' if i == 32012 else 'str%d' % i):
            handler(self.query(), c).do()
        self.assertEqual(S.deleted, [self.DIR + 'Nobody (2021).hr.srt'])
        self.assertNotIn(self.DIR + 'Nobody (2021).hr.srt', S.written)    # the old one was not put back: the save worked
        self.assertEqual([x[0] for x in c.calls], ['choose', 'choose'])
        self.assertIn('Nobody (2021).hr.srt', dialog.yesno.call_args[0][1])
        self.assertNotIn('.en.srt', dialog.yesno.call_args[0][1])        # only this language
        self.assertNotIn('Other (2020)', dialog.yesno.call_args[0][1])   # only this video
        self.assertEqual(S.items[-1][0], 'special://temp/service.subtitles.holyarrs/Nobody (2021).hr.srt')

    def test_saying_no_leaves_the_old_subtitle_alone(self):
        c, dialog = self.replace_setup(answer=False)
        with mock.patch.object(addon, '__dialog__', dialog):
            handler(self.query(), c).do()
        self.assertEqual(S.deleted, [])
        self.assertEqual([x[0] for x in c.calls], ['choose'])
        self.assertEqual(S.items[-1][0], '')
        self.assertIn('str32010', S.notifications[-1])

    def test_the_old_subtitle_is_written_back_when_the_new_one_still_cannot_be_saved(self):
        c, dialog = self.replace_setup(conflicts=2)
        old = self.DIR + 'Nobody (2021).hr.srt'
        S.contents = {old: b'OLD CONTENT'}
        with mock.patch.object(addon, '__dialog__', dialog):
            handler(self.query(), c).do()
        self.assertEqual(S.deleted, [old])
        self.assertEqual(S.written, [old])
        self.assertEqual(S.contents[old], b'OLD CONTENT')
        self.assertEqual(S.items[-1][0], '')

    def test_no_old_subtitle_found_means_no_question(self):
        c, dialog = self.replace_setup()
        S.files = {self.DIR.rstrip('/'): ['Nobody (2021).mkv']}
        with mock.patch.object(addon, '__dialog__', dialog):
            handler(self.query(), c).do()
        dialog.yesno.assert_not_called()
        self.assertEqual(S.deleted, [])
        self.assertIn('str32010', S.notifications[-1])


if __name__ == '__main__':
    unittest.main()
