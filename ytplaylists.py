from argparse import ArgumentParser, Namespace
from collections import defaultdict
from json import load
from os import environ
from ytmusicapi import OAuthCredentials, YTMusic, setup_oauth
import requests
from typing import Literal
from google.oauth2.credentials import Credentials
from googleapiclient import discovery
from google_auth_oauthlib.flow import InstalledAppFlow


AUTH: Literal["browser", "oauth"] | None = None
MAX_RESULTS = 50
SCOPES = ["https://www.googleapis.com/auth/youtube"]


class YTPlaylists:

    def __init__(self):
        credentials = Credentials.from_authorized_user_info(
            eval(environ["youtube_token"]), SCOPES
        )
        self.youtube = discovery.build("youtube", "v3", credentials=credentials)

        match AUTH:
            case "browser":
                with open("browser.json", "r") as browser_file:
                    browser_json = load(browser_file)
                browser_json["authorization"] = environ["yt_music_authorization"]
                browser_json["cookie"] = environ["yt_music_cookie"]
                self.ytmusic = YTMusic(browser_json)
            case "oauth":
                self.ytmusic = YTMusic(
                    auth={
                        "scope": SCOPES[0],
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
    def fetch_all(method, **kwargs):
        all_items = []
        next_page_token = None
        while True:
            results = method(
                maxResults=MAX_RESULTS,
                pageToken=next_page_token,
                **kwargs,
            ).execute()
            all_items.extend(results["items"])
            next_page_token = results.get("nextPageToken")
            if not next_page_token:
                return all_items

    @staticmethod
    def create_md_table(table_name, headers, records):
        title = f"### {table_name} ({len(records)})"
        header = "| " + " | ".join(headers) + " |"
        underline = "| " + " | ".join(["---" for _ in headers]) + " |"
        values = "\n".join(
            "| "
            + " | ".join([record[property].replace("|", "\\|") for property in headers])
            + " |"
            for record in records
        )
        return f"{title}\n{header}\n{underline}\n{values}"

    def get_playlist_id(self, playlist_title):
        playlists = self.fetch_all(
            self.youtube.playlists().list,
            part="contentDetails,id,snippet,status",
            mine=True,
        )
        playlist_title_id = {
            playlist["snippet"]["title"]: playlist["id"] for playlist in playlists
        }
        return playlist_title_id.get(playlist_title)

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
        if not playlist_id:
            return

        # Get all playlist items using YouTube API
        playlist_items = self.fetch_all(
            self.youtube.playlistItems().list,
            playlistId=playlist_id,
            part="id",
        )

        # Delete each item
        for item in playlist_items:
            self.youtube.playlistItems().delete(id=item["id"]).execute()

    def overwrite_playlist(self, target_playlist_title, archive_playlist_title, tracks):
        archive_playlist_id = self.get_playlist_id(archive_playlist_title)
        if archive_playlist_id:
            self.clear_playlist(archive_playlist_title)
        else:
            # Create archive playlist using YouTube API
            response = (
                self.youtube.playlists()
                .insert(
                    part="snippet,status",
                    body={
                        "snippet": {
                            "title": archive_playlist_title,
                            "description": "",
                        },
                        "status": {"privacyStatus": "public"},
                    },
                )
                .execute()
            )
            archive_playlist_id = response["id"]

        target_playlist_id = self.get_playlist_id(target_playlist_title)

        # Copy all items from target to archive using YouTube API
        target_items = self.fetch_all(
            self.youtube.playlistItems().list,
            playlistId=target_playlist_id,
            part="snippet",
        )
        for item in target_items:
            self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": archive_playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": item["snippet"]["resourceId"]["videoId"],
                        },
                    }
                },
            ).execute()

        # Clear target playlist
        self.clear_playlist(target_playlist_title)

        # Add sorted tracks to target playlist using YouTube API
        for track in tracks:
            self.youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": target_playlist_id,
                        "resourceId": {
                            "kind": "youtube#video",
                            "videoId": track["videoId"],
                        },
                    }
                },
            ).execute()

    @staticmethod
    def get_track_details(track):
        title = track["youtube"].get("snippet", {}).get("title", "") or track[
            "ytmusic"
        ].get("title", "")
        details = {
            "title": title,
            "titleLink": f"[{title}](https://www.youtube.com/watch?v={track['videoId']})",
            "album": (track["ytmusic"].get("album") or {}).get("name", ""),
            "artists": track["ytmusic"].get("artists", []),
            "artistNames": ", ".join(
                [artist["name"] for artist in track["ytmusic"].get("artists", [])]
            ),
            "duration": track["ytmusic"].get("duration"),
            "duration_seconds": track["ytmusic"].get("duration_seconds", 0),
            "historicalLink": f"[{track['videoId']}](https://quiteaplaylist.com/search?url=https://www.youtube.com/watch?v={track['videoId']})",
            "isAvailable": track["ytmusic"].get("isAvailable", None),
            "isExplicit": track["ytmusic"].get("isExplicit", None),
            "likeStatus": track.get("rating", {}).get("rating"),
            "privacyStatus": track["youtube"]
            .get("status", {})
            .get("privacyStatus", ""),
            "videoType": track["ytmusic"].get("videoType"),
        }
        return details

    def get_tracks(self, playlist_title):
        playlist_id = self.get_playlist_id(playlist_title)
        tracks_from_ytmusic = self.ytmusic.get_playlist(playlist_id, None)["tracks"]
        tracks_from_youtube = self.fetch_all(
            self.youtube.playlistItems().list,
            playlistId=playlist_id,
            part="contentDetails,id,snippet,status",
        )
        videos_details = []
        videos_ratings = []
        all_video_ids = list(
            {
                videoId: None
                for videoId in [
                    track["contentDetails"]["videoId"] for track in tracks_from_youtube
                ]
                + [track["videoId"] or track["title"] for track in tracks_from_ytmusic]
            }.keys()
        )
        for i in range(0, len(all_video_ids), MAX_RESULTS):
            video_ids_str = ",".join(all_video_ids[i : i + MAX_RESULTS])
            videos_chunk = (
                self.youtube.videos()
                .list(
                    part="contentDetails,id,liveStreamingDetails,paidProductPlacementDetails,recordingDetails,snippet,statistics,status,topicDetails",
                    id=video_ids_str,
                    hl="en",
                )
                .execute()["items"]
            )
            videos_details.extend(videos_chunk)
            videos_chunk = (
                self.youtube.videos()
                .getRating(
                    id=video_ids_str,
                )
                .execute()["items"]
            )
            videos_ratings.extend(videos_chunk)
        youtube_dict = {
            track["contentDetails"]["videoId"]: track for track in tracks_from_youtube
        }
        video_details_dict = {track["id"]: track for track in videos_details}
        video_ratings_dict = {track["videoId"]: track for track in videos_ratings}
        ytmusic_dict = {track["videoId"]: track for track in tracks_from_ytmusic}

        # Save original playlist memberships before enrichment
        youtube_ids = set(youtube_dict.keys())
        ytmusic_ids = set(ytmusic_dict.keys())

        # Enrich ytmusic data for tracks only in YouTube
        for video_id in youtube_ids - ytmusic_ids:
            ytmusic_dict[video_id] = self.ytmusic.get_song(video_id)

        # Build tracks with categorization (use lists to handle duplicates)
        youtube_only = []
        ytmusic_only = []
        result = []

        for videoId in all_video_ids:
            track = {
                "videoId": videoId,
                "youtube": youtube_dict.get(videoId, {}),
                "details": video_details_dict.get(videoId, {}),
                "rating": video_ratings_dict.get(videoId, {}),
                "ytmusic": ytmusic_dict.get(videoId, {}),
            }
            track.update(YTPlaylists.get_track_details(track))

            in_youtube = videoId in youtube_ids
            in_ytmusic = videoId in ytmusic_ids

            if in_youtube and in_ytmusic:
                result.append(track)
            elif in_youtube:
                youtube_only.append(track)
            elif in_ytmusic:
                ytmusic_only.append(track)

        # Match and combine tracks by sanitized title
        ytmusic_remaining = ytmusic_only.copy()

        for yt_track in youtube_only:
            yt_sanitized = YTPlaylists.sanitize_track_title(yt_track["title"])

            # Find matching ytmusic track
            matched_ytm = None
            for ytm_track in ytmusic_remaining:
                ytm_sanitized = YTPlaylists.sanitize_track_title(ytm_track["title"])
                if yt_sanitized == ytm_sanitized:
                    matched_ytm = ytm_track
                    ytmusic_remaining.remove(ytm_track)
                    break

            if matched_ytm:
                # Combine the tracks
                combined = {
                    "videoId": matched_ytm["videoId"],
                    "youtube": yt_track["youtube"],
                    "details": yt_track["details"],
                    "rating": yt_track["rating"],
                    "ytmusic": matched_ytm["ytmusic"],
                }
                combined.update(YTPlaylists.get_track_details(combined))
                combined["historicalLink"] = (
                    f"[{yt_track['videoId']}](https://quiteaplaylist.com/search?url=https://www.youtube.com/watch?v={yt_track['videoId']})"
                )
                result.append(combined)
            else:
                # No match, keep original but remove clickable link
                yt_track["titleLink"] = yt_track["title"]
                result.append(yt_track)

        # Add remaining unmatched ytmusic tracks
        result.extend(ytmusic_remaining)

        # Sort by title
        result.sort(key=lambda t: t["title"].lower())

        return result

    def sort_playlist(self, target_playlist_title, archive_playlist_title, key):
        unsorted_tracks = self.get_tracks(target_playlist_title)
        sorted_tracks = sorted(unsorted_tracks, key=key)
        self.overwrite_playlist(
            target_playlist_title, archive_playlist_title, sorted_tracks
        )

    @staticmethod
    def get_unavailable_tracks(tracks):
        return [
            track
            for track in tracks
            if track["privacyStatus"] != "public"
            or not track["isAvailable"]
            or not track["ytmusic"]
            or not track["youtube"]
        ]

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
            if track["isAvailable"] and not track["likeStatus"] == "like"
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

    def replace_with_ytmusic(self, playlist_title):
        """
        Replace YouTube songs with their YouTube Music equivalents.
        For matched songs, removes YouTube version and inserts
        YouTube Music version at the same position.

        Returns: replaced_tracks list
        """
        playlist_id = self.get_playlist_id(playlist_title)
        if not playlist_id:
            return []

        # Get current playlist items with positions
        playlist_items = self.fetch_all(
            self.youtube.playlistItems().list,
            playlistId=playlist_id,
            part="contentDetails,id,snippet",
        )

        # Create a mapping of videoId to playlist item ID and position
        youtube_item_map = {
            item["contentDetails"]["videoId"]: {"id": item["id"], "position": idx}
            for idx, item in enumerate(playlist_items)
        }

        # Get all tracks with matching information
        tracks = self.get_tracks(playlist_title)

        # Find tracks to replace
        tracks_to_replace = []
        for track in tracks:
            # Get the YouTube video ID that's currently in the playlist
            youtube_video_id = (
                track.get("youtube", {}).get("contentDetails", {}).get("videoId")
            )

            # Get the YouTube Music video ID
            ytmusic_video_id = track.get("ytmusic", {}).get("videoId")

            # Check if track is in YouTube playlist with different
            # YTMusic version
            if (
                youtube_video_id
                and ytmusic_video_id
                and youtube_video_id != ytmusic_video_id
                and youtube_video_id in youtube_item_map
            ):

                tracks_to_replace.append(
                    {
                        "track": track,
                        "youtube_video_id": youtube_video_id,
                        "ytmusic_video_id": ytmusic_video_id,
                        "position": youtube_item_map[youtube_video_id]["position"],
                        "playlist_item_id": (youtube_item_map[youtube_video_id]["id"]),
                    }
                )

        # Sort by position in reverse order to avoid position shifts
        tracks_to_replace.sort(key=lambda x: x["position"], reverse=True)

        # Perform the replacements
        replaced_tracks = []
        for item in tracks_to_replace:
            try:
                # Delete the YouTube version
                self.youtube.playlistItems().delete(
                    id=item["playlist_item_id"]
                ).execute()

                # Insert the YouTube Music version at the same position
                self.youtube.playlistItems().insert(
                    part="snippet",
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "position": item["position"],
                            "resourceId": {
                                "kind": "youtube#video",
                                "videoId": item["ytmusic_video_id"],
                            },
                        }
                    },
                ).execute()

                replaced_tracks.append(item["track"])

            except Exception as e:
                title = item["track"]["title"]
                print(f"Error replacing {title}: {str(e)}")

        return replaced_tracks


def ytmusic_oauth(_: Namespace):
    setup_oauth(
        client_id=environ["client_id"],
        client_secret=environ["client_secret"],
        filepath="./oauth.json",
        open_browser=True,
    )


def ytmusic_browser(_: Namespace):
    pass  # TODO


def youtube_oauth(_: Namespace):
    # Disable OAuthlib's HTTPS verification when running locally.
    # *DO NOT* leave this option enabled in production.
    environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
    credentials = InstalledAppFlow.from_client_secrets_file(
        environ["youtube_client_secrets_file"], SCOPES
    ).run_local_server()
    with open("token.json", "w") as token:
        # TODO: write this to env file instead?
        token.write(credentials.to_json())


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
            ("titleLink", "artistNames"),
            [track for track in tracks_1 if track["videoId"] not in track_ids_2],
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            f"Tracks in {args.playlist_title_2} but not in {args.playlist_title_1}",
            ("titleLink", "artistNames"),
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
            ("titleLink", "artistNames", "album", "privacyStatus", "historicalLink"),
            yt_playlists.get_unavailable_tracks(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Duplicates",
            ("sanitizedTitle", "titleLink", "artistNames", "album"),
            yt_playlists.get_duplicates(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            f"Songs longer than {args.max_minutes} minutes",
            ("titleLink", "artistNames", "duration"),
            yt_playlists.get_tracks_longer_than(tracks, args.max_minutes),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Unliked songs",
            ("titleLink", "artistNames", "likeStatus"),
            yt_playlists.get_unliked_tracks(tracks),
        )
        + "\n"
    )
    print(
        yt_playlists.create_md_table(
            "Low-quality",
            ("titleLink", "artistNames", "videoType"),
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


def replace_with_ytmusic(args: Namespace):
    yt_playlists = YTPlaylists()
    replaced_tracks = yt_playlists.replace_with_ytmusic(args.playlist_title)

    if replaced_tracks:
        print(
            yt_playlists.create_md_table(
                "Replaced YouTube tracks with YouTube Music versions",
                (
                    "titleLink",
                    "artistNames",
                    "album",
                    "privacyStatus",
                    "historicalLink",
                ),
                replaced_tracks,
            )
            + "\n"
        )
        print(f"Total tracks replaced: {len(replaced_tracks)}")
    else:
        print("No tracks were replaced.")


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    subparser = subparsers.add_parser("ytmusic_oauth")
    subparser.set_defaults(func=ytmusic_oauth)

    subparser = subparsers.add_parser("ytmusic_browser")
    subparser.set_defaults(func=ytmusic_browser)

    subparser = subparsers.add_parser("youtube_oauth")
    subparser.set_defaults(func=youtube_oauth)

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

    subparser = subparsers.add_parser("replace_with_ytmusic")
    subparser.add_argument("playlist_title", type=str)
    subparser.set_defaults(func=replace_with_ytmusic)

    args = parser.parse_args()
    args.func(args)


# TODO: add unit tests especially to make sure exceptions work
