#!/usr/bin/python3
import argparse
import requests
import re
import magic

try:
    import ujson as json
except (ImportError, SyntaxError):
    try:
        import simplejson as json
    except (ImportError, SyntaxError):
        import json

from argparse import HelpFormatter
from functools import partial

from datetime import datetime, timezone
from typing import List, Dict


class CustomHelpFormatter(HelpFormatter):

    def _format_action_invocation(self, action):
        if not action.option_strings:
            # Use default methods for positional arguments
            default = self._get_default_metavar_for_positional(action)
            metavar, = self._metavar_formatter(action, default)(1)
            return metavar

        else:
            parts = []
            if action.nargs == 0:
                # Just add options, if they expects no values (like --help)
                parts.extend(action.option_strings)
            else:
                default = self._get_default_metavar_for_optional(action)
                args_string = self._format_args(action, default)
                for option_string in action.option_strings:
                    parts.append(option_string)
                # Join the argument names (like -p --param ) and add the metavar at the end
                return '%s %s' % (', '.join(parts), args_string)

            return ', '.join(parts)


"""
With the custom formatter the metavar does not get displayed twice.
With the max_help_position you can decide how long the parameters + metavar should be before a line break gets inserted,
additionally the width parameter defines the maximum length of a line.
The difference can be seen here:
https://github.com/alex1701c/Screenshots/blob/master/PythonArgparseCLI/default_output.png
https://github.com/alex1701c/Screenshots/blob/master/PythonArgparseCLI/customized_output_format.png
"""


def parse_mentions(text: str) -> List[Dict]:
    spans = []
    # regex based on: https://atproto.com/specs/handle#handle-identifier-syntax
    mention_regex = rb"[$|\W](@([a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(mention_regex, text_bytes):
        spans.append({
            "start": m.start(1),
            "end": m.end(1),
            "handle": m.group(1)[1:].decode("UTF-8")
        })
    return spans


def parse_urls(text: str) -> List[Dict]:
    spans = []
    # partial/naive URL regex based on: https://stackoverflow.com/a/3809435
    # tweaked to disallow some training punctuation
    url_regex = rb"[$|\W](https?:\/\/(www\.)?[-a-zA-Z0-9@:%._\+~#=]{1,256}\.[a-zA-Z0-9()]{1,6}\b([-a-zA-Z0-9()@:%_\+.~#?&//=]*[-a-zA-Z0-9@%_\+~#//=])?)"
    text_bytes = text.encode("UTF-8")
    for m in re.finditer(url_regex, text_bytes):
        spans.append({
            "start": m.start(1),
            "end": m.end(1),
            "url": m.group(1).decode("UTF-8"),
        })
    return spans

# Parse facets from text and resolve the handles to DIDs


def parse_facets(text: str) -> List[Dict]:
    facets = []
    for m in parse_mentions(text):
        resp = requests.get(
            "https://bsky.social/xrpc/com.atproto.identity.resolveHandle",
            params={"handle": m["handle"]},
        )
        # If the handle can't be resolved, just skip it!
        # It will be rendered as text in the post instead of a link
        if resp.status_code == 400:
            continue
        did = resp.json()["did"]
        facets.append({
            "index": {
                "byteStart": m["start"],
                "byteEnd": m["end"],
            },
            "features": [{"$type": "app.bsky.richtext.facet#mention", "did": did}],
        })
    for u in parse_urls(text):
        facets.append({
            "index": {
                "byteStart": u["start"],
                "byteEnd": u["end"],
            },
            "features": [
                {
                    "$type": "app.bsky.richtext.facet#link",
                    # NOTE: URI ("I") not URL ("L")
                    "uri": u["url"],
                }
            ],
        })
    return facets


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Send post to Bluesky social network', formatter_class=CustomHelpFormatter)
    parser.add_argument('-v', '--version', action='version',
                        version='bskypost 1.2')
    parser.add_argument('-i', '--image', metavar='<image>', action='append',
                        help='Path to image to be embed into post (arg can be used multiple times)')
    parser.add_argument('-a', '--alt', metavar='<image_alt>', action='append',
                        help='Alternate text for embeded image into post (arg can be used multiple times)')
    parser.add_argument('bsky_handle', metavar='<bsky_handle>',
                        help='Bluesky handle')
    parser.add_argument('app_password', metavar='<app_password>',
                        help='Bluesky app password')
    parser.add_argument('post_text', metavar='<post_text>', help='Post text')
    args = parser.parse_args()

    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.server.createSession",
        json={"identifier": args.bsky_handle, "password": args.app_password},
    )
    resp.raise_for_status()
    session = resp.json()
    # print(session["accessJwt"])

    post = {
        "$type": "app.bsky.feed.post",
        "text": args.post_text,
        "createdAt": now,
    }

    post["facets"] = parse_facets(post["text"])

    if args.image:
        post["embed"] = {
            "$type": "app.bsky.embed.images",
            "images": []
        }

        for idx, img in enumerate(args.image):
            with open(img, 'rb') as f:
                img_bytes = f.read()

            # this size limit is specified in the app.bsky.embed.images lexicon
            if len(img_bytes) > 1000000:
                raise Exception(
                    f"image file {img} size is too large. 1000000 bytes maximum, got: {len(img_bytes)}"
                )

            # TODO: strip EXIF metadata here, if needed

            resp = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                headers={
                    "Content-Type": magic.from_buffer(img_bytes, mime=True),
                    "Authorization": "Bearer " + session["accessJwt"],
                },
                data=img_bytes,
            )
            resp.raise_for_status()
            blob = resp.json()["blob"]

            post["embed"]["images"].append({
                'alt': args.alt[idx] if len(args.alt) > idx else "",
                'image': blob
            })

    resp = requests.post(
        "https://bsky.social/xrpc/com.atproto.repo.createRecord",
        headers={"Authorization": "Bearer " + session["accessJwt"]},
        json={
            "repo": session["did"],
            "collection": "app.bsky.feed.post",
            "record": post,
        },
    )
    print(json.dumps(resp.json(), indent=2))
    resp.raise_for_status()
