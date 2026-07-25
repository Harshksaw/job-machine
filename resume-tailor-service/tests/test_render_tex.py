from pathlib import Path
from app.bank import Bullet, Contact, Education, Job, Project, ResumeBank, SkillLine, load_bank
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
        skill_ids=["skill.languages"],
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


def test_render_tex_skills_render_actual_values_not_dict_items_method():
    # BUG 1 regression: skills used to be passed as plain dicts and the
    # template accessed `line.items`, which Jinja resolves to the dict's
    # bound `.items()` method (not the "items" key), producing a rendered
    # method repr like "<built-in method items of dict object at 0x...>".
    bank = load_bank(FIXTURE)
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "built-in method" not in tex
    assert "Python, Go" in tex


def test_render_tex_uses_only_selected_skill_categories():
    bank = load_bank(FIXTURE)
    bank.skills.append(
        SkillLine(id="skill.cloud", category="Cloud", items="AWS, Docker")
    )
    tex = render_tex(_manifest(), bank, TEMPLATE_DIR)
    assert "Python, Go" in tex
    assert "AWS, Docker" not in tex


def test_render_tex_escapes_special_characters_in_bank_fields():
    # BUG 2 regression: bullets/fields containing raw LaTeX special
    # characters (&, %, etc.) must be escaped at render time so the
    # bank itself can stay plain, human-readable text.
    bank = ResumeBank(
        contact=Contact(
            name="A & B",
            phone="1 & 2",
            location="X & Y",
            email="a@b.com",
            linkedin_url="https://example.com/a&b",
            github_url="https://example.com/gh&ub",
            website_url="https://example.com/site&page",
            website_display="site.com & co",
        ),
        education=Education(degree="B.Sc. & Such", school="Uni & Co", date="2024 & beyond"),
        jobs=[
            Job(
                id="j1",
                company="C & D",
                location="L & L",
                title="T & T",
                dates="2020 -- 2021",
                bullets=[Bullet(id="j1.b1", text="Did X & Y at 70%")],
            )
        ],
        projects=[
            Project(
                id="p1",
                name="P & Q",
                tech="A & B",
                bullets=[Bullet(id="p1.b1", text="Built X & Y")],
            )
        ],
        achievements=[Bullet(id="a1", text="Won X & Y award, 70%")],
        skills=[SkillLine(category="Cat & Sub", items="X & Y, 70%")],
    )
    manifest = Manifest(
        summary="Engineer.",
        job_selections=[JobSelection(job_id="j1", bullet_ids=["j1.b1"])],
        project_selections=[ProjectSelection(project_id="p1", bullet_ids=["p1.b1"])],
        achievement_ids=["a1"],
        job_trim_priority=["j1"],
    )
    tex = render_tex(manifest, bank, TEMPLATE_DIR)

    assert r"C \& D" in tex
    assert r"Did X \& Y at 70\%" in tex
    assert r"P \& Q" in tex
    assert r"Built X \& Y" in tex
    assert r"Won X \& Y award, 70\%" in tex
    assert r"Cat \& Sub" in tex
    assert r"X \& Y, 70\%" in tex
    assert r"B.Sc. \& Such" in tex
    assert r"Uni \& Co" in tex
    assert r"site.com \& co" in tex

    # URL fields must stay raw (unescaped) since they go inside \href{...}.
    assert "https://example.com/a&b" in tex
    assert "https://example.com/gh&ub" in tex
    assert "https://example.com/site&page" in tex
