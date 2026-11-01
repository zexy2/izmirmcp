"""Multi-tool prompts only reference real tools and stay additive."""

from __future__ import annotations

import re

import pytest

from app.mcp import prompts
from app.mcp.registry import DEFAULT_TOOL_NAMES

NEW_PROMPTS = (
    prompts.rota_karsilastir,
    prompts.bugun_ne_yapsam,
    prompts.su_durumu_raporu,
    prompts.eczane_ve_ulasim,
    prompts.sehir_simdi,
)
SAMPLES = {
    "rota_karsilastir": {"nereden": "Konak", "nereye": "Karşıyaka"},
    "bugun_ne_yapsam": {"ilce": "Bornova"},
    "su_durumu_raporu": {"ilce": "Buca"},
    "eczane_ve_ulasim": {"ilce": "Karşıyaka", "konum": "Bostanlı"},
    "sehir_simdi": {},
}


def test_new_prompts_are_registered_after_existing_ones():
    names = [p.__name__ for p in prompts.WORKFLOW_PROMPTS]
    assert names[:7] == [
        "gunun_ozeti",
        "veri_kesfi",
        "toplu_ulasim",
        "otobus",
        "pazar_ve_duyurular",
        "sehir_hizmetleri",
        "nobetci_eczane",
    ]
    assert names[7:] == [p.__name__ for p in NEW_PROMPTS]


@pytest.mark.parametrize("prompt", NEW_PROMPTS, ids=lambda p: p.__name__)
def test_every_referenced_tool_exists(prompt):
    text = prompt(**SAMPLES[prompt.__name__])
    referenced = set(re.findall(r"\b(izmir_[a-z_]+)\(", text)) | set(re.findall(r"\b(izmir_[a-z_]+)\b", text))
    assert referenced
    assert referenced <= set(DEFAULT_TOOL_NAMES), referenced - set(DEFAULT_TOOL_NAMES)


@pytest.mark.parametrize("prompt", NEW_PROMPTS, ids=lambda p: p.__name__)
def test_disclaimer_and_freshness_are_present(prompt):
    text = prompt(**SAMPLES[prompt.__name__])
    assert "Resmî olmayan" in text
    assert "freshness" in text


def test_water_prompt_handles_izsu_outage_feed_failure():
    text = prompts.su_durumu_raporu("Buca")
    assert "500" in text and "source_unavailable" in text
    assert "kesinti yok" in text  # explicitly told NOT to read failure as "no outage"


@pytest.mark.parametrize("prompt", NEW_PROMPTS, ids=lambda p: p.__name__)
def test_new_prompts_respect_argument_limit(prompt):
    args = {k: "x" * (prompts.MAX_PROMPT_ARGUMENT_CHARS + 1) for k in SAMPLES[prompt.__name__]}
    if not args:
        args = {"yer": "x" * (prompts.MAX_PROMPT_ARGUMENT_CHARS + 1)}
    with pytest.raises(ValueError):
        prompt(**args)
