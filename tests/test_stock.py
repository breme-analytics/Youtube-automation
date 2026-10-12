import json

import httpx
import pytest

from owd.stock import (
    EDGE_TRIM,
    Pixabay,
    StockError,
    StockVideo,
    best_rendition,
    clip_window,
    rank,
    subject,
    term_list,
)

SHORT, LONG = (1080, 1920), (1920, 1080)


def hit(id_, tags, duration=13, sizes=("large", "medium", "small", "tiny"), vertical=False, **extra):
    dims = {"large": (3840, 2160), "medium": (2560, 1440), "small": (1920, 1080), "tiny": (1280, 720)}
    videos = {}
    for name in sizes:
        w, h = dims[name]
        w, h = (h, w) if vertical else (w, h)
        videos[name] = {"url": f"https://cdn.example/{id_}-{name}.mp4", "width": w, "height": h, "size": w * h // 100,
                        "thumbnail": ""}
    return {"id": id_, "pageURL": f"https://pixabay.com/videos/id-{id_}/", "tags": tags, "duration": duration,
            "user": f"user{id_}", "videos": videos, "downloads": 1000, **extra}


def video(*args, **kwargs):
    return StockVideo.from_api(hit(*args, **kwargs))


def test_from_api_reads_renditions_flags_and_credit():
    v = video(44236, "zebra, animal, plains zebra", isAiGenerated=True)
    assert v.tags == ("zebra", "animal", "plains zebra")
    assert {r.name for r in v.renditions} == {"large", "medium", "small", "tiny"}
    assert v.ai_generated and not v.low_quality
    assert v.credit == "user44236 on Pixabay: https://pixabay.com/videos/id-44236/"


def test_best_rendition_is_the_smallest_that_needs_no_upscaling():
    v = video(1, "zebra")
    assert best_rendition(v, LONG).name == "small"  # 1920x1080 fills 1920x1080 exactly
    assert best_rendition(v, SHORT).name == "large"  # a 9:16 crop needs 4K to stay sharp
    assert best_rendition(v, SHORT, max_upscale=1.4).name == "medium"  # preview: 1.33x is allowed
    assert best_rendition(video(2, "zebra", sizes=("tiny",)), SHORT).name == "tiny"  # all there is


def test_term_list_and_subject():
    assert term_list("Zebras grazing, herds!") == ["zebra", "grazing", "herd"]
    assert subject("owl night") == "owl" and subject("") is None
    assert subject("old book pages") == "book" and subject("calm lake") == "lake"
    assert subject("golden") == "golden"  # only describing words: the first one


def test_long_videos_only_take_landscape_clips():
    clips = [video(1, "owl"), video(2, "owl", vertical=True)]
    assert [v.id for v, _ in rank(clips, "owl", 4.0, LONG)] == [1]


def test_animals_and_holidays_are_skipped_unless_the_search_asks_for_them():
    clips = [video(1, "lake, calm, dog, beech"), video(2, "lake, calm, water"), video(3, "candle, christmas time"),
             video(4, "dogs, running, animal")]
    assert [v.id for v, _ in rank(clips, "lake calm", 4.0, LONG)] == [2]
    assert rank(clips, "candle flame", 4.0, LONG) == []
    assert rank(clips, "candle flame", 4.0, LONG, require_subject=False) == [] or all(
        v.id == 2 for v, _ in rank(clips, "candle flame", 4.0, LONG, require_subject=False))
    assert {v.id for v, _ in rank(clips, "dog running", 4.0, LONG)} == {1, 4}  # the scene is about a dog


def test_rank_needs_the_subject_and_skips_ai_low_quality_and_short_clips():
    found = [
        video(1, "cow herd, cows, farm"),  # 'herd' only: no zebra
        video(2, "zebra, wildlife", isAiGenerated=True),
        video(3, "zebra, animal", isLowQuality=True),
        video(4, "zebra", duration=2),  # too short even slowed down
        video(5, "zebra, animal"),
        video(6, "zebra, herd, savanna"),
    ]
    ranked = rank(found, "zebra herd", 4.0, SHORT)
    assert [v.id for v, _ in ranked] == [6, 5]  # both tags matched ranks first
    assert [v.id for v, _ in rank(found, "zebra herd", 4.0, SHORT, exclude=[6])] == [5]
    loose = rank(found, "zebra herd", 4.0, SHORT, require_subject=False)
    assert 1 in [v.id for v, _ in loose]


def test_rank_prefers_vertical_footage_for_shorts():
    ranked = rank([video(1, "owl"), video(2, "owl", vertical=True)], "owl", 4.0, SHORT)
    assert [v.id for v, _ in ranked] == [2, 1]


def test_clip_window_uses_the_middle_then_continues_and_wraps():
    assert clip_window(13.0, 4.0) == (pytest.approx(4.5), 4.0, 1.0)  # centred in 0.4..12.6
    begin, span, slowdown = clip_window(13.0, 4.0, start=EDGE_TRIM)
    assert (begin, span, slowdown) == (pytest.approx(0.4), 4.0, 1.0)
    assert clip_window(13.0, 4.0, start=4.4)[0] == pytest.approx(4.4)  # the next unseen part
    assert clip_window(13.0, 4.0, start=12.2)[0] == pytest.approx(EDGE_TRIM)  # used up: start again
    begin, span, slowdown = clip_window(4.0, 4.5)  # short clip: slowed down to fill the shot
    assert span == pytest.approx(3.2) and slowdown == pytest.approx(4.5 / 3.2, rel=1e-3)
    assert clip_window(2.0, 6.0)[2] == pytest.approx(1.5)  # never slower than 1.5x


class Clock:
    def __init__(self):
        self.now = 1_000_000.0

    def __call__(self):
        return self.now


def test_search_is_cached_for_a_day_and_never_reveals_the_key(tmp_path):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url)
        return httpx.Response(200, json={"total": 1, "totalHits": 1, "hits": [hit(7, "lion")]})

    clock = Clock()
    stock = Pixabay("SECRET-KEY", tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)), clock=clock)
    assert [v.id for v in stock.search("lion", category="animals")] == [7]
    assert [v.id for v in stock.search("lion", category="animals")] == [7]
    assert len(calls) == 1
    params = dict(calls[0].params)
    assert params["q"] == "lion" and params["category"] == "animals" and params["video_type"] == "film"
    assert params["safesearch"] == "true" and params["key"] == "SECRET-KEY"
    cached = next((tmp_path / "search").glob("*.json")).read_text()
    assert "SECRET-KEY" not in cached
    clock.now += 24 * 3600 + 1
    stock.search("lion", category="animals")
    assert len(calls) == 2
    with pytest.raises(ValueError, match="category"):
        stock.search("lion", category="cats")


def test_rate_limit_waits_then_errors_never_include_the_key(tmp_path):
    responses = iter([httpx.Response(429, headers={"X-RateLimit-Reset": "7"}),
                      httpx.Response(200, json={"hits": []}),
                      httpx.Response(400, text="[ERROR 400] invalid key")])
    waits = []
    stock = Pixabay("SECRET-KEY", tmp_path, http=httpx.Client(transport=httpx.MockTransport(lambda r: next(responses))),
                    sleep=waits.append)
    assert stock.search("owl") == [] and waits == [7.0]
    with pytest.raises(StockError) as error:
        stock.search("fox")
    assert "400" in str(error.value) and "SECRET-KEY" not in str(error.value)

    def broken(request):
        raise httpx.ConnectError("boom", request=request)

    offline = Pixabay("SECRET-KEY", tmp_path, http=httpx.Client(transport=httpx.MockTransport(broken)))
    with pytest.raises(StockError) as error:
        offline.search("bear")
    assert "SECRET-KEY" not in str(error.value)


def test_download_keeps_clips_for_reuse(tmp_path):
    served = []

    def handler(request):
        served.append(str(request.url))
        return httpx.Response(200, content=b"0" * 1000)

    stock = Pixabay("k", tmp_path, http=httpx.Client(transport=httpx.MockTransport(handler)))
    v = video(9, "owl")
    rendition = best_rendition(v, LONG)
    first = stock.download(v, rendition)
    second = stock.download(v, rendition)
    assert first == second and first.read_bytes() == b"0" * 1000 and len(served) == 1
    assert not list(tmp_path.rglob("*.part"))


def test_cache_file_is_valid_json_with_params(tmp_path):
    stock = Pixabay("k", tmp_path, http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, json={"hits": [hit(1, "fox")]}))))
    stock.search("fox")
    cached = json.loads(next((tmp_path / "search").glob("*.json")).read_text())
    assert cached["params"]["q"] == "fox" and cached["data"]["hits"][0]["id"] == 1
