# -*- coding: utf-8 -*-

import json
import os
import sys
import time

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

__addon__ = xbmcaddon.Addon()
__dialog__ = xbmcgui.Dialog()
__player__ = xbmc.Player()
__addonname__ = __addon__.getAddonInfo('name')
__addonid__ = __addon__.getAddonInfo('id')
get_local_str = __addon__.getLocalizedString

__cwd__ = xbmcvfs.translatePath(__addon__.getAddonInfo('path'))
__resource__ = xbmcvfs.translatePath(os.path.join(__cwd__, 'resources', 'lib'))
sys.path.append(__resource__)

from prelogging import Prelogger  # noqa: E402
import preutils as pu  # noqa: E402
from holyarrs import (  # noqa: E402
    HolyArrsClient, HolyArrsNotConfigured, HolyArrsItemNotFound, HolyArrsAuthError, HolyArrsHTTPError,
    is_foreign_file_conflict, conflicting_subtitles,
)

try:
    import requests
except ImportError:
    requests = None


class ActionHandler(object):

    def __init__(self, raw_params):
        self.log = Prelogger()
        self.params = pu.get_params(raw_params[2])
        self.action = self.params['?action'][0] if '?action' in self.params else self.params.get('action', [None])[0]
        self.handle = int(raw_params[1])
        self.log.debug("Action='{0}' params={1}".format(self.action, self.params))

        self.ACTION_MAP = {
            'search': self.search,
            'manualsearch': self.manual_search,
            'download': self.download,
        }

        self.client = self._build_client()

    @staticmethod
    def _holyarrs_error_string(exc):
        """The message id for a failed HolyArrs call: a refused key and an HTTP error are not 'could not reach'."""
        if isinstance(exc, HolyArrsAuthError):
            return 32009
        if isinstance(exc, HolyArrsHTTPError):
            return 32010
        return 32007

    def _build_client(self):
        try:
            verify_ssl = __addon__.getSettingBool('verify_ssl')
        except Exception:
            verify_ssl = __addon__.getSetting('verify_ssl') != 'false'
        try:
            return HolyArrsClient(__addon__.getSetting('holyarrs_url'), __addon__.getSetting('holyarrs_apikey'),
                                  verify_ssl=verify_ssl)
        except HolyArrsNotConfigured:
            self.notify(get_local_str(32005))
            return None

    def notify(self, message):
        xbmc.executebuiltin('Notification({0}, {1})'.format(__addonname__, message))
        self.log.warning(message)

    def do(self):
        if self.action not in self.ACTION_MAP:
            self.notify(get_local_str(32000))
            return
        if self.client is None:
            return
        self.ACTION_MAP[self.action]()

    # -----------------------------------------------------------------
    # search - list available subtitles for the item Kodi is asking about
    # -----------------------------------------------------------------

    def search(self):
        show = self.get_current_show()
        wanted_langs = pu.kodi_langs_to_iso639_1(self.params.get('languages', [''])[0])
        self.log.debug("Current show: {0}, wanted langs: {1}".format(show, wanted_langs))
        self._search_files(show, wanted_langs)

    def _search_files(self, show, wanted_langs):
        """HolyArrs: find the playing file by its library path, then ask its
        subtitle sites for candidates (nothing is saved until one is picked)."""
        media_type = 'episode' if show.get('type') == 'episode' else 'movie'
        added = []
        try:
            found = self.client.find_file(show.get('file_original_path'), media_type=media_type,
                                          title=show.get('title'), tvshow_title=show.get('tvshow_title'))
            # Kodi asked for these languages; HolyArrs only searches the file's wished ones.
            added = self.client.ensure_languages(found, wanted_langs)
            if added:
                self.log.debug("Added {0} to this file's wish".format(added))
            results = self.client.list_subtitles(found['file_id'])
        except HolyArrsItemNotFound as exc:
            self.log.warning(str(exc))
            self.notify(get_local_str(32006))
            return
        except Exception as exc:  # noqa: BLE001 - surface any transport error to the user
            self.log.error("HolyArrs request failed: {0}".format(exc))
            self.notify(get_local_str(self._holyarrs_error_string(exc)))
            return

        if wanted_langs:
            results = [r for r in results if str(r.get('language', '')).lower()[:2] in wanted_langs]
        if not results:
            # Nothing to pick: do not leave the temporary wish behind.
            if added and found.get('item_id'):
                try:
                    self.client.clear_wish(found['title_id'], found['item_id'])
                except Exception as exc:  # noqa: BLE001
                    self.log.warning("Could not drop the temporary wish: {0}".format(exc))
            self.notify(get_local_str(32008))
            return

        # The temporary wish stays until the pick is saved (HolyArrs only accepts a pick for a wished language).
        context = {'file_id': found['file_id'], 'title_id': found.get('title_id'),
                   'item_id': found.get('item_id'), 'temp_wish': bool(added)}
        for result in results:
            self._add_search_result_item(show, context, result)

    def manual_search(self):
        # HolyArrs searches with the library item's own metadata; a typed search term has nothing to bind to,
        # so re-run the normal search.
        self.search()

    def _add_search_result_item(self, show, context, result):
        lang_code = str(result.get('language', ''))
        kodi_lang_name = xbmc.convertLanguage(lang_code, xbmc.ENGLISH_NAME) or lang_code
        # 'label' must be a plain language name/code - Kodi's C++ subtitle
        # dialog parses THIS field (via CLangCodeExpander::ConvertToISO6391)
        # to build the destination filename when saving to the movie folder.
        # Anything else here (provider, brackets, etc.) makes that parse
        # fail and produces a language-less filename instead of matching
        # the naming of the subtitle files HolyArrs saves.
        label = kodi_lang_name
        label2 = "[B]{0} - {1}[/B]".format(result.get('provider') or '', result.get('release_info') or '')
        list_item = xbmcgui.ListItem(label=label, label2=label2)
        kodi_lang = xbmc.convertLanguage(lang_code, xbmc.ISO_639_1) or lang_code
        list_item.setArt({'thumb': kodi_lang})

        plugin_url = "plugin://{0}/?action=download&context={1}&result={2}&filepath={3}".format(
            __addonid__,
            pu.get_quoted_str(json.dumps(context)),
            pu.get_quoted_str(json.dumps(result, default=str)),
            pu.get_quoted_str(show['file_original_path']),
        )
        xbmcplugin.addDirectoryItem(handle=self.handle, url=plugin_url, listitem=list_item, isFolder=False)

    # -----------------------------------------------------------------
    # download - HolyArrs saves the chosen result beside the video
    # -----------------------------------------------------------------

    def download(self):
        context = json.loads(self.params['context'][0])
        result = json.loads(self.params['result'][0])
        video_path = self.params['filepath'][0]
        self._download(context, result, pu.dir_of(video_path), pu.path_stem(video_path))

    def _remove_old_subtitles(self, video_dir, video_stem, language):
        """Ask before touching anything, then delete this video's old subtitle files for the language so HolyArrs can
        save the new one under that name. The contents are kept in memory until the save works, so a failed save
        puts them back. Returns [(path, bytes)] for what was removed; empty when nothing was removed."""
        _dirs, files = xbmcvfs.listdir(video_dir)
        names = conflicting_subtitles(files, video_stem, language)
        if not names:
            return []
        if not __dialog__.yesno(get_local_str(32011), get_local_str(32012).format(', '.join(names))):
            return []
        removed = []
        base = video_dir.rstrip('/') + '/'
        for name in names:
            path = base + name
            try:
                handle = xbmcvfs.File(path)
                content = handle.readBytes()
                handle.close()
            except Exception as exc:  # noqa: BLE001
                self.log.error("Could not read {0} before replacing it: {1}".format(path, exc))
                self._restore_subtitles(removed)
                return []
            if not xbmcvfs.delete(path):
                self.log.error("Could not delete {0}".format(path))
                self._restore_subtitles(removed)
                return []
            removed.append((path, content))
        return removed

    def _restore_subtitles(self, removed):
        for path, content in removed:
            try:
                handle = xbmcvfs.File(path, 'w')
                handle.write(content)
                handle.close()
            except Exception as exc:  # noqa: BLE001
                self.log.error("Could not put {0} back: {1}".format(path, exc))

    def _download(self, context, result, video_dir, video_stem=''):
        """HolyArrs saves the chosen subtitle beside the video itself and says
        where; wait briefly for the share to show the file, then hand it to Kodi."""
        moved = []
        try:
            try:
                saved = self.client.choose(context['file_id'], result)
            except Exception as exc:  # noqa: BLE001
                if not is_foreign_file_conflict(exc):
                    raise
                # HolyArrs never overwrites a subtitle it did not save. Offer to replace the old one, then try again.
                moved = self._remove_old_subtitles(video_dir, video_stem, str(result.get('language', '')))
                if not moved:
                    raise
                saved = self.client.choose(context['file_id'], result)
        except Exception as exc:  # noqa: BLE001
            self.log.error("HolyArrs choose failed: {0}".format(exc))
            self._restore_subtitles(moved)  # the new one was not saved: put the old subtitle back
            self.notify(get_local_str(self._holyarrs_error_string(exc)))
            self.add_subtitle_dir_item('')
            return
        name = pu.path_leaf(saved or '')
        if not name:
            self.notify(get_local_str(32003))
            self.add_subtitle_dir_item('')
            return
        if context.get('temp_wish') and context.get('item_id'):
            try:
                self.client.clear_wish(context['title_id'], context['item_id'])  # the saved file now covers the language
            except Exception as exc:  # noqa: BLE001
                self.log.warning("Could not drop the temporary wish: {0}".format(exc))
        subtitle_path = video_dir.rstrip('/') + '/' + name
        try:
            wait_seconds = __addon__.getSettingInt('download_wait_seconds')
        except Exception:
            wait_seconds = int(__addon__.getSetting('download_wait_seconds') or 8)
        deadline = time.time() + wait_seconds
        while not xbmcvfs.exists(subtitle_path) and time.time() < deadline:
            time.sleep(0.5)  # a network share can show a new file a moment late
        if not xbmcvfs.exists(subtitle_path):
            self.log.warning("HolyArrs saved {0} but {1} does not show it within {2}s".format(saved, subtitle_path, wait_seconds))
            self.notify(get_local_str(32003))
            self.add_subtitle_dir_item('')
            return
        self.add_subtitle_dir_item(self._stage_locally(subtitle_path, name) or subtitle_path)

    def _stage_locally(self, subtitle_path, name):
        """Copy the saved subtitle from the share to a local folder and hand Kodi THAT path. Kodi copies the file the
        add-on names into its own temp folder, and on some NFS shares that copy fails right after HolyArrs wrote the
        file ('Saving of subtitle nfs://... to special://temp/... failed'). Reading it here puts the real error in the
        log, and Kodi then copies a local file. Returns the local path, or '' (Kodi then gets the share path)."""
        try:
            folder = xbmcvfs.translatePath('special://temp/' + __addonid__ + '/')
            xbmcvfs.mkdirs(folder)
            target = folder + name
            source = xbmcvfs.File(subtitle_path)
            try:
                data = source.readBytes()
            finally:
                source.close()
            if not data:
                raise IOError('read 0 bytes')
            out = xbmcvfs.File(target, 'w')
            try:
                written = out.write(data)
            finally:
                out.close()
            if not written:
                raise IOError('could not write {0}'.format(target))
            self.log.debug('Staged {0} ({1} bytes) at {2}'.format(subtitle_path, len(data), target))
            return target
        except Exception as exc:  # noqa: BLE001
            self.log.error('Could not copy {0} to a local file: {1}'.format(subtitle_path, exc))
            return ''

    def add_subtitle_dir_item(self, subtitle_path):
        list_item = xbmcgui.ListItem(label=subtitle_path)
        xbmcplugin.addDirectoryItem(handle=self.handle, url=subtitle_path, listitem=list_item, isFolder=False)

    # -----------------------------------------------------------------
    # figure out what's currently playing / focused, same approach the
    # original titlovi-cobric addon used
    # -----------------------------------------------------------------

    def get_current_show(self):
        item = {}
        if __player__.isPlaying():
            tag = __player__.getVideoInfoTag()
            media_type = tag.getMediaType()
            item['type'] = media_type
            item['file_original_path'] = __player__.getPlayingFile()

            if media_type == 'episode':
                item['season'] = int(xbmc.getInfoLabel("VideoPlayer.Season") or 0)
                item['episode'] = int(xbmc.getInfoLabel("VideoPlayer.Episode") or 0)
                item['tvshow_title'] = xbmc.getInfoLabel("VideoPlayer.TVShowTitle").replace(':', '')
                episode_id = tag.getDbId()
                episode_details = self._json_rpc('VideoLibrary.GetEpisodeDetails', {
                    'episodeid': episode_id, 'properties': ['tvshowid']})
                tvshow_id = episode_details['episodedetails']['tvshowid']
                show_details = self._json_rpc('VideoLibrary.GetTVShowDetails', {
                    'tvshowid': tvshow_id, 'properties': ['uniqueid']})
                unique_ids = show_details['tvshowdetails'].get('uniqueid', {})
                item['tvdb_id'] = unique_ids.get('tvdb')
                item['imdb_id'] = unique_ids.get('imdb')
            elif media_type == 'movie':
                item['imdb_id'] = tag.getUniqueID('imdb')
                item['year'] = tag.getYear()
                item['title'] = tag.getTitle()
        else:
            item = self._get_current_show_from_focused_item()

        self.log.debug("Resolved current show: {0}".format(item))
        return item

    def _get_current_show_from_focused_item(self):
        media_type = xbmc.getInfoLabel("ListItem.DBTYPE")
        is_episode = media_type == 'episode' or xbmc.getCondVisibility("Container.Content(episodes)")
        item = {
            'file_original_path': xbmc.getInfoLabel("ListItem.FileNameAndPath"),
        }
        if is_episode:
            item['type'] = 'episode'
            item['season'] = int(xbmc.getInfoLabel("ListItem.Season") or 0)
            item['episode'] = int(xbmc.getInfoLabel("ListItem.Episode") or 0)
            item['tvshow_title'] = xbmc.getInfoLabel("ListItem.TVShowTitle").replace(':', '')
            item['tvdb_id'] = None  # not reliably available for a focused (non-playing) episode item
            item['imdb_id'] = None
        else:
            item['type'] = 'movie'
            item['title'] = xbmc.getInfoLabel("ListItem.Title") or xbmc.getInfoLabel("ListItem.OriginalTitle")
            item['year'] = xbmc.getInfoLabel("ListItem.Year")
            item['imdb_id'] = None
        return item

    @staticmethod
    def _json_rpc(method, params):
        request = {"jsonrpc": "2.0", "method": method, "params": params, "id": 1}
        response = json.loads(xbmc.executeJSONRPC(json.dumps(request)))
        if 'error' in response:
            raise RuntimeError("JSON-RPC {0} failed: {1}".format(method, response['error']))
        return response['result']


if __name__ == '__main__':
    handler = ActionHandler(sys.argv)
    handler.do()
    xbmcplugin.endOfDirectory(int(sys.argv[1]))
