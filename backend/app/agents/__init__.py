"""
Agent registry — all evaluation pipeline agents.
"""

from app.agents.consistency import ConsistencyAgent
from app.agents.explainability import ExplainabilityAgent
from app.agents.feedback import FeedbackAgent
from app.agents.rubric_grounding import RubricGroundingAgent
from app.agents.scoring import ScoringAgent
from app.agents.segmentation import SegmentationAgent

__all__ = [
    "SegmentationAgent",
    "RubricGroundingAgent",
    "ScoringAgent",
    "ConsistencyAgent",
    "FeedbackAgent",
    "ExplainabilityAgent",
]
