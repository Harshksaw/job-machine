import pytest

from app.regions import Classification, classify_location, is_india


@pytest.mark.parametrize(
    "location, tier, region",
    [
        # Tier A: open to Canada, or anywhere.
        ("Canada", "A", "canada"),
        ("Remote - Canada", "A", "canada"),
        ("USA, Canada", "A", "canada"),
        ("North America", "A", "canada"),
        ("Toronto, ON", "A", "canada"),
        ("Americas", "A", "canada"),
        ("Worldwide", "A", "worldwide"),
        ("Anywhere in the World", "A", "worldwide"),
        ("Global", "A", "worldwide"),
        ("Europe, Canada", "A", "canada"),
        ("", "A", "unspecified"),
        ("Remote", "A", "unspecified"),
        # Tier A2: limited to US, UK, Australia, New Zealand or another non India country.
        ("USA", "A2", "us"),
        ("US", "A2", "us"),
        ("United States", "A2", "us"),
        ("US Only", "A2", "us"),
        ("Remote (U.S.)", "A2", "us"),
        ("US time zones", "A2", "us"),
        ("United Kingdom", "A2", "uk"),
        ("UK", "A2", "uk"),
        ("London, England", "A2", "uk"),
        ("Belfast, Northern Ireland", "A2", "uk"),
        ("Australia", "A2", "australia"),
        ("New Zealand", "A2", "new zealand"),
        ("NZ", "A2", "new zealand"),
        ("Brazil", "A2", "other"),
        ("LATAM", "A2", "other"),
        ("Latin America", "A2", "other"),
        ("Philippines", "A2", "other"),
        ("UK, Germany", "A2", "uk"),
        ("Australia, New Zealand", "A2", "australia"),
        ("US or Europe", "A2", "us"),
        # Tier E: Europe, last priority but kept.
        ("Europe", "E", "europe"),
        ("EU", "E", "europe"),
        ("EMEA", "E", "europe"),
        ("Germany", "E", "europe"),
        ("Berlin, Germany", "E", "europe"),
        ("Ireland", "E", "europe"),
        ("Netherlands", "E", "europe"),
        ("Switzerland", "E", "europe"),
        ("Norway", "E", "europe"),
        ("Iceland", "E", "europe"),
        ("Liechtenstein", "E", "europe"),
        ("Czechia", "E", "europe"),
        ("Spain, Portugal, Poland", "E", "europe"),
        ("Remote (CET +/- 2 hours)", "E", "europe"),
    ],
)
def test_classify_location_tiers(location, tier, region):
    result = classify_location(location)
    assert isinstance(result, Classification)
    assert (result.tier, result.region) == (tier, region), location
    assert result.reason == ""


@pytest.mark.parametrize(
    "location",
    ["India", "Bengaluru, India", "Bangalore", "US, India", "Worldwide, India",
     "Canada or India", "Remote - Hyderabad", "Europe, India"],
)
def test_india_is_dropped_even_with_another_match(location):
    result = classify_location(location)
    assert (result.tier, result.reason) == ("drop", "india")


@pytest.mark.parametrize("location", ["Hybrid - Toronto", "On-site, Austin", "Onsite"])
def test_hybrid_or_onsite_location_is_dropped(location):
    result = classify_location(location)
    assert (result.tier, result.reason) == ("drop", "not remote")


def test_us_match_is_strict():
    # Lowercase "us" in prose is not the United States.
    assert classify_location("Come work with us").region == "other"
    assert classify_location("Join us anywhere").tier == "A"
    # Indiana is a US state, not India.
    assert classify_location("Indianapolis, Indiana").tier != "drop"
    assert not is_india("Indiana")
    assert is_india("Pune, India")


def test_remote_scope_is_read_with_location():
    assert classify_location("Remote", "Canada").tier == "A"
    assert classify_location("Remote", "Germany").tier == "E"
    assert classify_location("Remote", "US, India").reason == "india"


def test_rank_follows_country_order():
    order = ["Canada", "USA", "UK", "Australia", "New Zealand", "Brazil", "Germany"]
    ranks = [classify_location(place).rank for place in order]
    assert ranks == sorted(ranks)
    assert len(set(ranks)) == len(ranks)
