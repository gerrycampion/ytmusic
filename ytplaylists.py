from collections import Counter
from ytmusicapi import YTMusic


ytmusic = YTMusic("oauth.json")


def add_individually(playlist_id, tracks):
    for track in tracks:
        status = ytmusic.add_playlist_items(playlist_id, [track["videoId"]])
        if status["status"] != "STATUS_SUCCEEDED":
            print(status)
            print(track["title"])


def add_bulk(playlist_id, tracks):
    status = ytmusic.add_playlist_items(
        playlist_id, [track["videoId"] for track in tracks]
    )
    if status["status"] != "STATUS_SUCCEEDED":
        print(status)


def delete_playlist(title):
    playlist = [
        playlist["playlistId"]
        for playlist in ytmusic.get_library_playlists()
        if playlist["title"] == title
    ]
    if playlist:
        ytmusic.delete_playlist(playlist[0])


def overwrite_playlist(title, tracks):
    delete_playlist(title)
    return ytmusic.create_playlist(
        title, "", "PUBLIC", [track["videoId"] for track in tracks]
    )


def get_tracks(title):
    playlist = [
        playlist
        for playlist in ytmusic.get_library_playlists()
        if playlist["title"] == title
    ][0]
    return ytmusic.get_playlist(playlist["playlistId"], int(playlist["count"]))[
        "tracks"
    ]


def dirty_to_clean(dirty_title, clean_title, key):
    dirty_playlist_songs = get_tracks(dirty_title)

    clean_tracks = [track for track in dirty_playlist_songs if not track["isExplicit"]]
    dirty_tracks = [track for track in dirty_playlist_songs if track["isExplicit"]]

    tracks = clean_tracks
    uncleanables = []

    for track in dirty_tracks:
        # if track["title"] == "Empire State Of Mind (feat. Alicia Keys)":
        #     print ("ESM")
        artist = track["artists"][0]["name"] if track["artists"] else ""
        results = ytmusic.search(
            f"{track['title']}{' ' if artist else ''}{artist}", "songs", None, 10
        )
        results = [
            result
            for result in results
            if not result["isExplicit"]
            and normalize_title(result["title"]) == normalize_title(track["title"])
            # and result.get("album", {})["id"] == track.get("album", {})["id"]
            and (
                (result["artists"][0]["id"] if result["artists"] else "")
                == (track["artists"][0]["id"] if track["artists"] else "")
            )
            and track["duration_seconds"] >= result["duration_seconds"] - 5
        ]
        if results:
            tracks += [results[0]]
        else:
            uncleanable = f"{track['title']} - {artist}"
            print(uncleanable)
            uncleanables += [uncleanable]

    tracks = sorted(tracks, key=key)

    overwrite_playlist(clean_title, tracks)

    with open("./uncleanable.txt", "w+") as fp:
        for track in uncleanables:
            fp.write(f"{track}\n")

    return uncleanables


def sort_playlist(unsorted_title, sorted_title, key):
    unsorted_tracks = get_tracks(unsorted_title)
    sorted_tracks = sorted(unsorted_tracks, key=key)
    overwrite_playlist(sorted_title, sorted_tracks)


def get_duplicates(title):
    tracks = get_tracks(title)
    tracks = sorted([normalize_title(track["title"]) for track in tracks])
    return [title for title, count in Counter(tracks).items() if count > 1]


def normalize_title(title):
    return title.lower().split("(")[0].split("[")[0].strip()


# print(get_duplicates("Volleyball Dirty"))

# sort_playlist(
#     "Volleyball Dirty", "Volleyball Dirty Sorted", lambda track: track["title"].upper()
# )

# dirty_to_clean(
#     "Volleyball Dirty", "Volleyball Clean", lambda track: track["title"].upper()
# )




# addIndividually(cleanPlaylist["playlistId"], cleanTracks)
# add_bulk(clean_playlist["playlistId"], clean_tracks)
