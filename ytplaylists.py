from argparse import ArgumentParser, Namespace
from collections import defaultdict
from json import load
from os import environ
from ytmusicapi import OAuthCredentials, YTMusic, setup_oauth
import requests
from typing import Literal

auth: Literal["browser", "oauth"] | None = None


class YTPlaylists:

    def __init__(self):
        match auth:
            case "browser":
                with open("browser.json", "r") as browser_file:
                    browser_json = load(browser_file)
                browser_json["authorization"] = environ["yt_music_authorization"]
                browser_json["cookie"] = environ["yt_music_cookie"]
                self.ytmusic = YTMusic(browser_json)
            case "oauth":
                self.ytmusic = YTMusic(
                    auth={
                        "scope": "https://www.googleapis.com/auth/youtube",
                        "token_type": "Bearer",
                        "access_token": environ["access_token"],
                        "refresh_token": environ["refresh_token"],
                    },
                    oauth_credentials=OAuthCredentials(
                        client_id=environ["client_id"],
                        client_secret=environ["client_secret"],
                    ),
                    # removes the 30 second timeout
                    requests_session=requests.Session(),
                )
            case _:
                self.ytmusic = YTMusic()

    @staticmethod
    def get_artists(track):
        return ", ".join([artist["name"] for artist in track["artists"]])

    @staticmethod
    def get_property(track, property):
        property_map = {"artists": YTPlaylists.get_artists}
        return property_map.get(property, lambda track: f"{track[property]}")(
            track
        ).replace("|", "\\|")

    @staticmethod
    def create_md_table(table_name, headers, records):
        title = f"### {table_name} ({len(records)})"
        header = "| " + " | ".join(headers) + " |"
        underline = "| " + " | ".join(["---" for _ in headers]) + " |"
        values = "\n".join(
            "| "
            + " | ".join(
                [YTPlaylists.get_property(record, property) for property in headers]
            )
            + " |"
            for record in records
        )
        return f"{title}\n{header}\n{underline}\n{values}"

    def get_playlist_id(self, playlist_title):
        playlist_ids = [
            playlist["playlistId"]
            for playlist in self.ytmusic.get_library_playlists()
            if playlist["title"] == playlist_title
        ]
        if playlist_ids:
            return playlist_ids[0]

    def delete_playlist(self, playlist_title):
        playlist_id = self.get_playlist_id(playlist_title)
        if playlist_id:
            self.ytmusic.delete_playlist(playlist_id)

    @DeprecationWarning
    def replace_playlist(self, playlist_title, tracks):
        self.delete_playlist(playlist_title)
        return self.ytmusic.create_playlist(
            playlist_title, "", "PUBLIC", [track["videoId"] for track in tracks]
        )

    def rename_playlist(self, from_playlist_title, to_playlist_title):
        self.delete_playlist(to_playlist_title)
        playlist_id = self.get_playlist_id(from_playlist_title)
        self.ytmusic.edit_playlist(playlistId=playlist_id, title=to_playlist_title)

    def clear_playlist(self, playlist_title):
        playlist_id = self.get_playlist_id(playlist_title)
        tracks = self.get_tracks(playlist_title)
        if playlist_id and tracks:
            self.ytmusic.remove_playlist_items(
                playlistId=playlist_id,
                videos=tracks,
            )

    def overwrite_playlist(self, target_playlist_title, archive_playlist_title, tracks):
        archive_playlist_id = self.get_playlist_id(archive_playlist_title)
        if archive_playlist_id:
            self.clear_playlist(archive_playlist_title)
        else:
            archive_playlist_id = self.ytmusic.create_playlist(
                archive_playlist_title, "", "PUBLIC", []
            )
        target_playlist_id = self.get_playlist_id(target_playlist_title)
        self.ytmusic.add_playlist_items(
            playlistId=archive_playlist_id, source_playlist=target_playlist_id
        )
        self.clear_playlist(target_playlist_title)
        self.ytmusic.add_playlist_items(
            playlistId=target_playlist_id,
            videoIds=[track["videoId"] for track in tracks],
        )

    def get_tracks(self, playlist_title):
        playlist_id = self.get_playlist_id(playlist_title)
        return self.ytmusic.get_playlist(playlist_id, None)["tracks"]

    def sort_playlist(self, target_playlist_title, archive_playlist_title, key):
        unsorted_tracks = self.get_tracks(target_playlist_title)
        sorted_tracks = sorted(unsorted_tracks, key=key)
        self.overwrite_playlist(
            target_playlist_title, archive_playlist_title, sorted_tracks
        )

    @staticmethod
    def get_unavailable_tracks(tracks):
        return [track for track in tracks if not track["isAvailable"]]

    @staticmethod
    def get_duplicates(tracks):
        sanitized_tracks = defaultdict(list)
        for track in tracks:
            sanitizedTitle = YTPlaylists.sanitize_track_title(track["title"])
            sanitized_tracks[sanitizedTitle].append(
                {"sanitizedTitle": sanitizedTitle} | track
            )
        return [
            track
            for _, track_list in sanitized_tracks.items()
            if len(track_list) > 1
            for track in track_list
        ]

    @staticmethod
    def get_tracks_longer_than(tracks, max_minutes):
        max_seconds = max_minutes * 60
        return [track for track in tracks if track["duration_seconds"] > max_seconds]

    @staticmethod
    def get_unliked_tracks(tracks):
        return [
            track
            for track in tracks
            if track["isAvailable"] and not track["likeStatus"] == "LIKE"
        ]

    @staticmethod
    def get_low_quality_tracks(tracks):
        return [
            track
            for track in tracks
            if track["isAvailable"] and track["videoType"] != "MUSIC_VIDEO_TYPE_ATV"
        ]

    @staticmethod
    def sanitize_track_title(track_title):
        return track_title.lower().split("(")[0].split("[")[0].strip()

    def explicit_to_clean(
        self,
        explicit_playlist_title,
        clean_playlist_title,
        archive_playlist_title,
        key,
    ):
        explicit_playlist_tracks = self.get_tracks(explicit_playlist_title)
        archive_playlist_tracks = self.get_tracks(clean_playlist_title)

        clean_tracks = [
            track for track in explicit_playlist_tracks if not track["isExplicit"]
        ]
        explicit_tracks = [
            track for track in explicit_playlist_tracks if track["isExplicit"]
        ]

        clean_playlist_tracks = clean_tracks
        uncleanable_tracks = []

        for explicit_track in explicit_tracks:
            # if track["title"] == "Empire State Of Mind (feat. Alicia Keys)":
            #     print ("ESM")
            artist = (
                explicit_track["artists"][0]["name"]
                if explicit_track["artists"]
                else ""
            )
            result_tracks = self.ytmusic.search(
                f"{explicit_track['title']}{' ' if artist else ''}{artist}",
                "songs",
                None,
                10,
            )
            result_tracks = [
                result_track
                for result_track in result_tracks
                if not result_track["isExplicit"]
                and self.sanitize_track_title(result_track["title"])
                == self.sanitize_track_title(explicit_track["title"])
                # and result.get("album", {})["id"] == track.get("album", {})["id"]
                and (
                    (
                        result_track["artists"][0]["id"]
                        if result_track["artists"]
                        else ""
                    )
                    == (
                        explicit_track["artists"][0]["id"]
                        if explicit_track["artists"]
                        else ""
                    )
                )
                and explicit_track["duration_seconds"]
                >= result_track["duration_seconds"] - 5
            ]
            if result_tracks:
                clean_playlist_tracks += [result_tracks[0]]
            else:
                uncleanable_tracks += [explicit_track]

        clean_playlist_tracks = sorted(clean_playlist_tracks, key=key)

        self.overwrite_playlist(
            clean_playlist_title, archive_playlist_title, clean_playlist_tracks
        )

        archive_playlist_ids = {track["videoId"] for track in archive_playlist_tracks}
        clean_playlist_ids = {track["videoId"] for track in clean_playlist_tracks}
        added_tracks = [
            track
            for track in clean_playlist_tracks
            if track["videoId"] not in archive_playlist_ids
        ]
        removed_tracks = [
            track
            for track in archive_playlist_tracks
            if track["videoId"] not in clean_playlist_ids
        ]
        return uncleanable_tracks, added_tracks, removed_tracks


def oauth(_: Namespace):
    setup_oauth(
        client_id=environ["client_id"],
        client_secret=environ["client_secret"],
        filepath="./oauth.json",
        open_browser=True,
    )


def compare(args: Namespace):
    yt_playlists = YTPlaylists()
    tracks_1 = yt_playlists.get_tracks(args.playlist_title_1)
    print(f"Size of {args.playlist_title_1}: {len(tracks_1)}")
    track_ids_1 = {track["videoId"] for track in tracks_1}
    tracks_2 = yt_playlists.get_tracks(args.playlist_title_2)
    print(f"Size of {args.playlist_title_2}: {len(tracks_2)}")
    track_ids_2 = {track["videoId"] for track in tracks_2}
    print(
        yt_playlists.create_md_table(
            f"Tracks in {args.playlist_title_1} but not in {args.playlist_title_2}",
            ("title", "artists"),
            [track for track in tracks_1 if track["videoId"] not in track_ids_2],
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            f"Tracks in {args.playlist_title_2} but not in {args.playlist_title_1}",
            ("title", "artists"),
            [track for track in tracks_2 if track["videoId"] not in track_ids_1],
        )
        + "\n"
    )


def problems(args: Namespace):
    yt_playlists = YTPlaylists()
    tracks = yt_playlists.get_tracks(args.playlist_title)
    print(
        yt_playlists.create_md_table(
            "Unavailable songs",
            ("title", "artists"),
            yt_playlists.get_unavailable_tracks(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Duplicates",
            ("sanitizedTitle", "title", "artists"),
            yt_playlists.get_duplicates(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            f"Songs longer than {args.max_minutes} minutes",
            ("title", "artists", "duration"),
            yt_playlists.get_tracks_longer_than(tracks, args.max_minutes),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Unliked songs",
            ("title", "artists", "likeStatus"),
            yt_playlists.get_unliked_tracks(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Low-quality",
            ("title", "artists", "videoType"),
            yt_playlists.get_low_quality_tracks(tracks),
        )
        + "\n"
    )


def sort(args: Namespace):
    yt_playlists = YTPlaylists()
    yt_playlists.sort_playlist(
        args.target_playlist_title,
        args.archive_playlist_title,
        lambda track: track["title"].upper(),
    )


def clean(args: Namespace):
    yt_playlists = YTPlaylists()
    uncleanable_tracks, added_tracks, removed_tracks = yt_playlists.explicit_to_clean(
        args.explicit_playlist_title,
        args.clean_playlist_title,
        args.archive_playlist_title,
        lambda track: track["title"].upper(),
    )
    print(
        yt_playlists.create_md_table(
            "Added",
            ("title", "artists"),
            added_tracks,
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Removed",
            ("title", "artists"),
            removed_tracks,
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Uncleanable",
            ("title", "artists"),
            uncleanable_tracks,
        )
        + "\n"
    )


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    subparser = subparsers.add_parser("oauth")
    subparser.set_defaults(func=oauth)

    subparser = subparsers.add_parser("compare")
    subparser.add_argument("playlist_title_1", type=str)
    subparser.add_argument("playlist_title_2", type=str)
    subparser.set_defaults(func=compare)

    subparser = subparsers.add_parser("problems")
    subparser.add_argument("playlist_title", type=str)
    subparser.add_argument("max_minutes", type=int)
    subparser.set_defaults(func=problems)

    subparser = subparsers.add_parser("sort")
    subparser.add_argument("target_playlist_title", type=str)
    subparser.add_argument("archive_playlist_title", type=str)
    subparser.set_defaults(func=sort)

    subparser = subparsers.add_parser("clean")
    subparser.add_argument("explicit_playlist_title", type=str)
    subparser.add_argument("clean_playlist_title", type=str)
    subparser.add_argument("archive_playlist_title", type=str)
    subparser.set_defaults(func=clean)

    args = parser.parse_args()
    args.func(args)


# TODO: add unit tests especially to make sure exceptions work
