# -*- coding: utf-8 -*-

# Copyright 2024 Mike Fährmann
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License version 2 as
# published by the Free Software Foundation.

"""Extractors for https://cohost.org/"""

from .common import Extractor, Message
from .. import text, util

BASE_PATTERN = r"(?:https?://)?(?:www\.)?cohost\.org"


class CohostExtractor(Extractor):
    """Base class for cohost extractors"""
    category = "cohost"
    root = "https://cohost.org"
    directory_fmt = ("{category}", "{postingProject[handle]}")
    filename_fmt = ("{postId}_{headline|plainTextBody:?/_/[:100]}"
                    "{num}.{extension}")
    archive_fmt = "{postId}_{num}"

    def _init(self):
        self.replies = self.config("replies", True)
        self.pinned = self.config("pinned", False)
        self.shares = self.config("shares", False)
        self.asks = self.config("asks", True)

    def items(self):
        for post in self.posts():
            files = self._extract_files(post)
            post["count"] = len(files)
            post["date"] = text.parse_datetime(
                post["publishedAt"], "%Y-%m-%dT%H:%M:%S.%fZ")

            yield Message.Directory, post
            for post["num"], file in enumerate(files, 1):
                url = file["fileURL"]
                post.update(file)
                text.nameext_from_url(url, post)
                yield Message.Url, url, post

    def posts(self):
        return ()

    def _request_api(self, endpoint, input):
        url = "{}/api/v1/trpc/{}".format(self.root, endpoint)
        params = {"batch": "1", "input": util.json_dumps({"0": input})}
        headers = {"content-type": "application/json"}

        data = self.request(url, params=params, headers=headers).json()
        return data[0]["result"]["data"]

    def _extract_files(self, post):
        files = []

        self._extract_blocks(post, files)
        if self.shares and post.get("shareTree"):
            for share in post["shareTree"]:
                self._extract_blocks(share, files, share)
            del post["shareTree"]

        return files

    def _extract_blocks(self, post, files, shared=None):
        post["content"] = content = []

        for block in post.pop("blocks") or ():
            try:
                type = block["type"]
                if type == "attachment":
                    file = block["attachment"].copy()
                    file["shared"] = shared
                    files.append(file)
                elif type == "markdown":
                    content.append(block["markdown"]["content"])
                elif type == "ask":
                    post["ask"] = block["ask"]
                else:
                    self.log.debug("%s: Unsupported block type '%s'",
                                   post["postId"], type)
            except Exception as exc:
                self.log.debug("%s: %s", exc.__class__.__name__, exc)


class CohostUserExtractor(CohostExtractor):
    """Extractor for media from a cohost user"""
    subcategory = "user"
    pattern = BASE_PATTERN + r"/([^/?#]+)/?(?:$|\?|#)"
    example = "https://cohost.org/USER"

    def posts(self):
        empty = 0
        params = {
            "projectHandle": self.groups[0],
            "page": 0,
            "options": {
                "pinnedPostsAtTop"    : bool(self.pinned),
                "hideReplies"         : not self.replies,
                "hideShares"          : not self.shares,
                "hideAsks"            : not self.asks,
                "viewingOnProjectPage": True,
            },
        }

        while True:
            data = self._request_api("posts.profilePosts", params)

            posts = data["posts"]
            if posts:
                empty = 0
                yield from posts
            else:
                empty += 1

            pagination = data["pagination"]
            if not pagination.get("morePagesForward"):
                return
            if empty >= 3:
                return self.log.debug("Empty API results")
            params["page"] = pagination["nextPage"]


class CohostPostExtractor(CohostExtractor):
    """Extractor for media from a single cohost post"""
    subcategory = "post"
    pattern = BASE_PATTERN + r"/([^/?#]+)/post/(\d+)"
    example = "https://cohost.org/USER/post/12345"

    def posts(self):
        endpoint = "posts.singlePost"
        params = {
            "handle": self.groups[0],
            "postId": int(self.groups[1]),
        }

        data = self._request_api(endpoint, params)
        post = data["post"]

        try:
            post["comments"] = data["comments"][self.groups[1]]
        except LookupError:
            post["comments"] = ()

        return (post,)
