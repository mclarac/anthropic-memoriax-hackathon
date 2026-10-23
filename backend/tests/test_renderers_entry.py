import pytest

from memoria.renderers import render_asset


def test_unknown_asset_type_raises(tmp_path):
    with pytest.raises(ValueError, match="webinar"):
        render_asset("webinar", {}, [], tmp_path, "x", "/u")
    assert not list(tmp_path.iterdir())


def test_out_dir_is_created(tmp_path):
    blog = {"title": "T", "slug": "t", "meta_description": "d", "body_markdown": "Hi", "cta": "Go",
            "placeholders": []}
    out = tmp_path / "a" / "b"
    files = render_asset("blog", blog, [], out, "post", "/u")
    assert (out / "post.html").exists() and files
