"""The chatbot's language safety net and model setting."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from server import SYSTEM_PROMPT, clean_reply  # noqa: E402


def test_abusive_words_are_masked_in_any_case_and_script():
    assert clean_reply("You are a Bastard") == "You are a *******"
    assert "chutiya" not in clean_reply("tu chutiya hai").lower()
    assert "BSDK" not in clean_reply("BSDK kya bol raha")
    assert "हरामी" not in clean_reply("वो हरामी है")
    assert clean_reply("what the f**k") == "what the f**k"  # already masked text is left alone


def test_medical_and_normal_words_are_never_masked():
    for text in ("Condoms and the pill both protect against pregnancy.", "Breast self-exam once a month helps.",
                 "Sexual health clinics test for STIs confidentially.", "Dr. Dickson sees patients on Monday.",
                 "Shitake mushrooms are fine to eat.", "Scunthorpe hospital is open 24 hours.",
                 "Aapka appointment kal 10 baje hai.", "आपकी बुकिंग हो गई है।", "Assess the symptoms first."):
        assert clean_reply(text) == text, text


def test_prompt_has_the_language_rules():
    assert "Never use vulgar" in SYSTEM_PROMPT and "Answer exactly what was asked" in SYSTEM_PROMPT
    assert "describing abuse" in SYSTEM_PROMPT  # victims are supported, not treated as rude


def test_model_setting_and_fallbacks_follow_the_model():
    code = "import server; print(server.MODEL, bool(server.FALLBACK_KW))"
    run = lambda model: subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                       env={**os.environ, "AI_MODEL": model}).stdout.split()
    assert run("") == ["claude-opus-5-5", "True"]          # default unchanged
    assert run("claude-haiku-5-5") == ["claude-haiku-5-5", "False"]  # no server-side fallback on Haiku
    assert run("claude-sonnet-5-5") == ["claude-sonnet-5-5", "True"]
