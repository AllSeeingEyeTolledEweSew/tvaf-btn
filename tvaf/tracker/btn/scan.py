import os
import re

import tvaf.scan
import tvaf.tracker.btn as tvaf_btn


BTN_FULL_SEASON_REGEX = re.compile(r"Season (?P<season>\d+)$")
BTN_EPISODE_REGEX = re.compile(r"S(?P<season>\d+)(?P<episodes>(E\d+)+)$")
BTN_EPISODE_PART_REGEX = re.compile(r"E(?P<episode>\d+)")
BTN_DATE_EPISODE_REGEX = re.compile(
    r"(?P<y>\d{4})[\.-](?P<m>\d\d)[\.-](?P<d>\d\d)$")
BTN_SEASON_PARTIAL_REGEXES = (
    re.compile(r"Season (?P<season>\d+)"),
    re.compile(r"(?P<season>\d{4})[\.-]\d\d[\.-]\d\d"),
    re.compile(r"S(?P<season>\d+)(E\d+)+"))


class Scanner(object):

    def __init__(self, torrent_entry, debug_scanner=False):
        self.torrent_entry = torrent_entry
        self.debug_scanner = debug_scanner

    def iter_media_items(self):
        if self.torrent_entry.container in ("VOB", "M2TS", "ISO"):
            return

        fis = []
        for fi in self.torrent_entry.file_info_cached:
            path = fi.path
            # Filter out files which don't seem to match the labeled container
            container = self.torrent_entry.container
            if container not in ("", "---"):
                _, ext = os.path.splitext(path)
                ext = os.fsencode(os.fsdecode(ext).lower())
                ext = {b".mpg": b".mpeg"}.get(ext) or ext
                if ext != b"." + container.lower().encode():
                    continue
            fis.append(fi)

        if not fis:
            return

        if self.torrent_entry.group.category == CATEGORY_EPISODE:
            m = BTN_EPISODE_REGEX.match(self.torrent_entry.group.name)
            if m:
                s = int(m.group("season"))
                episodes = m.group("episodes")
                episodes = [
                    int(e)
                    for e in BTN_EPISODE_PART_REGEX.findall(episodes)]
                if all(e != 0 for e in episodes):
                    for i, e in enumerate(episodes):
                        yield tvaf_btn.MediaItem(
                            self.torrent_entry, fis, episode=e, season=s,
                            exact_season=True, offset=i / len(episodes) * 100)
                    return
            m = BTN_DATE_EPISODE_REGEX.match(self.torrent_entry.group.name)
            if m:
                date = "%s-%s-%s" % (m.group("y"), m.group("m"), m.group("d"))
                yield tvaf_btn.MediaItem(self.torrent_entry, fis, date=date)
                return
            yield tvaf_btn.MediaItem(self.torrent_entry, fis)
            return

        if self.torrent_entry.group.category == CATEGORY_SEASON:
            known_strings = [
                self.torrent_entry.codec, self.torrent_entry.resolution,
                self.torrent_entry.source]

            if self.torrent_entry.resolution[-1] in ("i", "p"):
                known_strings.append(self.torrent_entry.resolution[:-1])

            if self.torrent_entry.source in (
                    "Bluray", "BD50", "BDRip", "BRRip"):
                known_strings.extend([
                    "blu-ray", "bluray", "blu ray", "blu_ray", "blu.ray",
                    "blue-ray", "blueray", "blue ray", "blue_ray",
                    "blue.ray"])
            if self.torrent_entry.source in ("WEB-DL", "WEBRip"):
                known_strings.append("WEB")

            for rx in BTN_SEASON_PARTIAL_REGEXES:
                m = rx.match(self.torrent_entry.group.name)
                if m:
                    season = int(m.group("season"))
                    break
            else:
                season = None

            exact_season = bool(BTN_FULL_SEASON_REGEX.match(
                self.torrent_entry.group.name))

            scanner = tvaf.scan.SeriesPathnameScanner(
                fis, known_season=season, known_strings=known_strings,
                debug=self.debug_scanner)

            for mi in scanner.iter_media_items():
                if season is not None and exact_season:
                    mi.details.season = season
                yield tvaf_btn.MediaItem(
                    self.torrent_entry, mi.parts, episode=mi.details.episode,
                    season=mi.details.season, date=mi.details.date,
                    filename=mi.details.filename, offset=mi.details.offset,
                    exact_season=exact_season)
