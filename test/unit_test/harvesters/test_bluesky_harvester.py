# COMP90024 Team 2

from types import SimpleNamespace

from backend.harvesters import bluesky_harvester


def test_bluesky_post_to_dict_marks_replies_and_builds_url():
    record = SimpleNamespace(
        text="Umbrella weather",
        langs=["en"],
        created_at="2024-01-01T00:00:00Z",
        reply=SimpleNamespace(
            parent=SimpleNamespace(uri="at://did:example/alice/app.bsky.feed.post/parent"),
            root=SimpleNamespace(uri="at://did:example/alice/app.bsky.feed.post/root"),
        ),
    )
    post = SimpleNamespace(
        uri="at://did:example/alice/app.bsky.feed.post/abc123",
        cid="cid123",
        author=SimpleNamespace(handle="alice.bsky.social", did="did:example:alice"),
        record=record,
        reply_count=1,
        repost_count=2,
        like_count=3,
    )

    rec = bluesky_harvester.post_to_dict(post, "sydney", "Sydney weather")

    assert rec["kind"] == "reply"
    assert rec["id"] == post.uri
    assert rec["author_handle"] == "alice.bsky.social"
    assert rec["lang"] == ["en"]
    assert rec["parent_post_id"] == "at://did:example/alice/app.bsky.feed.post/parent"
    assert rec["root_post_id"] == "at://did:example/alice/app.bsky.feed.post/root"
    assert rec["url"] == "https://bsky.app/profile/alice.bsky.social/post/abc123"


def test_bluesky_post_to_dict_handles_posts_without_reply_metadata():
    record = SimpleNamespace(
        text="Sunny weather",
        langs=None,
        created_at="2024-01-01T00:00:00Z",
    )
    post = SimpleNamespace(
        uri="at://did:example/alice/app.bsky.feed.post/root",
        cid="cid-root",
        author=SimpleNamespace(handle="alice.bsky.social", did="did:example:alice"),
        record=record,
        reply_count=0,
        repost_count=2,
        like_count=3,
    )

    rec = bluesky_harvester.post_to_dict(post, "melbourne", "Melbourne weather")

    assert rec["kind"] == "post"
    assert rec["text"] == "Sunny weather"
    assert rec["lang"] == []
    assert rec["parent_post_id"] is None
    assert rec["root_post_id"] is None
    assert rec["url"] == "https://bsky.app/profile/alice.bsky.social/post/root"


def test_bluesky_iter_thread_replies_walks_thread_view_posts_only():
    valid_grandchild = SimpleNamespace(
        py_type="app.bsky.feed.defs#threadViewPost",
        replies=[],
        post=SimpleNamespace(uri="grandchild"),
    )
    valid_child = SimpleNamespace(
        py_type="app.bsky.feed.defs#threadViewPost",
        replies=[valid_grandchild],
        post=SimpleNamespace(uri="child"),
    )
    blocked_child = SimpleNamespace(py_type="app.bsky.feed.defs#notFoundPost", replies=[])
    root = SimpleNamespace(replies=[valid_child, blocked_child])

    replies = list(bluesky_harvester._iter_thread_replies(root))

    assert [reply.post.uri for reply in replies] == ["child", "grandchild"]


def test_bluesky_iter_thread_replies_handles_missing_replies():
    assert list(bluesky_harvester._iter_thread_replies(SimpleNamespace())) == []


def test_bluesky_fetch_replies_filters_by_date_and_skips_missing_posts():
    in_window_post = SimpleNamespace(
        uri="at://did:example/alice/app.bsky.feed.post/in-window",
        cid="cid-in-window",
        author=SimpleNamespace(handle="alice.bsky.social", did="did:example:alice"),
        record=SimpleNamespace(
            text="In window",
            langs=["en"],
            created_at="2024-06-01T00:00:00Z",
            reply=None,
        ),
        reply_count=0,
        repost_count=0,
        like_count=1,
    )
    old_post = SimpleNamespace(
        uri="at://did:example/alice/app.bsky.feed.post/old",
        cid="cid-old",
        author=SimpleNamespace(handle="alice.bsky.social", did="did:example:alice"),
        record=SimpleNamespace(
            text="Old reply",
            langs=["en"],
            created_at="2023-12-31T23:59:59Z",
            reply=None,
        ),
        reply_count=0,
        repost_count=0,
        like_count=1,
    )
    thread = SimpleNamespace(
        py_type="app.bsky.feed.defs#threadViewPost",
        replies=[
            SimpleNamespace(py_type="app.bsky.feed.defs#threadViewPost", replies=[], post=in_window_post),
            SimpleNamespace(py_type="app.bsky.feed.defs#threadViewPost", replies=[], post=old_post),
            SimpleNamespace(py_type="app.bsky.feed.defs#threadViewPost", replies=[]),
        ],
    )
    client = SimpleNamespace(
        app=SimpleNamespace(
            bsky=SimpleNamespace(
                feed=SimpleNamespace(get_post_thread=lambda params: SimpleNamespace(thread=thread))
            )
        )
    )

    replies = bluesky_harvester.fetch_replies(
        client,
        root_uri="at://did:example/alice/app.bsky.feed.post/root",
        city="sydney",
        query="Sydney weather",
        since_iso="2024-01-01T00:00:00Z",
        until_iso="2024-12-31T23:59:59Z",
    )

    assert len(replies) == 1
    assert replies[0]["id"] == "at://did:example/alice/app.bsky.feed.post/in-window"
    assert replies[0]["kind"] == "reply"


def test_bluesky_fetch_replies_returns_empty_for_non_thread_response():
    client = SimpleNamespace(
        app=SimpleNamespace(
            bsky=SimpleNamespace(
                feed=SimpleNamespace(
                    get_post_thread=lambda params: SimpleNamespace(
                        thread=SimpleNamespace(py_type="app.bsky.feed.defs#notFoundPost")
                    )
                )
            )
        )
    )

    assert (
        bluesky_harvester.fetch_replies(
            client,
            root_uri="at://did:example/alice/app.bsky.feed.post/root",
            city="sydney",
            query="Sydney weather",
            since_iso="2024-01-01T00:00:00Z",
            until_iso="2024-12-31T23:59:59Z",
        )
        == []
    )
