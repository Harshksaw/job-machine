from app.slug import safe_slug


def test_safe_slug_lowercases_and_hyphenates_spaces():
    assert safe_slug("Acme Corp", "Backend Engineer") == "acme-corp-backend-engineer"


def test_safe_slug_strips_special_chars():
    assert safe_slug("Foo, Inc.", "Sr. C++ Dev!") == "foo-inc.-sr.-c-dev"


def test_safe_slug_strips_path_traversal():
    slug = safe_slug("../../etc", "x")
    assert "/" not in slug
    assert ".." not in slug
    assert slug


def test_safe_slug_falls_back_to_job_when_empty():
    assert safe_slug("..", "..") == "job"
    assert safe_slug("", "") == "job"
