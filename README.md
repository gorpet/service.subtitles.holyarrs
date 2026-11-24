# service.subtitles.holyarrs

Kodi subtitle add-on that asks your own **[HolyArrs](https://github.com/HolyArrs/HolyArrs)** server for
subtitles. HolyArrs does the subtitle-site work (scoring, downloading, saving); this add-on finds the playing
file in HolyArrs, lists the candidates in Kodi's subtitle dialog, and asks HolyArrs to save the one you pick
next to the video. Kodi and HolyArrs must see the media files at paths that end alike (a shared SMB/NFS mount).

It was split out of `service.subtitles.bazarr`, which stays a Bazarr add-on.

## Install

Add the repository https://gorpet.github.io in Kodi and install **HolyArrs** from *Subtitles* (see that
repository's README), or zip this folder and use *Add-ons -> Install from zip file*.

## Configure

*Add-ons -> My add-ons -> Subtitles -> HolyArrs -> Configure*:

- **HolyArrs URL** - e.g. `https://holyarrs.example.com` (the default `http://127.0.0.1:6262` only works when
  Kodi runs on the HolyArrs machine).
- **HolyArrs API key** - HolyArrs `Settings > API > Make key`, a key with the **all** scope (the add-on reads
  titles, saves subtitles and sets language wishes). Make a separate key for Kodi.
- **Verify SSL certificate** - turn off only for a self-signed certificate you cannot install.
- **Seconds to wait for the saved subtitle to appear** - how long to wait for a network share to show the file.
- **Enable debug logging** - verbose request lines in `kodi.log`.

## How it works

1. The playing (or focused) file is found by **path**: HolyArrs lists every file with a path relative to its
   library folder (`Nobody (2021)/Nobody (2021).mkv`) and Kodi's playing path ends with it (percent-escapes,
   case and `\` vs `/` are ignored). The title only narrows the lookup, with the folder name as a fallback.
2. `GET /api/v1/titles?q=` -> `GET /api/v1/titles/{id}/subtitles` (match by path) ->
   `POST /api/v1/files/{id}/subtitles/choices` (asks the subtitle sites now, scored candidates, saves nothing)
   -> `POST /api/v1/files/{id}/subtitles/choose` (`{"site","key"}`: saves the pick beside the video and
   answers its path). Auth is the `X-Api-Key` header.
3. Candidates are scored 0-100 by HolyArrs; a "refused" one (wrong title) is left out.

## Behaviour worth knowing

- **Languages outside the wish:** HolyArrs lists, and saves, only languages in the file's wish. You can keep the
  global wish short (say only Croatian, so the background search stays small) and still ask Kodi for Bosnian:
  the add-on adds the languages Kodi asks for ("Languages to download subtitles for") to THAT ONE file's own
  wish (`PUT /api/v1/titles/{id}/subtitle-wish` with the file's `item_id`), lists the candidates, and drops
  that wish after the pick is saved (or at once when nothing was found). The global setting is never changed.
  If you open the list and walk away without picking, the file keeps the extra language until you pick or
  HolyArrs finds one on its own. A search from Kodi costs one or two requests of the subtitle site's hourly limit.
- **Languages already covered:** from HolyArrs 1.3.0 on, the list shows candidates for every wished language,
  even one a sidecar or built-in track already has, so you can swap a subtitle. On HolyArrs 1.2.x only missing
  languages are offered.
- **Replacing a subtitle HolyArrs did not save:** HolyArrs never overwrites a subtitle file it did not save
  itself (for example one an older tool saved) and answers HTTP 409. The add-on then asks "Replace the existing
  subtitle?" and, on Yes, deletes that video's subtitle files for that language and asks HolyArrs to save the
  pick again, so the new one takes the old name. The old contents are held in memory until the save works; if it
  fails they are written back. Kodi needs write access to the folder (a read-only share cannot do this; the
  add-on logs it and leaves the old subtitle alone).
- **Error messages:** "HolyArrs refused the API key" (401/403), "HolyArrs answered with an error (see the Kodi
  log)" (other HTTP errors, with the status and HolyArrs' message in the log), "Could not reach HolyArrs"
  (connection failures only).
- `manualsearch` (Kodi's "search by typed term") re-runs the normal search: HolyArrs matches the library item,
  there is nothing for a typed term to bind to.

## The one thing that is easy to break

In `_add_search_result_item` the search result's **`label` must be a plain language name** (e.g. `"Croatian"`),
nothing appended. Kodi's subtitle dialog reads exactly this field to compute the filename it saves
(`{video}.{code}.{ext}`). If `label` is not parseable as a language, Kodi saves with an empty code
(`{video}..srt`). Put anything else you want shown (provider, release info) in `label2`.

## Tests

`cd tests && python3 -m unittest discover -p 'test_*.py'` runs the real search/download code with Kodi's Python
modules stubbed (`tests/kodistubs.py`). Not a Kodi emulator.
