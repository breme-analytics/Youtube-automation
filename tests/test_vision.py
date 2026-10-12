import io
import json

import httpx
from PIL import Image

from owd.vision import GOOD_ENOUGH, Verdict, VisionJudge, thumbnail_bytes


def jpeg(colour="red", size=(640, 360)):
    out = io.BytesIO()
    Image.new("RGB", size, colour).save(out, "JPEG")
    return out.getvalue()


def answer(scores, reason="fits"):
    text = json.dumps({"scores": scores, "reason": reason})
    return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": text}]}}]})


class Clock:
    def __init__(self):
        self.now, self.slept = 0.0, []

    def time(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def judge(handler, clock=None, **kwargs):
    clock = clock or Clock()
    return VisionJudge("G-KEY", http=httpx.Client(transport=httpx.MockTransport(handler)),
                       clock=clock.time, sleep=clock.sleep, **kwargs), clock


def test_thumbnail_is_small():
    small = Image.open(io.BytesIO(thumbnail_bytes(jpeg(size=(1920, 1080)))))
    assert max(small.size) == 384


def test_verdict_ranks_only_good_enough_candidates():
    verdict = Verdict((3, 9, 6, 9))
    assert verdict.ranked() == [1, 3, 2] and Verdict((1, 2)).ranked() == []
    assert GOOD_ENOUGH == 6


def test_judge_sends_every_still_with_the_narration_and_parses_scores():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return answer([2, 8, 5])

    j, clock = judge(handler)
    verdict = j.judge("The last of his hope burned down like a candle.", "candle flame", [jpeg(), jpeg("blue"), jpeg("green")])
    assert verdict.scores == (2, 8, 5) and verdict.ranked() == [1]
    parts = seen[0]["contents"][0]["parts"]
    assert sum("inlineData" in part for part in parts) == 3
    assert "last of his hope" in parts[-1]["text"] and "candle flame" in parts[-1]["text"]
    assert j.calls == 1


def test_judge_paces_calls_and_waits_out_one_rate_limit():
    responses = iter([answer([7]), httpx.Response(429), answer([4])])
    j, clock = judge(lambda request: next(responses))
    j.judge("a", "b", [jpeg()])
    j.judge("c", "d", [jpeg()])
    assert 60 in clock.slept  # the 429 waited a minute
    assert any(0 < s <= 4.5 for s in clock.slept)  # calls are spaced out


def test_judge_gives_up_cleanly():
    j, _ = judge(lambda request: httpx.Response(403))
    assert j.judge("a", "b", [jpeg()]) is None and not j.enabled
    wrong_count, _ = judge(lambda request: answer([5, 5]))
    assert wrong_count.judge("a", "b", [jpeg()]) is None  # two scores for one still
    assert VisionJudge("").judge("a", "b", [jpeg()]) is None  # no key, no calls
