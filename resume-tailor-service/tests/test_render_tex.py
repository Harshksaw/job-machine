from pathlib import Path
from app.bank import load_bank
from app.models import Manifest, JobSelection, ProjectSelection
from app.render_tex import render_tex, latex_escape

FIXTURE = Path(__file__).parent / "fixtures" / "sample_bank.yaml"
TEMPLATE_DIR = Path(__file__).parent.parent / "templates"


def _manifest():
    return Manifest(
        summary="Backend engineer, 500 widgets/hour.",
        job_selections=[JobSelection(job_id="acme", bullet_ids=["acme.bullet.1"])],
        project_selections=[
            ProjectSelection(project_id="widgetizer", bullet_ids=["project.widgetizer.bullet.1"])
        ],
        achievement_ids=["achievement.1"],
        job_trim_priority=["acme"],
    )


def test_render_tex_includes_selected_content():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "Test Person" in tex
    assert "Built a widget pipeline processing 500 widgets per hour." in tex
    assert "Widgetizer" in tex
    assert "Won the regional Test Hackathon." in tex


def test_render_tex_excludes_unselected_bullets():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "Reduced widget latency by 40 percent." not in tex


def test_render_tex_jobs_stay_in_chronological_bank_order():
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert tex.index("Acme Corp") < tex.index("Achievements")


def test_latex_escape_handles_special_characters():
    assert latex_escape("50% & growing_fast #1") == r"50\% \& growing\_fast \#1"
