from argparse import ArgumentParser, Namespace
from collections import Counter
from os import environ
from ytmusicapi import OAuthCredentials, YTMusic, setup_oauth


ytmusic = YTMusic(
    auth={
        "scope": "https://www.googleapis.com/auth/youtube",
        "token_type": "Bearer",
        "access_token": environ["access_token"],
        "refresh_token": environ["refresh_token"],
        "expires_at": int(environ["expires_at"]),
        "expires_in": int(environ["expires_in"]),
    },
    oauth_credentials=OAuthCredentials(
        client_id=environ["client_id"], client_secret=environ["client_secret"]
    ),
)


def get_playlist_id(playlist_title):
    playlist_ids = [
        playlist["playlistId"]
        for playlist in ytmusic.get_library_playlists()
        if playlist["title"] == playlist_title
    ]
    if playlist_ids:
        return playlist_ids[0]


def delete_playlist(playlist_title):
    playlist_id = get_playlist_id(playlist_title)
    if playlist_id:
        ytmusic.delete_playlist(playlist_id)


def overwrite_playlist(playlist_title, tracks):
    delete_playlist(playlist_title)
    return ytmusic.create_playlist(
        playlist_title, "", "PUBLIC", [track["videoId"] for track in tracks]
    )


def rename_playlist(from_playlist_title, to_playlist_title):
    delete_playlist(to_playlist_title)
    playlist_id = get_playlist_id(from_playlist_title)
    ytmusic.edit_playlist(playlistId=playlist_id, title=to_playlist_title)


def get_tracks(playlist_title):
    playlist_id = get_playlist_id(playlist_title)
    return ytmusic.get_playlist(playlist_id, None)["tracks"]


def sort_playlist(target_playlist_title, archive_playlist_title, key):
    unsorted_tracks = get_tracks(target_playlist_title)
    sorted_tracks = sorted(unsorted_tracks, key=key)
    rename_playlist(target_playlist_title, archive_playlist_title)
    overwrite_playlist(target_playlist_title, sorted_tracks)


def get_duplicates(tracks):
    tracks = sorted([sanitize_track_title(track["title"]) for track in tracks])
    return [
        track_title
        for track_title, track_count in Counter(tracks).items()
        if track_count > 1
    ]
    # TODO: get more info about the duplicates


def get_tracks_longer_than(tracks, max_minutes):
    max_seconds = max_minutes * 60
    return [
        {
            "title": track["title"],
            "artists": ",".join([artist["name"] for artist in track["artists"]]),
            "duration": track["duration"],
        }
        for track in tracks
        if track["duration_seconds"] > max_seconds
    ]


def get_unliked_tracks(tracks):
    return [
        {
            "title": track["title"],
            "artists": ",".join([artist["name"] for artist in track["artists"]]),
            "likeStatus": track["likeStatus"],
        }
        for track in tracks
        if not track["likeStatus"] == "LIKE"
    ]


def get_unavailable_tracks(tracks):
    return [
        {
            "title": track["title"],
            "artists": ",".join([artist["name"] for artist in track["artists"]]),
        }
        for track in tracks
        if not track["isAvailable"]
    ]


def sanitize_track_title(track_title):
    return track_title.lower().split("(")[0].split("[")[0].strip()


def explicit_to_clean(
    explicit_playlist_title, clean_playlist_title, archive_playlist_title, key
):
    explicit_playlist_tracks = get_tracks(explicit_playlist_title)
    archive_playlist_tracks = get_tracks(clean_playlist_title)

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
            explicit_track["artists"][0]["name"] if explicit_track["artists"] else ""
        )
        result_tracks = ytmusic.search(
            f"{explicit_track['title']}{' ' if artist else ''}{artist}",
            "songs",
            None,
            10,
        )
        result_tracks = [
            result_track
            for result_track in result_tracks
            if not result_track["isExplicit"]
            and sanitize_track_title(result_track["title"])
            == sanitize_track_title(explicit_track["title"])
            # and result.get("album", {})["id"] == track.get("album", {})["id"]
            and (
                (result_track["artists"][0]["id"] if result_track["artists"] else "")
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
            uncleanable_tracks += [
                {
                    "title": explicit_track["title"],
                    "artists": ",".join(
                        [artist["name"] for artist in explicit_track["artists"]]
                    ),
                }
            ]

    clean_playlist_tracks = sorted(clean_playlist_tracks, key=key)

    rename_playlist(clean_playlist_title, archive_playlist_title)
    overwrite_playlist(clean_playlist_title, clean_playlist_tracks)

    archive_playlist_ids = {track["videoId"] for track in archive_playlist_tracks}
    clean_playlist_ids = {track["videoId"] for track in clean_playlist_tracks}
    added_tracks = [
        {
            "title": track["title"],
            "artists": ",".join([artist["name"] for artist in track["artists"]]),
        }
        for track in clean_playlist_tracks
        if track["videoId"] not in archive_playlist_ids
    ]
    removed_tracks = [
        {
            "title": track["title"],
            "artists": ",".join([artist["name"] for artist in track["artists"]]),
        }
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


def problems(args: Namespace):
    tracks = get_tracks(args.playlist_title)
    print(f"Duplicates\n{get_duplicates(tracks)}\n")
    print(
        f"Songs longer than {args.max_minutes} minutes\n{get_tracks_longer_than(tracks, args.max_minutes)}\n"
    )
    print(f"Unliked songs\n{get_unliked_tracks(tracks)}\n")
    print(f"Unavailable songs\n{get_unavailable_tracks(tracks)}\n")


def sort(args: Namespace):
    sort_playlist(
        args.target_playlist_title,
        args.archive_playlist_title,
        lambda track: track["title"].upper(),
    )


def clean(args: Namespace):
    uncleanable_tracks, added_tracks, removed_tracks = explicit_to_clean(
        args.explicit_playlist_title,
        args.clean_playlist_title,
        args.archive_playlist_title,
        lambda track: track["title"].upper(),
    )
    print(f"Added\n{added_tracks}\n")
    print(f"Removed\n{removed_tracks}\n")
    print(f"Uncleanable\n{uncleanable_tracks}\n")


if __name__ == "__main__":
    parser = ArgumentParser()
    subparsers = parser.add_subparsers()

    subparser = subparsers.add_parser("oauth")
    subparser.set_defaults(func=oauth)

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
