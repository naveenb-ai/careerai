# Import all ORM models to ensure SQLAlchemy metadata includes every table.
# This module is intended to be imported once at application startup.

from app.models.agent_run import AgentRun  # noqa: F401
from app.models.agent_state import AgentState  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.chat_log import ChatLog  # noqa: F401
from app.models.cover_letter_draft import CoverLetterDraft  # noqa: F401
from app.models.builder_session import BuilderSession  # noqa: F401
from app.models.resume_version import ResumeVersion  # noqa: F401
from app.models.education import Education  # noqa: F401
from app.models.experience import Experience  # noqa: F401
from app.models.internship import Internship  # noqa: F401
from app.models.internship_skill import InternshipSkill  # noqa: F401
from app.models.interview_answer import InterviewAnswer  # noqa: F401
from app.models.interview_question import InterviewQuestion  # noqa: F401
from app.models.interview_report import InterviewReport  # noqa: F401
from app.models.interview_session import InterviewSession  # noqa: F401
from app.models.linkedin_report import LinkedInReport  # noqa: F401
from app.models.linkedin_session import LinkedInSession  # noqa: F401
from app.models.notification import Notification  # noqa: F401
from app.models.password_reset_token import PasswordResetToken  # noqa: F401
from app.models.project import Project  # noqa: F401
from app.models.recommendation import Recommendation  # noqa: F401
from app.models.resume import Resume  # noqa: F401
from app.models.resume_analysis import ResumeAnalysis  # noqa: F401
from app.models.resume_data import ResumeData  # noqa: F401
from app.models.skill import Skill  # noqa: F401
from app.models.skill_snapshot import SkillSnapshot  # noqa: F401
from app.models.user import User  # noqa: F401





