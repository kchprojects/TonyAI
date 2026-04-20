import asyncio
import time
from typing import Any, Union
from urllib import response

from poetry import json
from enum import Enum

from tony_ai.agents.copilot_agent import CopilotAgent
from tony_ai.config import DEFAULT_MODEL, DEFAULT_PRO_MODEL

from logging import getLogger
logger = getLogger(__name__)
logger.setLevel("INFO")



class WorkflowModifier:
    def __init__(self, description: str):
        self.description = description

class ActivityType(Enum):
    CODING  = "CODING"
    DOCUMENTATION = "DOCUMENTATION"
    DESIGN = "DESIGN"
    TESTING = "TESTING"
    RESEARCH = "RESEARCH"
    PLANNING = "PLANNING"
    CHATTING = "CHATTING"
    OTHER = "OTHER"

    def get_best_model(self):
        if self in {
            ActivityType.CODING,
            ActivityType.DOCUMENTATION,
            ActivityType.DESIGN,
            ActivityType.TESTING,
            ActivityType.RESEARCH,
            ActivityType.PLANNING}:
            return DEFAULT_PRO_MODEL
        else:
            return DEFAULT_MODEL

        
class MessageContext:
    def __init__(self, project_name:str, activity_type: Union[ActivityType,str]):
        self.project_name = project_name
        self.activity_type = activity_type if isinstance(activity_type, ActivityType) else ActivityType(activity_type)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "MessageContext":
        return MessageContext(
            project_name=d.get("project_name", ""),
            activity_type=d.get("activity_type", ActivityType.OTHER.value)
        )
    
class SemanticAnalyzer(CopilotAgent):
    def __init__(self) -> None:
        super().__init__()
        self._agent_md =f"""
        Your task is to analyze the user's message. Your task is to extract context of the users message.
        You always return a JSON object with the following fields:
        - 'activity_type': one of { [t.value for t in ActivityType] }
        - 'project_name': if the message references a specific project, extract the project name (e.g. "website", "mobile app", "data pipeline"). Otherwise, return null.
        NEVER response anything else than the JSON object described above. Do not include any explanatory text, just return the JSON object.
        """
        self._loop = asyncio.new_event_loop()    
        self.pro_model = DEFAULT_MODEL
        self.base_model = DEFAULT_MODEL

    def analyze(self, text: str) -> MessageContext:
        out = None
        response = self._loop.run_until_complete(self.send("semantic_analysis", text,pro=False)) # semantic analysis is lightweight, so we can use the base model
        print(response)        
        try:
            analysis = response.get("choices", [{}])[0].get("message", {}).get("content", "")
            out = MessageContext.from_dict(json.loads(analysis))
        except Exception as exc:
            logger.error(f"Error analyzing message: {exc}", exc_info=True)
            out = MessageContext(project_name="", activity_type=ActivityType.OTHER)
        return out
    
if __name__ == "__main__":
    analyzer = SemanticAnalyzer()
    context = analyzer.analyze("Budu pracovat na projektu tony_ai a chci abys udelal research aktualnich zmen")
    print(f"Project: {context.project_name}, Activity Type: {context.activity_type}")
