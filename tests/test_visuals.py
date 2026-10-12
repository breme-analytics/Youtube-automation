import base64
import io

import httpx
import pytest
from PIL import Image

from owd.config import LONG
from owd.images import ImageError, SceneImages
from owd.stock import StockVideo
from owd.storyboard import Scene
from owd.vision import Verdict
from owd.visuals import choose_visuals


def png(size=(1024, 576), colour="navy"):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "PNG")
    return out.getvalue()


def clip(id_, tags):
    return StockVideo.from_api({
        "id": id_, "pageURL": f"https://pixabay.com/videos/id-{id_}/", "tags": tags, "duration": 20, "user": f"u{id_}",
        "downloads": 100,
        "videos": {"large": {"url": f"https://cdn/{id_}.mp4", "width": 3840, "height": 2160, "size": 1,
                             "thumbnail": f"https://cdn/{id_}.jpg"}},
    })


class FakeStock:
    def __init__(self, clips):
        self.clips = clips
        self.previews = []

    def search(self, query, category=None):
        return [c for c in self.clips if query.split()[0] in c.tags[0]]

    def preview(self, video):
        self.previews.append(video.id)
        return png(colour="gray")


class FakeJudge:
    def __init__(self, *scores):
        self.answers = list(scores)
        self.enabled = True
        self.calls = 0

    def judge(self, narration, intent, stills):
        self.calls += 1
        return Verdict(tuple(self.answers.pop(0)[: len(stills)]))


class FakeImages:
    def __init__(self, fail=False):
        self.fail, self.prompts = fail, []

    def generate(self, prompt, seed=0):
        if self.fail:
            raise ImageError("offline")
        self.prompts.append(prompt)
        from owd.images import Generated
        return Generated(f"/tmp/{seed}.png", "pollinations")


SCENES = [
    Scene("candle flame", "The last of his hope burned down.", image="a candle guttering in a dark empty room"),
    Scene("candle flame", "A small light is enough to begin again.", image="a hand shielding a new flame at dawn"),
]
STOCK = [clip(1, "candle, christmas"), clip(2, "candle, flame, dark"), clip(3, "candle, flame")]


def test_the_vision_pick_wins_and_each_scene_gets_a_different_clip():
    stock = FakeStock(STOCK)
    casting = choose_visuals(SCENES, [8.0, 8.0], stock, LONG, judge=FakeJudge([2, 9, 7], [8, 3]), images=FakeImages(),
                             log=lambda m: None)
    first, second = casting.visuals
    shown_first = stock.previews[:3]  # the order the candidates were shown to the judge
    assert (first.kind, first.clip[0].id, first.score) == ("clip", shown_first[1], 9)  # the 9/10 one
    assert second.kind == "clip" and second.clip[0].id != first.clip[0].id  # not reused for the next scene
    assert casting.vision_calls == 2 and casting.warnings == []


def test_a_painting_replaces_footage_that_doesnt_fit():
    images = FakeImages()
    casting = choose_visuals(SCENES[:1], [8.0], FakeStock(STOCK), LONG, judge=FakeJudge([2, 4, 5]), images=images,
                             log=lambda m: None)
    assert casting.visuals[0].kind == "image" and images.prompts == ["a candle guttering in a dark empty room"]
    assert casting.images_made == 1


def test_without_vision_or_paintings_the_best_tag_match_is_used_and_flagged():
    casting = choose_visuals(SCENES[:1], [8.0], FakeStock(STOCK), LONG, judge=FakeJudge([1, 1, 1]),
                             images=FakeImages(fail=True), log=lambda m: None)
    assert casting.visuals[0].kind == "clip" and "no painting" in casting.warnings[0]
    nothing = choose_visuals([Scene("unicorn", "x")], [5.0], FakeStock(STOCK), LONG, judge=None, images=None,
                             log=lambda m: None)
    assert nothing.visuals[0].kind == "none" and "plain background" in nothing.warnings[0]
    tags_only = choose_visuals(SCENES[:1], [8.0], FakeStock(STOCK), LONG, judge=None, images=None, log=lambda m: None)
    assert tags_only.visuals[0].kind == "clip" and tags_only.visuals[0].score is None


def test_scene_images_cache_and_crop_pollinations_and_fall_back(tmp_path):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        if "cloudflare" in str(request.url):
            return httpx.Response(401)
        return httpx.Response(200, content=png(), headers={"content-type": "image/jpeg"})

    env = {"CLOUDFLARE_ACCOUNT_ID": "acc", "CLOUDFLARE_AI_TOKEN": "t"}
    maker = SceneImages(tmp_path, env=env, http=httpx.Client(transport=httpx.MockTransport(handler)), sleep=lambda s: None)
    first = maker.generate("a lantern in a misty garden", seed=1)
    assert first.provider == "pollinations" and Image.open(first.path).size == (1024, 536)  # bottom mark cropped
    again = maker.generate("a lantern in a misty garden", seed=1)
    assert again.path == first.path
    assert sum("cloudflare" in c for c in calls) == 1 and sum("pollinations" in c for c in calls) == 1
    maker.generate("another scene", seed=2)
    assert sum("cloudflare" in c for c in calls) == 1  # a refused token isn't tried again


def test_scene_images_use_cloudflare_first_when_it_works(tmp_path):
    def handler(request):
        assert b'name="prompt"' in request.content and b'name="width"' in request.content
        return httpx.Response(200, json={"result": {"image": base64.b64encode(png((1344, 768))).decode()}})

    maker = SceneImages(tmp_path, env={"CLOUDFLARE_ACCOUNT_ID": "acc", "CLOUDFLARE_AI_TOKEN": "t"},
                        http=httpx.Client(transport=httpx.MockTransport(handler)))
    made = maker.generate("an hourglass on a stone table")
    assert made.provider == "cloudflare" and Image.open(made.path).size == (1344, 768)


def test_small_or_failing_images_raise(tmp_path):
    tiny = SceneImages(tmp_path, env={}, sleep=lambda s: None, http=httpx.Client(transport=httpx.MockTransport(
        lambda r: httpx.Response(200, content=png((300, 200)), headers={"content-type": "image/png"}))))
    with pytest.raises(ImageError, match="too small"):
        tiny.generate("x")
    down = SceneImages(tmp_path / "b", env={}, sleep=lambda s: None,
                       http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503))))
    with pytest.raises(ImageError, match="no image service worked"):
        down.generate("y")
