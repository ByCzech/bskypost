#!/usr/bin/python3
import argparse
import requests

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description='Send post to Bluesky social network', formatter_class=CustomHelpFormatter)
    parser.add_argument('-v', '--version', action='version',
                        version='bskypost 1.0')
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
